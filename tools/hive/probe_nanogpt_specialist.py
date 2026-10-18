"""Probe NanoGPT as the refusal-interception SPECIALIST provider.

Verifies the operator requirement end to end, without printing the key:

  1. NANOGPT_API_KEY is present in the environment (User scope counts too).
  2. The public catalog is reachable and holds the uncensored specialist ids.
  3. A tiny chat completion with the key PONGs on the specialist model.

Reads the key from NANOGPT_API_KEY (env); falls back to the User-scope value
via the registry-free path below only when the process env is empty.

Usage:
  python tools/hive/probe_nanogpt_specialist.py
  python tools/hive/probe_nanogpt_specialist.py --model abliteration-ai/abliterated-model-large-v2
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://nano-gpt.com/api/v1"
DEFAULT_SPECIALIST = "abliteration-ai/abliterated-model-large-v2"


def _key():
    key = os.environ.get("NANOGPT_API_KEY", "")
    if key:
        return key, "process env"
    # Windows User-scope fallback (the value lives in HKCU, not this shell).
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val, _ = winreg.QueryValueEx(k, "NANOGPT_API_KEY")
            return str(val), "HKCU\\\\Environment"
    except Exception:  # noqa: BLE001 - not on Windows / not set
        return "", "absent"


def _get(url, timeout):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return r.status, r.read()


def _post(url, body, key, timeout):
    req = urllib.request.Request(
        url, json.dumps(body).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_SPECIALIST)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    key, where = _key()
    print(f"1. NANOGPT_API_KEY: {'present' if key else 'MISSING'} "
          f"(source={where}, len={len(key)})")
    if not key:
        return 1

    print("2. catalog: GET /models")
    try:
        status, raw = _get(BASE + "/models", args.timeout)
        data = json.loads(raw).get("data", [])
        ids = [m.get("id", m) if isinstance(m, dict) else m for m in data]
        hits = [i for i in ids if "abliterat" in str(i).lower()]
        print(f"   {status} {len(ids)} models; uncensored candidates={hits[:10]}")
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {type(exc).__name__}: {exc}")

    print(f"3. chat PONG: {args.model}")
    try:
        status, raw = _post(BASE + "/chat/completions",
                            {"model": args.model,
                             "messages": [{"role": "user", "content": "Reply with the single word: PONG"}],
                             "max_tokens": 32, "stream": False},
                            key, args.timeout)
        doc = json.loads(raw)
        text = ((doc.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        print(f"   {status} content={text.strip()[:120]!r}")
    except urllib.error.HTTPError as exc:
        print(f"   HTTP {exc.code}: {exc.read()[:200]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
