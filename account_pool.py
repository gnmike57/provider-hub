"""Multi-account credential pool - Weighted-Least-In-Flight + token buckets.

Adapted from the operator's reference design (Hive/Abliteration multi-account
cascade, 2026-10-21) into THIS repo's architecture. Deliberate differences:

  * The gateway's ladder/constellation stays the ROUTING brain; this module is
    a CREDENTIAL layer: one `routed_headers()` call at egress picks the account
    that serves each attempt. No parallel cascade, no second refusal detector -
    the existing presignal/commitment machinery screens refusals far more
    precisely than a 300-char phrase list.
  * Synchronous and lock-light (threading.RLock): the egress hook runs inside
    httpx header construction on the event loop, so an asyncio.Lock (as the
    reference uses) is the wrong primitive here.
  * Depletion signals are measured, not guessed: Hive answers 405 "Out of
    Balance" on an empty org balance and 429 on the rate limit (tools/hive/
    README.md); Abliteration answers 402 "Billing account is not in good
    standing" (T3.2 live evidence). All three mark the account; 429 applies a
    short cooldown instead of a permanent depletion.
  * Sticky preference hashes the routing context (model + principal) instead of
    a subagent id: same intent -> same account -> upstream prompt-cache hits.
    A dead/depleted/cooldown sticky account falls through to WLIF.
  * FAIL-CLOSED to the configured key, never open: an empty pool, a corrupt
    file, or any internal error returns the caller's headers untouched (design
    rule 7 - hooks never raise into the request path).

Accounts load per (mtime, size) from a JSON file (default account_pool.json
beside this module, gitignored - full key values) with env overrides:

    ACCOUNT_POOL_FILE        file path override (tests)
    ACCOUNT_POOL_KEYS        live override: comma-separated "provider:key"
                             pairs ("hive:...", "ablit:...")
    ACCOUNT_POOL_ENABLED     0 disables the pool entirely (passthrough)
    ACCOUNT_POOL_HIVE_RPS / _ABLIT_RPS / _DEFAULT_RPS  per-provider bucket rate
    ACCOUNT_POOL_COOLDOWN_S  429 cooldown seconds (default 5.0)
    ACCOUNT_POOL_METRICS     0 freezes the additive rotation metrics
                             (metrics_snapshot(); default ON)
    HUB_IPC_LOCKS            0 disables cross-process file locking globally
                             (hub_ipc kill switch; default on, best-effort)

Storage shape: {"accounts": [{"provider": "hive"|"ablit",
                              "key": "<secret>", "label": "..."}]}

Hive auth note (tools/hive/README.md, verified live 2026-10-07): the SECRET key
is the credential (`Authorization: Bearer <secret>`); the ACCESS key is an
identifier that answers 401 if sent as the Bearer value. Only secret keys are
stored here.

CLI: python account_pool.py status
"""

import hashlib
import json
import os
import threading
import time
from typing import Dict, List, Optional

try:
    import hub_ipc  # cross-process read lock for account_pool.json (W2)
except ImportError:  # hub_ipc lives beside this module; never block import
    hub_ipc = None

__all__ = [
    "AccountKey", "AccountPool", "POOL", "routed_headers", "pool_summary",
    "reload_pool", "observe_result", "mark_depleted",
    "metrics_snapshot", "reset_metrics",
]

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POOL_PATH = os.path.join(ROOT, "account_pool.json")

# Depletion / throttle status classes (measured, see module docstring).
COOLDOWN_STATUSES = frozenset({429})
DEPLETED_STATUSES = frozenset({401, 402, 405})


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _sniff_provider(url: str) -> str:
    """URL -> provider key. Mirrors the gateway's egress topology."""
    u = (url or "").lower()
    if "thehive.ai" in u:
        return "hive"
    if "abliteration.ai" in u:
        return "ablit"
    return ""


def _redact(value: Optional[str]) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= 12:
        return value[:3] + "..."
    return value[:5] + "..." + value[-4:]


# --------------------------------------------------------------------------
# Additive rotation/health metrics (W2).  NEW counter names only - nothing
# pre-existing is renamed or re-keyed, so existing metric consumers see a
# pure superset.  Counters are process-local, best-effort, and never raise;
# ACCOUNT_POOL_METRICS=0 freezes them (default ON) - the summary keys simply
# keep their last values / stay zero.
# --------------------------------------------------------------------------
_METRICS_LOCK = threading.Lock()
_METRICS = {
    "pick_attempts": 0,          # every _pick() invocation
    "pick_sticky_hit": 0,        # sticky-hash preference acquired the token
    "pick_wlif_fallback": 0,     # sticky preferred but token-less -> WLIF won
    "pick_no_token": 0,          # sticky failed AND no WLIF candidate got a token
    "pick_empty_pool": 0,        # no available account for the provider
    "sticky_divert": 0,          # sticky preferred was unavailable -> diverted
    "acquire_none": 0,           # acquire() returned None (caller keeps own key)
    "reload_file": 0,            # file-sourced reloads
    "reload_env": 0,             # env-sourced reloads
    "reload_locked": 0,          # reloads that ran under the hub_ipc file lock
    "reload_lock_skipped": 0,    # reloads that ran unlocked (kill switch / no hub_ipc / timeout)
    "depleted_events": 0,        # 401/402/405 outcomes
    "cooldown_events": 0,        # 429 outcomes
}


def _bump(name: str, n: int = 1) -> None:
    """Best-effort metrics increment - never raises, lock is held briefly."""
    if os.getenv("ACCOUNT_POOL_METRICS", "1") == "0":
        return
    try:
        with _METRICS_LOCK:
            _METRICS[name] = int(_METRICS.get(name, 0)) + n
    except Exception:  # noqa: BLE001 - rule 7: metrics never break egress
        pass


def metrics_snapshot() -> Dict[str, int]:
    """Return a copy of the additive counters (new names only)."""
    with _METRICS_LOCK:
        return dict(_METRICS)


def reset_metrics() -> None:
    """Zero every counter (tests / ops snapshots)."""
    with _METRICS_LOCK:
        for k in _METRICS:
            _METRICS[k] = 0


def _file_read_lock(path: str):
    """Context manager: shared cross-process read lock over the pool file.

    Best-effort on purpose: hub_ipc missing, HUB_IPC_LOCKS=0, or a lock
    timeout all degrade to the historical unlocked read (default behaviour
    preserved).  Only full scans on mtime change pay the lock.
    """
    if hub_ipc is None:
        return _noop_lock()
    if os.getenv("HUB_IPC_LOCKS", "1") == "0":
        return _noop_lock()
    try:
        return hub_ipc.locked_path(path)
    except Exception:  # noqa: BLE001 - rule 7
        return _noop_lock()


def _noop_lock():
    from contextlib import nullcontext
    return nullcontext()


class AccountKey:
    """One provider account: token bucket + in-flight gauge + health state."""

    __slots__ = ("provider", "key", "label", "max_rps", "tokens", "in_flight",
                 "last_refill", "cooldown_until", "depleted")

    def __init__(self, provider: str, key: str, label: str = "",
                 max_rps: float = 4.5):
        self.provider = provider
        self.key = key
        self.label = label or f"{provider}-{id(self):x}"
        self.max_rps = max(0.1, float(max_rps))
        self.tokens = self.max_rps
        self.in_flight = 0
        self.last_refill = time.monotonic()
        self.cooldown_until = 0.0
        self.depleted = False

    def try_acquire(self) -> bool:
        """Refill the bucket, then spend one token if available."""
        now = time.monotonic()
        if self.depleted or now < self.cooldown_until:
            return False
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.max_rps, self.tokens + elapsed * self.max_rps)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def available(self) -> bool:
        return (not self.depleted
                and time.monotonic() >= self.cooldown_until)

    def note_result(self, status: Optional[int]) -> Optional[str]:
        """Feed an upstream outcome back; returns the outcome class so callers
        can meter it ("depleted" | "cooldown" | None)."""
        if status is None:
            return None
        if status in DEPLETED_STATUSES:
            # 401/402/405: THIS credential is dead (revoked / org out of
            # balance) - stop offering it until the pool file/env changes.
            self.depleted = True
            _bump("depleted_events")
            return "depleted"
        if status in COOLDOWN_STATUSES:
            self.cooldown_until = time.monotonic() + _env_float(
                "ACCOUNT_POOL_COOLDOWN_S", 5.0)
            _bump("cooldown_events")
            return "cooldown"
        return None

    def summary(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "label": self.label,
            "redacted": _redact(self.key),
            "in_flight": self.in_flight,
            "depleted": self.depleted,
            "cooling_down": time.monotonic() < self.cooldown_until,
        }

# --------------------------------------------------------------------------
# AccountPool: per-provider pools, lazy reload, WLIF + sticky selection.
# --------------------------------------------------------------------------
class AccountPool:
    """Per-provider account pools with WLIF + sticky selection.

    Locking: a plain threading.RLock guards the (tiny) critical sections -
    selection happens during header construction on the event loop thread and
    must not await. Every public method is exception-hardened (design rule 7).
    """

    def __init__(self, path: str = None):
        self._explicit_path = path is not None
        self._path = path or os.getenv("ACCOUNT_POOL_FILE") or DEFAULT_POOL_PATH
        self._lock = threading.RLock()
        self._spec = None
        self._pools: Dict[str, List[AccountKey]] = {}
        self._reload()

    # -- Loading (lazy, mtime+size keyed, degrade-to-empty) ---------------
    def _read_file(self) -> List[dict]:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
        rows = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            rows = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            provider = str(r.get("provider", "")).strip().lower()
            key = str(r.get("key", "")).strip()
            if not provider or not key:
                continue
            out.append({"provider": provider, "key": key,
                        "label": str(r.get("label", "") or ""),
                        "max_rps": r.get("max_rps")})
        return out

    @staticmethod
    def _parse_env_pairs(raw: str) -> List[dict]:
        out = []
        for i, pair in enumerate(raw.split(","), 1):
            pair = pair.strip()
            if not pair:
                continue
            provider, sep, key = pair.partition(":")
            provider = provider.strip().lower()
            key = key.strip()
            if not sep or not key:
                # Bare key: sniff the prefix so operators can paste ak_/cat_
                # keys without the provider: prefix.
                key = pair
                if key.startswith("ak_"):
                    provider = "ablit"
                elif key.startswith("cat_") or key.startswith("sk-nano"):
                    provider = "nano"
                elif key.endswith("=="):
                    provider = "hive"
                else:
                    continue
            if provider in ("abliteration", "ablit.ai"):
                provider = "ablit"
            out.append({"provider": provider, "key": key,
                        "label": f"env-{provider}-{i}", "max_rps": None})
        return out

    def _default_rps(self, provider: str) -> float:
        if provider == "hive":
            return _env_float("ACCOUNT_POOL_HIVE_RPS", 4.5)
        if provider == "ablit":
            return _env_float("ACCOUNT_POOL_ABLIT_RPS", 10.0)
        return _env_float("ACCOUNT_POOL_DEFAULT_RPS", 10.0)

    def _reload(self) -> None:
        # Re-resolve the path from env on EVERY reload (unless an explicit
        # path was injected), so ACCOUNT_POOL_FILE overrides work live - the
        # same env-at-read-time behaviour the abliteration pool has.
        if not self._explicit_path:
            self._path = os.getenv("ACCOUNT_POOL_FILE") or DEFAULT_POOL_PATH
        if os.getenv("ACCOUNT_POOL_ENABLED", "1") != "1":
            with self._lock:
                self._pools = {}
                self._spec = ("disabled",)
            return
        env = os.getenv("ACCOUNT_POOL_KEYS", "")
        if env.strip():
            rows = self._parse_env_pairs(env)
            spec = ("env", env)
            _bump("reload_env")
        else:
            try:
                st = os.stat(self._path)
                spec = ("file", st.st_mtime_ns, st.st_size)
            except OSError:
                spec = ("file", None)
            # Cross-process read lock: stop the torn half-of-a-rewrite read
            # when another process is mid-replace on the pool file.  Best
            # effort - the unlocked path is the default-preserved fallback.
            with _file_read_lock(self._path):
                if hub_ipc is not None and os.getenv("HUB_IPC_LOCKS", "1") != "0":
                    _bump("reload_locked")
                else:
                    _bump("reload_lock_skipped")
                rows = self._read_file()
            _bump("reload_file")
        pools: Dict[str, List[AccountKey]] = {}
        for r in rows:
            provider = r["provider"]
            if provider not in ("hive", "ablit", "nano"):
                continue
            try:
                max_rps = (float(r["max_rps"])
                           if r.get("max_rps") not in (None, "")
                           else self._default_rps(provider))
            except (TypeError, ValueError):
                max_rps = self._default_rps(provider)
            pools.setdefault(provider, []).append(
                AccountKey(provider, r["key"], r.get("label") or "", max_rps))
        with self._lock:
            self._spec = spec
            self._pools = pools

    def _maybe_reload(self) -> None:
        with self._lock:
            if os.getenv("ACCOUNT_POOL_ENABLED", "1") != "1":
                self._pools = {}
                self._spec = ("disabled",)
                return
            env = os.getenv("ACCOUNT_POOL_KEYS", "")
            if env.strip():
                if self._spec != ("env", env):
                    self._reload()
                return
            try:
                st = os.stat(self._path)
                spec = ("file", st.st_mtime_ns, st.st_size)
            except OSError:
                spec = ("file", None)
            if self._spec != spec:
                self._reload()
    # -- Selection: sticky-hash preference -> WLIF among token-ready ------
    def _pick(self, provider: str, route_key: str) -> Optional[AccountKey]:
        _bump("pick_attempts")
        pool = [a for a in (self._pools.get(provider) or []) if a.available()]
        if not pool:
            _bump("pick_empty_pool")
            return None
        # 1. Sticky preference: the same route lands on the same account so
        #    the provider's prompt cache stays warm (the reference design's
        #    subagent-hash idea, keyed on routing context instead).
        idx = int.from_bytes(
            hashlib.sha256(route_key.encode("utf-8", "replace")).digest()[:4],
            "big") % len(pool)
        preferred = pool[idx]
        if preferred.try_acquire():
            _bump("pick_sticky_hit")
            return preferred
        _bump("sticky_divert")
        # 2. Weighted least-in-flight among token-ready accounts.
        ready = [a for a in pool if a.try_acquire()]
        if ready:
            _bump("pick_wlif_fallback")
            return min(ready, key=lambda a: a.in_flight)
        _bump("pick_no_token")
        return None

    def acquire(self, url: str, route_key: str = "",
                provider_hint: str = "") -> Optional[AccountKey]:
        """Pick an account for one egress attempt. None -> keep the caller's
        configured credential (pool empty / provider unknown / all dead)."""
        try:
            self._maybe_reload()
            provider = ((provider_hint or "").strip().lower()
                        or _sniff_provider(url))
            if not provider:
                return None
            with self._lock:
                acct = self._pick(provider, route_key or url)
                if acct is not None:
                    acct.in_flight += 1
                else:
                    _bump("acquire_none")
                return acct
        except Exception:  # noqa: BLE001 - rule 7: never raise into egress
            return None

    @staticmethod
    def release(acct: Optional[AccountKey]) -> None:
        if acct is None:
            return
        try:
            acct.in_flight = max(0, acct.in_flight - 1)
        except Exception:
            pass

    @staticmethod
    def result(acct: Optional[AccountKey], status: Optional[int]) -> Optional[str]:
        if acct is None:
            return None
        try:
            return acct.note_result(status)
        except Exception:
            return None

    def summary(self) -> Dict[str, object]:
        try:
            self._maybe_reload()
            with self._lock:
                accounts = [a.summary()
                            for pool in self._pools.values() for a in pool]
                return {
                    "enabled": os.getenv("ACCOUNT_POOL_ENABLED", "1") == "1",
                    "size": len(accounts),
                    "accounts": accounts,
                }
        except Exception:  # noqa: BLE001
            return {"enabled": False, "size": 0, "accounts": []}


# Module-level singleton (mirrors abliteration_keys' pool pattern).
POOL = AccountPool()


def reload_pool() -> None:
    """Forget cached state; the next egress call re-reads env/file."""
    with POOL._lock:
        POOL._spec = None
        POOL._reload()


def routed_headers(headers: Optional[Dict[str, str]], url: str,
                   route_key: str = "", provider_hint: str = ""):
    """Egress hook: pick an account and return (headers, account).

    Returns the INPUT dict unchanged (same object, not a copy) when the pool
    cannot serve - exactly like abliteration_keys.pooled_headers - so callers
    keep their configured credential and can release(None) safely.
    """
    try:
        if os.getenv("ACCOUNT_POOL_ENABLED", "1") != "1":
            return headers or {}, None
        acct = POOL.acquire(url, route_key, provider_hint)
        if acct is None:
            return headers or {}, None
        out = dict(headers or {})
        out["Authorization"] = f"Bearer {acct.key}"
        return out, acct
    except Exception:  # noqa: BLE001 - rule 7
        return headers or {}, None


def observe_result(acct, status: Optional[int]) -> Optional[str]:
    """Record one upstream outcome (health feedback + release) - one call at
    every finally, so in-flight counts can never wedge. Returns the outcome
    class ("depleted" | "cooldown" | None) for caller-side metering."""
    outcome = POOL.result(acct, status)
    POOL.release(acct)
    return outcome


def mark_depleted(acct) -> None:
    POOL.result(acct, 402)


def pool_summary() -> Dict[str, object]:
    return POOL.summary()


if __name__ == "__main__":
    print(json.dumps(pool_summary(), indent=2))

