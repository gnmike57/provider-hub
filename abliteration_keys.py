"""Abliteration key factory + round-robin throughput pool (2026-10-21).

Operator directive: the single admin key (ABLITERATION_ADMIN_KEY, sk_...) is
the ONLY admin key; every consumer that needs an inference key gets one minted
through the Administration API ("a new api key for everything that requests
one"), and because Abliteration caps throughput per API key, egress alternates
between a POOL of project keys (default 2) for maximum throughput.

Components:

    KeyFactory      mint/list/revoke project API keys via the Admin API
                    (POST/GET/DELETE /v1/organization/projects/{pid}/api_keys)
    ensure_pool()   keep N named pool keys alive + synchronised on disk
    next_key()      thread-safe round-robin over the pool (env overrides file)
    pooled_headers() egress hook: rotate Authorization when the URL targets
                    api.abliteration.ai; all other URLs pass through untouched

Pool storage: abliteration_pool.json next to this module (full key values ->
gitignored). Env override: ABLITERATION_POOL_KEYS=key1,key2,...  File path
override: ABLITERATION_POOL_FILE (tests point this at a session tmp dir).

CLI:
    python abliteration_keys.py status
    python abliteration_keys.py ensure-pool 2
    python abliteration_keys.py revoke <key_id>

Design rules (mirrors the repo header):
    6. Guards run once; the egress hook never raises into the request path -
       any pool failure degrades to the configured single key.
"""

import json
import os
import threading
import time
import uuid
from typing import Dict, List, Optional

import httpx

__all__ = [
    "ABLIT_BASE",
    "KeyFactory",
    "ensure_pool",
    "next_key",
    "pooled_headers",
    "pool_summary",
    "reload_pool",
]

ROOT = os.path.dirname(os.path.abspath(__file__))
_POOL_FILE_ENV = os.getenv("ABLITERATION_POOL_FILE") or ""
POOL_PATH = _POOL_FILE_ENV if _POOL_FILE_ENV else os.path.join(ROOT, "abliteration_pool.json")

ABLIT_BASE = os.getenv("ABLITERATION_API_URL", "https://api.abliteration.ai/v1")
POOL_PREFIX = os.getenv("ABLITERATION_POOL_PREFIX", "hub-pool")
POOL_SIZE = int(os.getenv("ABLITERATION_POOL_SIZE", "2"))


def _env_or_user_scope(name: str) -> str:
    """Process env first; else the persistent Windows User-scope value
    (HKCU\\Environment, where `setx` writes) - stale shells that started
    before the keys were installed still resolve them. On macOS/Linux the
    registry lookup is simply absent (ImportError) and the process env (or
    the shell profile) is the only source."""
    val = os.environ.get(name, "")
    if val:
        return val
    try:
        import winreg  # Windows only; macOS/Linux raises ImportError here
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val, _ = winreg.QueryValueEx(k, name)
    except (ImportError, OSError):
        val = ""
    return val or ""


def admin_key() -> str:
    return _env_or_user_scope("ABLITERATION_ADMIN_KEY")


# ---------------------------------------------------------------------------
# Round-robin pool (read side - hot path, must never raise)
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_STATE: Dict[str, object] = {"spec": None, "keys": [], "idx": 0}


def reload_pool() -> None:
    """Forget the cached pool; the next call re-reads env/file."""
    with _LOCK:
        _STATE["spec"] = None


def _load_pool_file() -> Dict:
    try:
        with open(POOL_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _resolve_keys() -> List[str]:
    env = os.getenv("ABLITERATION_POOL_KEYS", "")
    if env.strip():
        spec = ("env", env)
        keys = [k.strip() for k in env.split(",") if k.strip()]
    else:
        data = _load_pool_file()
        keys = [k.get("value", "") for k in data.get("keys", []) if k.get("value")]
        spec = ("file", data.get("saved_at"))
    with _LOCK:
        if _STATE["spec"] != spec:
            _STATE["spec"] = spec
            _STATE["keys"] = keys
            _STATE["idx"] = 0
        return list(_STATE["keys"])


def next_key() -> str:
    """Next pool key, round-robin. '' when the pool is empty (caller keeps
    its configured single key)."""
    keys = _resolve_keys()
    if not keys:
        return ""
    with _LOCK:
        idx = int(_STATE["idx"])
        _STATE["idx"] = (idx + 1) % len(keys)
        return keys[idx % len(keys)]


def _is_ablit(url: str) -> bool:
    return "api.abliteration.ai" in (url or "")


def pooled_headers(headers: Optional[Dict[str, str]], url: str) -> Dict[str, str]:
    """Egress hook for the gateway/hedge request paths.

    When `url` targets api.abliteration.ai and the pool is non-empty, return
    a copy of `headers` with Authorization rotated to the next pool key. Any
    other URL (Hive, gx10 hub, CYBER-FROST, ...) returns `headers` unchanged
    so today's live topology behaves exactly as before. The input dict is
    never mutated."""
    if not _is_ablit(url):
        return headers or {}
    key = next_key()
    if not key:
        return headers or {}
    out = dict(headers or {})
    out["Authorization"] = f"Bearer {key}"
    return out


def _redact(value: str) -> str:
    if len(value) <= 8:
        return value[:3] + "..."
    return value[:5] + "..." + value[-4:]


def pool_summary() -> Dict:
    """Redacted pool status for status endpoints / CLI."""
    env = os.getenv("ABLITERATION_POOL_KEYS", "")
    if env.strip():
        n = len([k for k in env.split(",") if k.strip()])
        return {"source": "env", "size": n}
    data = _load_pool_file()
    keys = data.get("keys", [])
    return {
        "source": "file",
        "size": len(keys),
        "keys": [
            {
                "id": k.get("id"),
                "name": k.get("name"),
                "redacted": _redact(k.get("value", "")),
                "created_at": k.get("created_at"),
            }
            for k in keys
        ],
    }


# ---------------------------------------------------------------------------
# KeyFactory (write side - Admin API)
# ---------------------------------------------------------------------------

class KeyFactory:
    """Create/list/revoke Project API keys through the Abliteration
    Administration API. One instance, no state besides credentials."""

    def __init__(self, base_url: str = ABLIT_BASE, key: str = "", project_id: str = ""):
        self.base = base_url.rstrip("/")
        self.key = key or admin_key()
        self._project_id = project_id

    # -- helpers -----------------------------------------------------------

    def _headers(self, idem: Optional[str] = None) -> Dict[str, str]:
        if not self.key:
            raise RuntimeError("ABLITERATION_ADMIN_KEY is not set")
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if idem:
            h["Idempotency-Key"] = idem
        return h

    def project_id(self, client: Optional[httpx.Client] = None) -> str:
        """First project of the admin key's organization (cached)."""
        if self._project_id:
            return self._project_id
        own = client is None
        c = client or httpx.Client(timeout=30.0)
        try:
            resp = c.get(f"{self.base}/organization/projects?limit=100",
                        headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data") or []
            if not items:
                raise RuntimeError("organization has no projects")
            self._project_id = items[0]["id"]
            return self._project_id
        finally:
            if own:
                c.close()

    # -- Admin API surface -------------------------------------------------

    def list_keys(self, client: Optional[httpx.Client] = None) -> List[Dict]:
        own = client is None
        c = client or httpx.Client(timeout=30.0)
        try:
            pid = self.project_id(c)
            out: List[Dict] = []
            after = None
            while True:
                url = f"{self.base}/organization/projects/{pid}/api_keys?limit=100"
                if after:
                    url += f"&after={after}"
                resp = c.get(url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                out.extend(data.get("data") or [])
                if not data.get("has_more"):
                    break
                after = data.get("last_id")
            return out
        finally:
            if own:
                c.close()

    def create_key(self, name: str, client: Optional[httpx.Client] = None) -> Dict:
        """Mint one project key. Returns the full creation record including
        `value` (the full key is shown ONCE - persist it immediately)."""
        own = client is None
        c = client or httpx.Client(timeout=30.0)
        try:
            pid = self.project_id(c)
            idem = f"key-create-{name}-{uuid.uuid4().hex[:12]}"
            resp = c.post(
                f"{self.base}/organization/projects/{pid}/api_keys",
                headers=self._headers(idem),
                json={"name": name},
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if own:
                c.close()

    def revoke_key(self, key_id: str, client: Optional[httpx.Client] = None) -> Dict:
        own = client is None
        c = client or httpx.Client(timeout=30.0)
        try:
            pid = self.project_id(c)
            resp = c.delete(
                f"{self.base}/organization/projects/{pid}/api_keys/{key_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if own:
                c.close()


# ---------------------------------------------------------------------------
# Pool maintenance
# ---------------------------------------------------------------------------

def ensure_pool(size: int = POOL_SIZE, prefix: str = POOL_PREFIX,
                factory: Optional[KeyFactory] = None,
                pool_path: Optional[str] = None,
                client: Optional[httpx.Client] = None) -> Dict:
    """Keep exactly `size` active pool keys named `<prefix>-<i>`.

    - Existing pool entries still active remotely are kept (matched by id).
    - Entries revoked/expired remotely are dropped from the local pool.
    - Missing entries are minted fresh via the Admin API.
    Returns the redacted summary; full values are written to the pool file."""
    path = pool_path or POOL_PATH
    f = factory or KeyFactory()
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
    try:
        remote = {k["id"]: k for k in f.list_keys(client)}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            saved = {}
        kept: List[Dict] = []
        for entry in saved.get("keys", []):
            r = remote.get(entry.get("id"))
            if r and r.get("status") == "active" and str(r.get("name", "")).startswith(prefix):
                kept.append({
                    "id": entry["id"], "name": entry.get("name"),
                    "value": entry.get("value"), "created_at": entry.get("created_at"),
                })
        for i in range(1, size + 1):
            if any(k["name"] == f"{prefix}-{i}" for k in kept):
                continue
            created = f.create_key(f"{prefix}-{i}", client)
            kept.append({
                "id": created["id"], "name": created.get("name"),
                "value": created.get("value"), "created_at": created.get("created_at"),
            })
        # drop surplus same-prefix keys remotely + locally (size enforcement)
        by_name = {}
        for k in kept:
            by_name[k["name"]] = k
        surplus = sorted(n for n in by_name if n.startswith(prefix))[size:]
        for n in surplus:
            f.revoke_key(by_name[n]["id"], client)
            del by_name[n]
        data = {"project_id": f.project_id(client), "saved_at": time.time(),
                "keys": [by_name[n] for n in sorted(by_name)]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if own:
            client.close()
    reload_pool()
    # Redacted summary of the pool THIS call wrote (independent of the
    # module-level POOL_PATH, so tests with pool_path= stay hermetic).
    keys = data.get("keys", [])
    return {
        "source": "file",
        "size": len(keys),
        "keys": [
            {
                "id": k.get("id"),
                "name": k.get("name"),
                "redacted": _redact(k.get("value", "")),
                "created_at": k.get("created_at"),
            }
            for k in keys
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Abliteration key factory + pool")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the pool (redacted)")
    ep = sub.add_parser("ensure-pool", help="mint/verify the N-key pool")
    ep.add_argument("n", nargs="?", type=int, default=POOL_SIZE)
    rv = sub.add_parser("revoke", help="revoke a project key by id")
    rv.add_argument("key_id")
    args = p.parse_args(argv)

    if args.cmd == "status":
        print(json.dumps(pool_summary(), indent=2))
        return 0
    if args.cmd == "ensure-pool":
        print(json.dumps(ensure_pool(args.n), indent=2))
        return 0
    if args.cmd == "revoke":
        f = KeyFactory()
        print(json.dumps(f.revoke_key(args.key_id), indent=2))
        reload_pool()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())



