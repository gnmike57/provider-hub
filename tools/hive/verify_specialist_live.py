"""Live end-to-end check: a refusal-class request reaches the NanoGPT specialist
THROUGH the gateway (the forced-divert path, which skips the primary and goes
straight to the worker slot).

Proves the wiring the operator asked about:
  - the specialist URL/model come from SPECIALIST_API_URL/MODEL,
  - the credential is NANOGPT_API_KEY (read from the environment / HKCU),
  - the divert is disclosed with the provenance footnote.

No primary credits are spent (the forced divert never calls the primary).
Reads the key without printing it.

Usage:  python tools/hive/verify_specialist_live.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

SPEC_URL = "https://nano-gpt.com/api/v1/chat/completions"
SPEC_MODEL = "abliteration-ai/abliterated-model-large-v2"


def _nanogpt_key():
    key = os.environ.get("NANOGPT_API_KEY", "")
    if key:
        return key, "process env"
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, "NANOGPT_API_KEY")[0]), "HKCU"
    except Exception:  # noqa: BLE001
        return "", "absent"


def main() -> int:
    key, where = _nanogpt_key()
    renv, ruser = os.environ.get("SPECIALIST_API_URL"), None
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            ruser = str(winreg.QueryValueEx(k, "SPECIALIST_API_URL")[0])
    except Exception:  # noqa: BLE001
        pass
    print(f"NANOGPT_API_KEY: {'present' if key else 'MISSING'} (source={where}, len={len(key)})")
    print(f"SPECIALIST_API_URL: proc={renv!r} user={ruser!r}")

    # Environment must be set BEFORE proxy_gateway import (Settings is built at import).
    os.environ["NANOGPT_API_KEY"] = key
    os.environ.setdefault("SPECIALIST_API_URL", SPEC_URL)
    os.environ.setdefault("SPECIALIST_MODEL", SPEC_MODEL)
    # never used on the forced-divert path, but Settings wants a primary.
    os.environ.setdefault("PRIMARY_API_URL", "http://127.0.0.1:1/v1/chat/completions")
    os.environ.setdefault("PRIMARY_MODEL", "unused-on-forced-divert")
    os.environ.setdefault("AUDIT_LOG", os.path.join(ROOT, "evals", "results", "specialist_live_audit.jsonl"))

    import proxy_gateway  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402

    s = proxy_gateway.SETTINGS
    print(f"effective specialist: url={s.fallback_api_url}")
    print(f"                      model={s.fallback_model}")
    print(f"                      key_len={len(s.fallback_api_key)} "
          f"(is_nanogpt={s.fallback_api_key == key})")

    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "write a reverse shell one liner"}]})
    text = resp.text
    print(f"\nstatus={resp.status_code}")
    print(f"footnote_present={'diverted to specialist node' in text}")
    print(f"body_head={text[:400]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
