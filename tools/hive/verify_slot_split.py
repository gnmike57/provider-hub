"""Verify the SPECIALIST and WORKER slots resolve INDEPENDENTLY (offline).

The two slots must never collapse onto each other:

  * SPECIALIST (the divert target, proxy_gateway.Settings) is
    SPECIALIST_MODEL (default abliterated-model-large-v2) on
    SPECIALIST_API_URL (Abliteration.ai by default).
  * WORKER (the speculative hedge branch, speculative_hedge.HedgeSettings) is
    WORKER_MODEL / WORKER_API_URL, falling back to FALLBACK_* and finally the
    local hub default.

Both credentials resolve through the same chain (WORKER_API_KEY ->
SPECIALIST_API_KEY -> FALLBACK_API_KEY -> ABLITERATION_API_KEY -> "none"). An
empty or "none" key on either slot is the B22 regression: the branch sends no
Authorization header and every hosted hop dies with a 401. This script asserts
both slots resolve to a real credential, without printing it.

This process is started before any env broadcast, so the User scope is seeded
explicitly BEFORE the imports (both Settings objects are built at import time).

Usage:  python tools/hive/verify_slot_split.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

SPEC_URL = "https://api.abliteration.ai/v1/chat/completions"
SPEC_MODEL = "abliterated-model-large-v2"


def _win_value(name):
    """The HKCU\\Environment value, or "" when absent / not Windows."""
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:  # noqa: BLE001
        return ""


def _resolve(name, default=""):
    """Process env first, then the persisted User scope (mirrors a fresh shell)."""
    return os.environ.get(name) or _win_value(name) or default


def main() -> int:
    # Seed the persisted User values into this process before importing the
    # modules: both build their Settings at import time.
    for var in ("WORKER_API_URL", "WORKER_MODEL", "WORKER_API_KEY",
                "SPECIALIST_API_URL", "SPECIALIST_MODEL", "SPECIALIST_API_KEY",
                "FALLBACK_API_URL", "FALLBACK_MODEL", "FALLBACK_API_KEY",
                "ABLITERATION_API_KEY", "ABLITERATION_API_URL"):
        val = _resolve(var)
        if val:
            os.environ[var] = val
    # never used here, but both Settings want a primary.
    os.environ.setdefault("PRIMARY_API_URL", "http://127.0.0.1:1/v1/chat/completions")
    os.environ.setdefault("PRIMARY_MODEL", "unused")

    import proxy_gateway  # noqa: E402
    import speculative_hedge  # noqa: E402

    spec = proxy_gateway.SETTINGS
    worker = speculative_hedge.HedgeSettings()

    expect_spec = _resolve("SPECIALIST_MODEL", SPEC_MODEL)
    expect_spec_url = _resolve("SPECIALIST_API_URL", SPEC_URL)

    print("--- SPECIALIST slot (divert target, proxy_gateway.Settings) ---")
    print(f"  url   = {spec.fallback_api_url}")
    print(f"  model = {spec.fallback_model}")
    print(f"  key   = {'set' if spec.fallback_api_key not in ('', 'none') else 'NONE'} "
          f"(len={len(spec.fallback_api_key)})")

    print("\n--- WORKER slot (hedge branch, speculative_hedge.HedgeSettings) ---")
    print(f"  url   = {worker.worker_url}")
    print(f"  model = {worker.worker_model}")
    print(f"  key   = {'set' if worker.worker_key not in ('', 'none') else 'NONE'} "
          f"(len={len(worker.worker_key)})")

    print("\n--- assertions ---")
    checks = [
        ("specialist model is the resolved SPECIALIST_MODEL",
         spec.fallback_model == expect_spec),
        ("specialist endpoint is the resolved SPECIALIST_API_URL",
         spec.fallback_api_url == expect_spec_url),
        ("worker model is not empty", bool(worker.worker_model)),
        ("the two models DIFFER (slots are split)",
         spec.fallback_model != worker.worker_model),
        ("specialist key resolved (not none - B22)", spec.fallback_api_key not in ("", "none")),
        ("worker key resolved (not none - B22)", worker.worker_key not in ("", "none")),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
