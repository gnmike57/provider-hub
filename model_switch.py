"""Runtime model switching - `/v1/switch` (operator alias: `/switch`).

Lets the operator hot-swap which configured model sits in the PRIMARY slot and
which sits in the SPECIALIST (worker) slot, while the gateway keeps serving.

    POST /v1/switch {"target": "primary", "provider": "hive", "model": "deepfrost"}
    POST /v1/switch {"target": "worker",  "model": "cyberfrost"}
    POST /v1/switch {"target": "swap"}
    POST /v1/switch {}                       # -> status snapshot

Seamlessness contract (what "seamless" means operationally):

  1. New requests pick up the new binding immediately: the chat path reads the
     slot fields from Settings per request, so the very next dispatch - normal
     stream, divert or hedge - uses the switched upstream.
  2. In-flight requests are untouched: they hold the settings copy (and the
     open stream) they started with, so a conversation never jumps providers
     mid-answer.
  3. A failed switch never locks the operator out. The new binding is probed
     with a cheap GET {base}/models, but verification is ADVISORY: the switch
     is applied either way and the outcome is reported honestly
     (`verified: true|false`). A savepoint is kept, so
     {"target": "...", "rollback": true} restores the previous binding
     atomically - the same fail-open philosophy as Gate 7's kill switch
     (NO_GO_ENABLED=0) and the Tier 4 classifier's never-force-a-divert rule.
  4. Every switch, failed verify and rollback lands in the audit trail
     (ingress_assembler.audit_record, signals switch_*), so the jsonl log
     answers "which binding served which window" afterwards.

Targets resolve through the provider registry (gateway_registry.json):
  - {"provider": "hive", "model": "deepfrost"}  explicit provider + exposed name
  - {"model": "cyberfrost"}                     unique-provider model lookup
  - {"model": "deepfrost"}                      Frost name -> slot + upstream id
  - {"url": ..., "key": ..., "model": ...}      raw out-of-registry override

Design rules honoured here (proxy_gateway header):
  6. Guards run once, shared by the endpoints (authz is enforced by the caller).
  7. Hooks never raise into the request path - everything returns a structured
     result; the endpoint decides the status code.

Run: imported by proxy_gateway (no fastapi/httpx import of its own; the caller
passes the shared httpx client in).
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "SwitchError",
    "SwitchRequest",
    "SlotBinding",
    "SlotManager",
    "parse_switch_request",
    "resolve_target",
    "verify_target",
    "perform_switch",
    "manager",
    "SWITCH_TARGETS",
]

SWITCH_TARGETS = ("primary", "worker", "swap", "status")


class SwitchError(Exception):
    """Validation failure - the endpoint turns this into a 400/404."""

    def __init__(self, detail: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(detail)


# --------------------------------------------------------------------------
# Request parsing / validation (F5 preserved: a malformed body is a 400)
# --------------------------------------------------------------------------
@dataclass
class SwitchRequest:
    target: str
    provider: str = ""
    model: str = ""
    url: str = ""
    key: Optional[str] = None  # None = "keep existing" for raw targets
    verify: bool = True
    rollback: bool = False


def parse_switch_request(body) -> SwitchRequest:
    """Validate a /v1/switch body. Raises SwitchError(400) on garbage."""
    body = body or {}
    if not isinstance(body, dict):
        raise SwitchError("request body must be a JSON object")
    target = str(body.get("target") or "status").strip().lower()
    if target not in SWITCH_TARGETS:
        raise SwitchError(
            f"unknown target {target!r}; expected one of {', '.join(SWITCH_TARGETS)}"
        )
    req = SwitchRequest(
        target=target,
        provider=str(body.get("provider") or "").strip(),
        model=str(body.get("model") or "").strip(),
        url=str(body.get("url") or "").strip(),
        key=body.get("key") if isinstance(body.get("key"), str) else None,
        verify=body.get("verify") is not False,
        rollback=body.get("rollback") is True,
    )
    if req.target in ("primary", "worker") and not req.rollback:
        if not req.model and not req.url:
            raise SwitchError(
                f"target {req.target!r} needs a 'model' (with optional 'provider', "
                "or raw 'url'/'key') - or 'rollback': true"
            )
        if req.url and not req.model:
            raise SwitchError("a raw 'url' target still needs a 'model' id")
    return req


# --------------------------------------------------------------------------
# Slot state
# --------------------------------------------------------------------------
@dataclass
class SlotBinding:
    """One slot's binding, as reported by status/healthz (never the key)."""

    model: str = ""
    url: str = ""
    key_present: bool = False
    provider_id: str = ""
    updated_ts: Optional[float] = None  # None = never switched since boot
    updated_by: str = ""  # request id of the switch that last wrote it

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "url": self.url,
            "key_present": self.key_present,
            "provider_id": self.provider_id,
            "updated_ts": self.updated_ts,
            "updated_by": self.updated_by,
        }


@dataclass
class SwitchEvent:
    ts: float
    request_id: str
    principal: str
    target: str
    action: str  # applied | verified | verify_failed | rolled_back
    detail: str = ""


class SlotManager:
    """Thread-safe runtime owner of the two slots.

    All writes run under one lock and only after validation has succeeded, so
    a rejected switch can never leave a half-written binding. A savepoint of
    both slots is kept for rollback after a bad switch.
    """

    def __init__(self, settings):
        self._settings = settings
        self._lock = threading.Lock()
        self.primary = SlotBinding(
            model=getattr(settings, "primary_model", ""),
            url=getattr(settings, "primary_api_url", ""),
            key_present=bool(getattr(settings, "primary_api_key", "")),
        )
        self.worker = SlotBinding(
            model=getattr(settings, "fallback_model", ""),
            url=getattr(settings, "fallback_api_url", ""),
            key_present=bool(getattr(settings, "fallback_api_key", "")),
        )
        self._savepoint = None
        self.events = []

    # ---- reads -----------------------------------------------------------
    def settings(self):
        """The live settings. The gateway reads slot fields per request."""
        return self._settings

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "primary": self.primary.as_dict(),
                "worker": self.worker.as_dict(),
                "last_events": [
                    {
                        "ts": round(e.ts, 3),
                        "request_id": e.request_id,
                        "principal": e.principal,
                        "target": e.target,
                        "action": e.action,
                        "detail": e.detail,
                    }
                    for e in self.events[-8:]
                ],
            }

    def record(self, request_id, principal, target, action, detail=""):
        self.events.append(
            SwitchEvent(time.time(), request_id, principal, target, action, detail)
        )
        del self.events[:-8]

    # ---- writes ----------------------------------------------------------
    def _binding_for(self, target: str) -> SlotBinding:
        return self.primary if target == "primary" else self.worker

    def _capture_savepoint(self) -> None:
        """Snapshot both slots from the live settings (caller holds the lock)."""
        s = self._settings
        self._savepoint = {
            "primary": (s.primary_api_url, s.primary_api_key, s.primary_model),
            "worker": (s.fallback_api_url, s.fallback_api_key, s.fallback_model),
        }

    def apply(self, *, target, url, key, model, provider_id="",
              request_id="", principal="") -> SlotBinding:
        """Atomically write one slot (primary or worker) on the live settings.

        The FIRST mutation of a session captures the pre-mutation state as the
        rollback savepoint (an explicit savepoint() may have been called even
        earlier; whichever comes first wins), so rollback always restores BOTH
        slots to the last known-good binding - a savepoint taken after a
        mutation used to bake that mutation in, making it unrollbackable.
        """
        with self._lock:
            if self._savepoint is None:
                self._capture_savepoint()
            s = self._settings
            if target == "primary":
                s.primary_api_url = url
                s.primary_api_key = key
                s.primary_model = model
            else:
                s.fallback_api_url = url
                s.fallback_api_key = key
                s.fallback_model = model
            binding = self._binding_for(target)
            binding.model = model
            binding.url = url
            binding.key_present = bool(key)
            binding.provider_id = provider_id
            binding.updated_ts = time.time()
            binding.updated_by = request_id
            return binding

    def savepoint(self) -> None:
        """Snapshot both slots; used by rollback after a bad switch.

        Sticky: only the FIRST capture wins (apply() also captures on first
        mutation), so a savepoint taken after a mutation can no longer bake
        that mutation into the rollback target.
        """
        with self._lock:
            if self._savepoint is None:
                self._capture_savepoint()

    def has_savepoint(self) -> bool:
        with self._lock:
            return self._savepoint is not None

    def rollback(self, *, request_id: str = "", principal: str = "") -> bool:
        """Restore the pre-switch bindings. True when a savepoint existed."""
        with self._lock:
            sp = self._savepoint
            if not sp:
                return False
            s = self._settings
            s.primary_api_url, s.primary_api_key, s.primary_model = sp["primary"]
            s.fallback_api_url, s.fallback_api_key, s.fallback_model = sp["worker"]
            for target, binding in (("primary", self.primary), ("worker", self.worker)):
                url, key, model = sp[target]
                binding.model = model
                binding.url = url
                binding.key_present = bool(key)
                binding.provider_id = ""
                binding.updated_ts = time.time()
                binding.updated_by = request_id
            self.record(request_id, principal, "both", "rolled_back")
            return True

    def swap(self, *, request_id: str = "", principal: str = "") -> None:
        """Exchange the two slots' bindings atomically."""
        with self._lock:
            s = self._settings
            s.primary_api_url, s.fallback_api_url = s.fallback_api_url, s.primary_api_url
            s.primary_api_key, s.fallback_api_key = s.fallback_api_key, s.primary_api_key
            s.primary_model, s.fallback_model = s.fallback_model, s.primary_model
            now = time.time()
            p, w = self.primary, self.worker
            p.model, w.model = w.model, p.model
            p.url, w.url = w.url, p.url
            p.key_present, w.key_present = w.key_present, p.key_present
            p.provider_id, w.provider_id = w.provider_id, p.provider_id
            p.updated_ts, p.updated_by = now, request_id
            w.updated_ts, w.updated_by = now, request_id


# --------------------------------------------------------------------------
# Target resolution + verification (upstream probe)
# --------------------------------------------------------------------------
def _norm_model(name: str) -> str:
    return " ".join(str(name or "").strip().lower().replace("_", " ").split())


def resolve_target(req, settings, registry=None) -> dict:
    """Turn a SwitchRequest into a concrete (url, key, model) binding.

    Resolution order:
      1. raw url+model        - out-of-registry override, used verbatim
      2. provider+model       - registry lookup inside one named provider
      3. bare model           - unique-provider lookup across the registry
      4. Frost name           - resolve_frost_alias: slot + upstream id; the
                                URL/key stay the CURRENT binding of the slot
                                the name points at (pure slot-swap semantics)
    Raises SwitchError with a 4xx status when nothing resolves.
    """
    if req.url and req.model:  # (1) raw override
        return {
            "url": req.url.rstrip("/"),
            "key": "" if req.key is None else req.key,
            "model": req.model,
            "provider_id": "raw",
        }

    if registry is not None:
        reg = registry
        reg.reload()
        if req.provider and req.model:  # (2) explicit provider
            provider = reg.providers.get(req.provider)
            if provider is None:
                raise SwitchError(f"unknown provider {req.provider!r}", status_code=404)
            upstream = provider.models.get(req.model) or (
                req.model if req.model in provider.models.values() else None
            )
            if upstream is None:
                raise SwitchError(
                    f"provider {req.provider!r} does not expose model {req.model!r}",
                    status_code=404,
                )
            return {
                "url": provider.chat_url(),
                "key": provider.key,
                "model": upstream,
                "provider_id": provider.id,
            }
        if req.model:  # (3) unique-provider lookup across the registry
            hits = [
                p
                for p in reg.providers.values()
                if req.model in p.models or req.model in p.models.values()
            ]
            if len(hits) > 1:
                names = ", ".join(sorted(p.id for p in hits))
                raise SwitchError(
                    f"model {req.model!r} is exposed by several providers ({names}); "
                    "pass 'provider' to disambiguate"
                )
            if hits:
                p = hits[0]
                upstream = p.models.get(req.model, req.model)
                return {
                    "url": p.chat_url(),
                    "key": p.key,
                    "model": upstream,
                    "provider_id": p.id,
                }

    if req.model:  # (4) Frost name -> slot + upstream id
        from providers import resolve_frost_alias

        frost = resolve_frost_alias(req.model)
        if frost is not None:
            slot, upstream = frost
            if slot == "primary":
                return {
                    "url": settings.primary_api_url,
                    "key": settings.primary_api_key,
                    # frost-general carries no baked-in upstream: it IS the
                    # slot's current default (pure slot-swap semantics).
                    "model": upstream or settings.primary_model,
                    "provider_id": "frost:primary",
                }
            # The Frost worker names address the frost-worker endpoint, not the
            # specialist binding SPECIALIST_API_URL repoints the divert target
            # at (a CYBER-FROST id on the specialist URL is a guaranteed 400,
            # measured live) - fall back to the fallback slot when the
            # dedicated endpoint is unset (getattr: tests pass namespaces).
            wurl = getattr(settings, "frost_worker_api_url", "") or settings.fallback_api_url
            wkey = (getattr(settings, "frost_worker_api_key", "")
                    if getattr(settings, "frost_worker_api_url", "")
                    else settings.fallback_api_key)
            return {
                "url": wurl,
                "key": wkey,
                "model": upstream or settings.fallback_model,
                "provider_id": "frost:worker",
            }
    raise SwitchError(
        f"could not resolve model {req.model!r}"
        + (f" on provider {req.provider!r}" if req.provider else "")
        + ": not in the registry and not a Frost name",
        status_code=404,
    )


async def verify_target(http, url: str, key: str) -> dict:
    """Cheap liveness probe of a would-be binding: GET {base}/models.

    Returns {"ok": bool, "detail": str}. NEVER raises (design rule 7). Any
    2xx counts as verified; auth errors are reported distinctly because a
    wrong key is the most common bad switch.
    """
    root = url.rstrip("/")
    for suffix in ("/chat/completions", "/messages"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
    headers = {}
    if key and key != "none":
        headers["Authorization"] = f"Bearer {key}"
    try:
        resp = await http.get(root + "/models", headers=headers, timeout=10.0)
        try:
            await resp.aclose()
        except Exception:
            pass
    except Exception as exc:  # transport errors, DNS, timeouts
        return {"ok": False, "detail": f"probe failed: {exc}"}
    if 200 <= resp.status_code < 300:
        return {"ok": True, "detail": "models endpoint answered 2xx"}
    if resp.status_code in (401, 403):
        return {"ok": False, "detail": f"auth rejected by upstream (HTTP {resp.status_code})"}
    return {"ok": False, "detail": f"upstream answered HTTP {resp.status_code}"}


# --------------------------------------------------------------------------
# Orchestrator: one call from the endpoint, everything structured
# --------------------------------------------------------------------------
async def perform_switch(
    req, *, settings, http, registry=None, request_id="", principal="",
    audit_log="",
) -> dict:
    """Apply a switch request end to end.

    Returns the response payload dict. Raises SwitchError only for validation
    problems (the endpoint maps SwitchError.status_code onto the response).
    """
    from ingress_assembler import audit_record

    mgr = _manager_for(settings)
    req = req if isinstance(req, SwitchRequest) else parse_switch_request(req)

    if req.target == "status":
        snap = mgr.snapshot()
        return {"ok": True, "switched": "status", **snap}

    if req.rollback:
        if not mgr.has_savepoint():
            raise SwitchError("nothing to roll back: no switch has been applied yet")
        mgr.rollback(request_id=request_id, principal=principal)
        audit_record(
            request_id=request_id,
            primary_model=settings.primary_model,
            worker_model=settings.fallback_model,
            signal="switch_rollback",
            mode="switch",
            principal=principal,
            audit_log=audit_log,
        )
        snap = mgr.snapshot()
        return {"ok": True, "switched": "rollback", **snap}

    # savepoint FIRST: every mutating switch can be undone with rollback:true
    mgr.savepoint()

    if req.target == "swap":
        mgr.swap(request_id=request_id, principal=principal)
        audit_record(
            request_id=request_id,
            primary_model=settings.primary_model,
            worker_model=settings.fallback_model,
            signal="switch_swap",
            mode="switch",
            principal=principal,
            audit_log=audit_log,
        )
        snap = mgr.snapshot()
        return {"ok": True, "switched": "swap", **snap}

    resolved = resolve_target(req, settings, registry)
    target_url = resolved["url"] or (
        settings.primary_api_url if req.target == "primary" else settings.fallback_api_url
    )
    target_key = resolved["key"]
    if target_key == "none":
        target_key = ""  # registry placeholder for "no key"

    verified = {"ok": True, "detail": "verification skipped (verify:false)"}
    if req.verify:
        verified = await verify_target(http, target_url, target_key)

    binding = mgr.apply(
        target=req.target,
        url=target_url,
        key=target_key,
        model=resolved["model"],
        provider_id=resolved["provider_id"],
        request_id=request_id,
        principal=principal,
    )
    mgr.record(
        request_id,
        principal,
        req.target,
        "verified" if verified["ok"] else "verify_failed",
        verified["detail"],
    )
    signal = "switch_" + req.target + ("" if verified["ok"] else "_unverified")
    audit_record(
        request_id=request_id,
        primary_model=settings.primary_model,
        worker_model=settings.fallback_model,
        signal=signal,
        mode="switch",
        principal=principal,
        audit_log=audit_log,
    )
    snap = mgr.snapshot()
    return {
        "ok": True,
        "switched": req.target,
        "slot": req.target,
        "provider_id": binding.provider_id,
        "model": binding.model,
        "url": binding.url,
        "verified": verified["ok"],
        "verify_detail": verified["detail"],
        "rollback_available": True,
        **snap,
    }


# --------------------------------------------------------------------------
# Module-level manager, bound to a given SETTINGS object. The gateway passes
# its live SETTINGS; tests construct their own and get their own manager
# (keyed by id()), so no global-mutation dance is needed.
# --------------------------------------------------------------------------
_managers = {}
_managers_lock = threading.Lock()


def _manager_for(settings):
    with _managers_lock:
        mgr = _managers.get(id(settings))
        if mgr is None:
            mgr = SlotManager(settings)
            _managers[id(settings)] = mgr
        return mgr


def manager() -> SlotManager:
    """The manager bound to proxy_gateway.SETTINGS (created on first use)."""
    import proxy_gateway

    return _manager_for(proxy_gateway.SETTINGS)
