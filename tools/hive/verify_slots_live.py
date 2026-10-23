"""LIVE proof that both slots answer on their OWN model (2026-10-16, upd. 2026-10-23).

Calls the exact payloads the two modules build, straight at their resolved
endpoints, so nothing about the wiring is simulated:

  * WORKER  - the speculative hedge's worker branch payload
              (speculative_hedge.HedgeSettings.worker_*).
  * SPECIALIST - the divert target payload
              (proxy_gateway.SETTINGS.fallback_*).

Each is asked a one-word PONG; the reply's `model` field must echo the id we
sent, which proves the endpoint accepted THAT model (the provider returns the
requested id only when it resolves). Reads the key without printing it.

Usage:  python tools/hive/verify_slots_live.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

WORKER_EXPECT = "deepseek-ai/deepseek-v4.1-flash-1017"  # the gx10 hub's local survivor
SPEC_EXPECT = "abliterated-model-large-v2"  # Abliteration.ai


def _win_value(name):
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:  # noqa: BLE001
        return ""


def _seed():
    for var in ("ABLITERATION_API_KEY", "SPECIALIST_API_URL", "SPECIALIST_MODEL",
                "WORKER_API_URL", "WORKER_MODEL"):
        val = os.environ.get(var) or _win_value(var)
        if val:
            os.environ[var] = val
    os.environ.setdefault("PRIMARY_API_URL", "http://127.0.0.1:1/v1/chat/completions")
    os.environ.setdefault("PRIMARY_MODEL", "unused")


def _pong(url, key, model, timeout=120.0, dual_budget=True):
    """Mirror the payload each module actually builds.

    dual_budget=True  -> hedge worker branch: max_tokens AND max_completion_tokens
                         (Hive-style self-hosted backends honour only the latter).
    dual_budget=False  -> gateway divert branch: max_tokens alone (specialist
                         providers are OpenAI-strict and 400 on both fields).
    """
    body = {"model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: PONG"}],
            "stream": False}
    if dual_budget:
        body["max_tokens"] = 256
        body["max_completion_tokens"] = 256
    else:
        body["max_tokens"] = 256
    headers = {"Content-Type": "application/json"}
    if key and key != "none":
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        doc = json.loads(r.read())
    text = ((doc.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    return doc.get("model", ""), text.strip()


def main() -> int:
    _seed()
    import proxy_gateway  # noqa: E402
    import speculative_hedge  # noqa: E402

    spec = proxy_gateway.SETTINGS
    worker = speculative_hedge.HedgeSettings()

    ok = True
    for label, url, key, model, expect, dual in (
        ("WORKER (hedge)", worker.worker_url, worker.worker_key, worker.worker_model, WORKER_EXPECT, True),
        ("SPECIALIST (divert)", spec.fallback_api_url, spec.fallback_api_key,
         spec.fallback_model, SPEC_EXPECT, False),
    ):
        print(f"\n=== {label} ===")
        print(f"  url={url}\n  model={model}\n  key={'set' if key and key != 'none' else 'NONE'}")
        if model != expect:
            print(f"  [FAIL] resolved model {model!r} != expected {expect!r}")
            ok = False
            continue
        try:
            echoed, text = _pong(url, key, model, dual_budget=dual)
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] live call: {type(exc).__name__}: {exc}")
            ok = False
            continue
        match = echoed == expect
        got_pong = "PONG" in text.upper()
        print(f"  echoed_model={echoed!r} content={text[:80]!r}")
        print(f"  [{'PASS' if match else 'FAIL'}] upstream echoed the requested id")
        print(f"  [{'PASS' if got_pong else 'FAIL'}] replied PONG")
        ok = ok and match and got_pong

    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
