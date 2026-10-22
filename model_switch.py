"""Runtime model switching - `/v1/switch` (operator alias: `/switch`).

Lets the operator hot-swap which configured model sits in the PRIMARY slot and
which sits in the SPECIALIST (worker) slot, while the gateway keeps serving.

    POST /v1/switch {"target": "primary", "provider": "hive", "model": "deepfrost"}
    POST /v1/switch {"target": "worker",  "model": "ablit-v2-large"}
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
     (NO_GO_ENABLED=0).
  4. Every switch, failed verify and rollback lands in the audit trail
     (ingress_assembler.audit_record, signals switch_*), so the jsonl log
     answers "which binding served which window" afterwards.

Targets resolve through the provider registry (gateway_registry.json):
  - {"provider": "hive", "model": "deepfrost"}  explicit provider + exposed name
  - {"model": "ablit-v2-large"}                 unique-provider model lookup
  - {"model": "deepfrost"}                      hub alias -> slot + upstream id
  - {"url": ..., "key": ..., "model": ...}      raw out-of-registry override

Design rules honoured here (proxy_gateway header):
  6. Guards run once, shared by the endpoints (authz is enforced by the caller).
  7. Hooks never raise into the request path - everything returns a structured
     result; the endpoint decides the status code.
  8. Raw out-of-registry overrides stay ON by default; MODEL_SWITCH_ALLOW_RAW=0
     is the operator kill switch for them (unset or =1 keeps the open behavior).

Run: imported by proxy_gateway (no fastapi/httpx import of its own; the caller
passes the shared httpx client in).
"""

import asyncio
import os
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
    "ALLOW_RAW_ENV",
    "raw_override_allowed",
]

# --------------------------------------------------------------------------
# MODEL_SWITCH_ALLOW_RAW - whether {"url": ..., "key": ...} raw out-of-registry
# overrides are accepted by /v1/switch.
#
#   unset  -> ALLOWED (historical behavior; raw override is a core feature and
#             stays fully functional unless an operator opts out)
#   "1"    -> ALLOWED (explicit opt-in, same as unset)
#   "0"    -> REJECTED with SwitchError(403) naming this knob
#
# Read at CALL time (not import time) so a deployment can flip it with a
# restart-only env change and tests can monkeypatch os.environ per case.
# --------------------------------------------------------------------------
ALLOW_RAW_ENV = "MODEL_SWITCH_ALLOW_RAW"


def raw_override_allowed() -> bool:
    """True unless MODEL_SWITCH_ALLOW_RAW is explicitly set to 0.

    Fail-open by design: only the literal "0" disables raw overrides. Every
    other value (including unset, "", "1", "true", "yes") keeps the historical
    allowing behavior, so an unrecognised value can never silently lock out a
    working operator workflow.
    """
    return os.environ.get(ALLOW_RAW_ENV, "").strip() != "0"

# Creative slot names (constellation layer) map onto the canonical targets:
# "helm" -> primary, "specialist" -> worker, "secondary" -> scout. Both
# vocabularies are accepted by /v1/switch, so old scripts keep working.
_SLOT_ALIASES = {
    "primary": "primary",
    "helm": "primary",
    "worker": "worker",
    "specialist": "worker",
    "scout": "scout",
    "secondary": "scout",
}
SWITCH_TARGETS = ("primary", "worker", "swap", "status", "scout",
                 "helm", "specialist", "secondary")


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
    # Time-travel rollback (constellation layer): an ISO timestamp or unix
    # epoch; restores the slot binding snapshot recorded at/before it.
    rollback_to: str = ""


def parse_switch_request(body) -> SwitchRequest:
    """Validate a /v1/switch body. Raises SwitchError(400) on garbage."""
    body = body or {}
    if not isinstance(body, dict):
        raise SwitchError("request body must be a JSON object")
    target = str(body.get("target") or "status").strip().lower()
    target = _SLOT_ALIASES.get(target, target)
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
        rollback_to=str(body.get("rollback_to") or "").strip(),
    )
    if req.target in ("primary", "worker", "scout") and not req.rollback and not req.rollback_to:
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
        # Scout (constellation layer): the probe/pre-screen slot. Defaults
        # to the helm binding, so a deployment that never touches it behaves
        # exactly as before (getattr everywhere: tests pass namespaces).
        self.scout = SlotBinding(
            model=getattr(settings, "scout_model", "") or getattr(settings, "primary_model", ""),
            url=getattr(settings, "scout_api_url", "") or getattr(settings, "primary_api_url", ""),
            key_present=bool(
                getattr(settings, "scout_api_key", "") or getattr(settings, "primary_api_key", "")
            ),
        )
        self._savepoint = None
        self.events = []
        # asyncio critical section for savepoint -> verify -> apply (see
        # switch_lock(); created lazily because __init__ may run outside a loop).
        self._async_lock: Optional[asyncio.Lock] = None
        self._async_loop = None

    # ---- reads -----------------------------------------------------------
    def settings(self):
        """The live settings. The gateway reads slot fields per request."""
        return self._settings

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "primary": self.primary.as_dict(),
                "worker": self.worker.as_dict(),
                "scout": self.scout.as_dict(),
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
        """Append one audit event to the ring buffer, under the slot lock.

        The buffer used to be mutated with no locking while snapshot() read it
        under self._lock, so a concurrent append could land between the
        `events[-8:]` slice and the dict build and corrupt/reorder the
        last_events view. The mutation now happens inside the same lock every
        other slot write uses.
        """
        with self._lock:
            self._record_locked(request_id, principal, target, action, detail)

    def _record_locked(self, request_id, principal, target, action, detail=""):
        """Append WITHOUT taking the lock - caller already holds self._lock.

        Split out because rollback() calls record() while holding self._lock;
        threading.Lock is not reentrant, so the public record() guard would
        deadlock on that path. Internal locked sections must use this.
        """
        self.events.append(
            SwitchEvent(time.time(), request_id, principal, target, action, detail)
        )
        del self.events[:-8]

    # ---- writes ----------------------------------------------------------
    def _binding_for(self, target: str) -> SlotBinding:
        if target == "primary":
            return self.primary
        if target == "scout":
            return self.scout
        return self.worker

    def switch_lock(self) -> asyncio.Lock:
        """The asyncio.Lock that serialises savepoint -> verify -> apply.

        Without it two concurrent switches interleave: A arms its savepoint and
        awaits the verify probe; B arms + applies over it; A then applies on
        top - the slots and the rollback savepoint end up describing a state
        that never existed. perform_switch/apply_constellation hold this lock
        across their whole mutating section.

        Created lazily and re-created when the RUNNING event loop changes:
        tests drive perform_switch through a fresh asyncio.run/TestClient loop
        each time, and a lock left bound to a closed loop would raise
        "bound to a different event loop". Per-manager, so tests that build
        their own settings namespace get their own critical section.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # called from sync context: best-effort lock
            loop = None
        if self._async_lock is None or (
            self._async_loop is not None and loop is not self._async_loop
        ):
            self._async_lock = asyncio.Lock()
        self._async_loop = loop
        return self._async_lock

    def existing_key(self, target: str) -> str:
        """The slot's CURRENT key - used when a raw switch omits 'key' (None).

        key=None on a switch means "keep whatever the slot holds now"; this is
        the read side of that contract. scout inherits helm's key when unset.
        """
        with self._lock:
            s = self._settings
            if target == "primary":
                return getattr(s, "primary_api_key", "") or ""
            if target == "scout":
                return (
                    getattr(s, "scout_api_key", "")
                    or getattr(s, "primary_api_key", "")
                    or ""
                )
            return getattr(s, "fallback_api_key", "") or ""

    def _capture_savepoint(self) -> None:
        """Snapshot all slots from the live settings (caller holds the lock)."""
        s = self._settings
        self._savepoint = {
            "primary": (s.primary_api_url, s.primary_api_key, s.primary_model),
            "worker": (s.fallback_api_url, s.fallback_api_key, s.fallback_model),
            "scout": (
                getattr(s, "scout_api_url", "") or s.primary_api_url,
                getattr(s, "scout_api_key", "") or s.primary_api_key,
                getattr(s, "scout_model", "") or s.primary_model,
            ),
        }

    def apply(self, *, target, url, key, model, provider_id="",
              request_id="", principal="") -> SlotBinding:
        """Atomically write one slot (primary/worker/scout) on the live settings.

        Validation (W5): a blank 'url' or 'model' is REJECTED instead of
        silently blanking the slot - history entries and rollback inputs used to
        be able to clear a slot's binding through here (url=""/model="").
        'key' keeps its three-state contract: None = keep the slot's current
        key, "" = explicitly clear it, anything else = the new key.

        The FIRST mutation of a session captures the pre-mutation state as the
        rollback savepoint (an explicit savepoint() may have been called even
        earlier; whichever comes first wins).
        """
        url = str(url or "").strip()
        model = str(model or "").strip()
        if not url or not model:
            raise SwitchError(
                f"cannot bind slot {target!r}: 'url' and 'model' must be "
                f"non-empty (got url={url!r}, model={model!r})"
            )
        with self._lock:
            if self._savepoint is None:
                self._capture_savepoint()
            s = self._settings
            if target == "primary":
                if key is None:  # keep the existing key
                    key = s.primary_api_key
                s.primary_api_url = url
                s.primary_api_key = key
                s.primary_model = model
            elif target == "scout":
                if key is None:  # keep the existing key (scout falls back to helm's)
                    key = getattr(s, "scout_api_key", "") or s.primary_api_key
                s.scout_api_url = url
                s.scout_api_key = key
                s.scout_model = model
            else:
                if key is None:  # keep the existing key
                    key = s.fallback_api_key
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

    def savepoint(self, force: bool = False) -> None:
        """Arm the rollback savepoint for the switch that is about to run.

        Sticky by default: only the FIRST capture wins, so a savepoint taken
        AFTER a mutation can no longer bake that mutation into the rollback
        target (the historical bug this guarded against). Mutating switches
        pass force=True to RE-ARM it: every switch must be undoable to the
        state right before IT, not to the state before the first-ever switch
        (which is what a never-re-armed savepoint meant rollback:true did,
        while still advertising rollback_available).
        """
        with self._lock:
            if force or self._savepoint is None:
                self._capture_savepoint()

    def has_savepoint(self) -> bool:
        with self._lock:
            return self._savepoint is not None

    def rollback(self, *, request_id: str = "", principal: str = "") -> bool:
        """Restore the pre-switch bindings. True when a savepoint existed.

        The savepoint is CONSUMED (cleared) on rollback: one level of undo,
        re-armed by the next mutating switch. It used to stay armed forever, so
        rollback:true advertised by every switch response always reverted to the
        pre-FIRST-switch state no matter how many switches had happened since.
        """
        with self._lock:
            sp = self._savepoint
            if not sp:
                return False
            s = self._settings
            s.primary_api_url, s.primary_api_key, s.primary_model = sp["primary"]
            s.fallback_api_url, s.fallback_api_key, s.fallback_model = sp["worker"]
            for target, binding in (
                ("primary", self.primary),
                ("worker", self.worker),
                ("scout", self.scout),
            ):
                url, key, model = sp[target]
                if target == "scout":
                    s.scout_api_url = url
                    s.scout_api_key = key
                    s.scout_model = model
                binding.model = model
                binding.url = url
                binding.key_present = bool(key)
                binding.provider_id = ""
                binding.updated_ts = time.time()
                binding.updated_by = request_id
            self._savepoint = None  # consumed; the next switch re-arms it
            self._record_locked(request_id, principal, "all", "rolled_back")
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
      4. Hub alias            - resolve_frost_alias: slot + upstream id; the
                                URL/key stay the CURRENT binding of the slot
                                the name points at (pure slot-swap semantics)
    Raises SwitchError with a 4xx status when nothing resolves.
    """
    if req.url and req.model:  # (1) raw override
        if not raw_override_allowed():
            raise SwitchError(
                f"raw url/key overrides are disabled: set {ALLOW_RAW_ENV}=1 to "
                "allow out-of-registry switch targets",
                status_code=403,
            )
        return {
            "url": req.url.rstrip("/"),
            # key stays three-state: None = keep the slot's current key (the
            # SwitchRequest contract), "" = explicitly clear it. It used to be
            # flattened to "" here, silently clearing the key of any raw
            # switch that omitted one.
            "key": req.key,
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
# Constellation layer: timestamp parsing + binding-history recording.
# Lazy imports keep model_switch <-> constellation acyclic.
# --------------------------------------------------------------------------
def _parse_ts(value: str):
    """'2026-10-19T14:30:00' | '1760874600' | '1760874600.5' -> unix epoch.

    Raises SwitchError(400) on anything unparseable.
    """
    raw = str(value or "").strip()
    if not raw:
        raise SwitchError("'rollback_to' needs a timestamp (ISO 8601 or unix epoch)")
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        from datetime import datetime

        # Accept both aware and naive ISO strings; naive is read as UTC.
        text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, ImportError):
        raise SwitchError(f"could not parse timestamp {value!r} for 'rollback_to'")


def _slots_for_history(mgr, settings) -> dict:
    """Full 3-slot snapshot (url/key/model/provider_id) for the history file."""
    return {
        "helm": {
            "url": settings.primary_api_url,
            "key": settings.primary_api_key,
            "model": settings.primary_model,
            "provider_id": mgr.primary.provider_id,
        },
        "specialist": {
            "url": settings.fallback_api_url,
            "key": settings.fallback_api_key,
            "model": settings.fallback_model,
            "provider_id": mgr.worker.provider_id,
        },
        "scout": {
            "url": getattr(settings, "scout_api_url", "") or settings.primary_api_url,
            "key": getattr(settings, "scout_api_key", "") or settings.primary_api_key,
            "model": getattr(settings, "scout_model", "") or settings.primary_model,
            "provider_id": mgr.scout.provider_id,
        },
    }


def _record_history(mgr, settings, request_id, principal, action) -> None:
    """Persist the current bindings; NEVER raises (design rule 7)."""
    try:
        import constellation

        constellation.BINDING_HISTORY.record(
            _slots_for_history(mgr, settings), request_id, principal, action
        )
    except Exception:  # noqa: BLE001 - history is advisory, not load-bearing
        pass


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

    # One async critical section across savepoint -> verify -> apply (W5):
    # concurrent switches could otherwise interleave around the await on the
    # verify probe, each arming/overwriting the shared rollback savepoint.
    async with mgr.switch_lock():

        # Time-travel rollback (constellation layer): restore the full binding
        # snapshot recorded at/before the given timestamp. Runs BEFORE the
        # plain savepoint rollback so it can also serve as one.
        if req.rollback_to:
            import constellation

            ts = _parse_ts(req.rollback_to)
            entry = constellation.BINDING_HISTORY.entry_at(ts)
            if entry is None:
                raise SwitchError(
                    f"no binding history at or before {req.rollback_to!r}; "
                    "the earliest retained entry is newer (or the file is empty)",
                    status_code=404,
                )
            mgr.savepoint(force=True)
            for slot, b in (entry.get("slots") or {}).items():
                canonical = _SLOT_ALIASES.get(slot, slot)
                if canonical not in ("primary", "worker", "scout"):
                    continue
                # Skip slots the old entry never bound: apply() now rejects
                # blank url/model instead of blanking a live slot.
                url = str((b or {}).get("url") or "").strip()
                model = str((b or {}).get("model") or "").strip()
                if not url or not model:
                    continue
                mgr.apply(
                    target=canonical,
                    url=url,
                    key=str((b or {}).get("key") or ""),
                    model=model,
                    provider_id=str((b or {}).get("provider_id") or ""),
                    request_id=request_id,
                    principal=principal,
                )
            mgr.record(request_id, principal, "all", "rolled_back",
                       f"restored entry at {entry.get('ts')}")
            _record_history(mgr, settings, request_id, principal, "time-travel")
            audit_record(
                request_id=request_id,
                primary_model=settings.primary_model,
                worker_model=settings.fallback_model,
                signal="switch_time_travel",
                mode="switch",
                principal=principal,
                audit_log=audit_log,
            )
            snap = mgr.snapshot()
            return {
                "ok": True,
                "switched": "rollback_to",
                "restored_from_ts": entry.get("ts"),
                **snap,
            }

        if req.rollback:
            if not mgr.has_savepoint():
                raise SwitchError(
                    "nothing to roll back: the savepoint was consumed by an "
                    "earlier rollback, or no switch has been applied yet"
                )
            mgr.rollback(request_id=request_id, principal=principal)
            _record_history(mgr, settings, request_id, principal, "rollback")
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

        # savepoint FIRST, re-armed for THIS switch: rollback:true undoes the
        # most recent switch, not every switch since the beginning of time.
        mgr.savepoint(force=True)

        if req.target == "swap":
            mgr.swap(request_id=request_id, principal=principal)
            _record_history(mgr, settings, request_id, principal, "swap")
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
        if req.target == "scout":
            default_url = getattr(settings, "scout_api_url", "") or settings.primary_api_url
        else:
            default_url = (
                settings.primary_api_url if req.target == "primary" else settings.fallback_api_url
            )
        target_url = resolved["url"] or default_url
        # Three-state key (W5): None = keep the slot's CURRENT key (a raw
        # switch that omits 'key'), "" = clear it, "none" = the registry
        # placeholder for "no key". resolve_target used to flatten None to
        # "", silently clearing the key of a slot switched with url+model only.
        target_key = resolved["key"]
        if target_key is None:
            target_key = mgr.existing_key(req.target)
        elif target_key == "none":
            target_key = ""

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
        _record_history(mgr, settings, request_id, principal, "switch")
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
            "rollback_available": mgr.has_savepoint(),
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


# --------------------------------------------------------------------------
# Constellation application: a named 3-slot preset, applied atomically.
# --------------------------------------------------------------------------
async def apply_constellation(preset, *, settings, http, registry=None,
                              request_id="", principal="", audit_log="") -> dict:
    """Apply a constellation preset: all three slots at once.

    Resolution happens for ALL slots BEFORE any mutation (a preset naming a
    model the registry does not know is a 404, not a half-applied
    constellation). The helm slot gets the usual upstream verification
    (advisory - it never blocks the apply, matching single-slot switches).

    Returns the response payload dict; raises SwitchError on bad presets.
    """
    from ingress_assembler import audit_record

    mgr = _manager_for(settings)
    slots = (preset or {}).get("slots") or {}
    if not isinstance(slots, dict) or not slots:
        raise SwitchError("constellation preset has no 'slots'")

    # 1. resolve everything first (fail before mutating anything)
    resolved = {}
    for display, spec in slots.items():
        canonical = _SLOT_ALIASES.get(str(display or "").strip().lower())
        if canonical is None:
            raise SwitchError(
                f"preset slot {display!r} is not one of helm/specialist/scout"
            )
        model = str((spec or {}).get("model") or "").strip()
        provider = str((spec or {}).get("provider") or "").strip()
        if not model:
            raise SwitchError(f"preset slot {display!r} has no 'model'")
        sub = SwitchRequest(target=canonical, provider=provider, model=model)
        resolved[canonical] = resolve_target(sub, settings, registry)

    # 2-4 run under the same async critical section as single-slot switches
    # (savepoint -> verify -> apply must not interleave with a concurrent
    # /v1/switch), and the savepoint is RE-ARMED for THIS apply so
    # rollback:true undoes it - not some earlier switch.
    async with mgr.switch_lock():
        mgr.savepoint(force=True)

        # 3. verify the helm binding (advisory, same as a single-slot switch)
        helm_resolved = resolved.get("primary")
        verified = {"ok": True, "detail": "verification skipped"}
        if helm_resolved and http is not None:
            verified = await verify_target(http, helm_resolved["url"], helm_resolved["key"])

        # 4. apply all slots
        bindings = {}
        for canonical, r in resolved.items():
            key = r["key"]
            if key == "none":
                key = ""
            elif key is None:  # keep the slot's current key
                key = mgr.existing_key(canonical)
            bindings[canonical] = mgr.apply(
                target=canonical,
                url=r["url"],
                key=key,
                model=r["model"],
                provider_id=r["provider_id"],
                request_id=request_id,
                principal=principal,
            )
        mgr.record(
            request_id, principal, "constellation",
            "verified" if verified["ok"] else "verify_failed", verified["detail"],
        )
        _record_history(mgr, settings, request_id, principal, "constellation")
        audit_record(
            request_id=request_id,
            primary_model=settings.primary_model,
            worker_model=settings.fallback_model,
            signal="switch_constellation",
            mode="switch",
            principal=principal,
            audit_log=audit_log,
        )
        snap = mgr.snapshot()
        return {
            "ok": True,
            "switched": "constellation",
            "slots": {name: b.model for name, b in bindings.items()},
            "verified": verified["ok"],
            "verify_detail": verified["detail"],
            "rollback_available": mgr.has_savepoint(),
            **snap,
        }
