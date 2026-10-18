"""Verify the WORKER and SPECIALIST slots resolve to their OWN models.

Operator requirement (2026-10-16): the two NanoGPT-backed slots are distinct -

  * WORKER (the speculative hedge branch, speculative_hedge.py) is
    xiaomi/mimo-v2.6-flash-abliterated, bound through WORKER_MODEL.
  * SPECIALIST (the refusal/failure divert target, proxy_gateway.py) stays
    abliteration-ai/abliterated-model-large-v2, bound through SPECIALIST_MODEL.

Both share the nano-gpt.com endpoint and the NANOGPT_API_KEY credential. This
script reads the environment the way BOTH modules do (Windows User scope counts
too), then asserts the split: if WORKER_MODEL were unset, the hedge would
silently fall back to SPECIALIST_MODEL/FALLBACK_MODEL and the slip would be
invisible. Reads the key without printing it.

Usage:  python tools/hive/verify_slot_split.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

NANO_URL = "https://nano-gpt.com/api/v1/chat/completions"
SPEC_MODEL = "abliteration-ai/abliterated-model-large-v2"
WORKER_MODEL = "xiaomi/mimo-v2.6-flash-abliterated"


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
    key = _resolve("NANOGPT_API_KEY")
    print(f"NANOGPT_API_KEY: {'present' if key else 'MISSING'} (len={len(key)})")

    # The environment must be set BEFORE the imports: proxy_gateway builds its
    # Settings at import time (module-level SETTINGS); speculative_hedge builds
    # HedgeSettings the same way. New shells see the persisted User values, but
    # THIS process was started before the broadcast, so seed them explicitly.
    for var in ("WORKER_API_URL", "WORKER_MODEL", "WORKER_API_KEY",
                "SPECIALIST_API_URL", "SPECIALIST_MODEL", "NANOGPT_API_KEY"):
        val = _resolve(var)
        if val:
            os.environ[var] = val
    os.environ.setdefault("SPECIALIST_API_URL", NANO_URL)
    os.environ.setdefault("WORKER_API_URL", NANO_URL)
    # never used here, but both Settings want a primary.
    os.environ.setdefault("PRIMARY_API_URL", "http://127.0.0.1:1/v1/chat/completions")
    os.environ.setdefault("PRIMARY_MODEL", "unused")

    import proxy_gateway  # noqa: E402
    import speculative_hedge  # noqa: E402

    spec = proxy_gateway.SETTINGS
    worker = speculative_hedge.HedgeSettings()

    print("\n--- SPECIALIST slot (divert target, proxy_gateway.Settings) ---")
    print(f"  url   = {spec.fallback_api_url}")
    print(f"  model = {spec.fallback_model}")
    print(f"  key   = {'NANOGPT_API_KEY' if spec.fallback_api_key == key else 'OTHER/none'}")

    print("\n--- WORKER slot (hedge branch, speculative_hedge.HedgeSettings) ---")
    print(f"  url   = {worker.worker_url}")
    print(f"  model = {worker.worker_model}")
    print(f"  key   = {'NANOGPT_API_KEY' if worker.worker_key == key else 'OTHER/none'}")

    print("\n--- assertions ---")
    checks = [
        ("specialist model == v2-large", spec.fallback_model == SPEC_MODEL),
        ("worker model == mimo 2.6 flash abliterated", worker.worker_model == WORKER_MODEL),
        ("the two models DIFFER (slots are split)", spec.fallback_model != worker.worker_model),
        ("specialist key is the NanoGPT key", spec.fallback_api_key == key),
        ("worker key is the NanoGPT key", worker.worker_key == key),
        ("both slots on the nano-gpt endpoint",
         spec.fallback_api_url == NANO_URL and worker.worker_url == NANO_URL),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
