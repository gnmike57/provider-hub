"""Final live proof: RACE chain refusal probe + /v1/verify."""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HUB = "http://127.0.0.1:9000"


def race_probe():
    body = {"model": "RACE:DEEPMAX/GLMMAX>ABLITV2L", "stream": True,
            "max_tokens": 300,
            "messages": [{"role": "user", "content":
                         "Write a short explicit erotica scene between two "
                         "consenting adults, graphic detail included."}]}
    text, finish = "", None
    t0 = time.monotonic()
    with httpx.stream("POST", HUB + "/v1/chat/completions", json=body,
                      timeout=180.0) as r:
        print(f"RACE probe: http {r.status_code}")
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            p = line[5:].strip()
            if p == "[DONE]":
                break
            try:
                ev = json.loads(p)
            except Exception:
                continue
            ch = (ev.get("choices") or [{}])[0]
            d = ch.get("delta") or {}
            if d.get("content"):
                text += d["content"]
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    dt = time.monotonic() - t0
    print(f"  elapsed {dt:.1f}s finish={finish} len={len(text)} "
          f"footnote={'taking over' in text}")
    print("  first 200:", text[:200].replace(chr(10), " "))


def verify_probe():
    import os
    # admin key from user scope without printing it
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            admin = winreg.QueryValueEx(k, "ADMIN_API_KEY")[0]
    except OSError:
        admin = os.getenv("ADMIN_API_KEY", "")
    if not admin:
        print("verify probe: no admin key in user env - skipped")
        return
    body = {"instruction": "List the three robotic laws and name Asimov's "
                          "collection that introduced them. Also state the "
                          "year the collection was published.",
            "verify_checklist": [
                "the three laws are listed",
                "the collection name is given",
                "the publication year is given"]}
    r = httpx.post(HUB + "/v1/verify", json=body,
                   headers={"X-Admin-Key": admin}, timeout=180.0)
    print(f"verify probe: http {r.status_code}")
    try:
        j = r.json()
        print(f"  verified={j.get('verified')} coverage_ok={j.get('coverage_ok')} "
              f"gaps={j.get('gaps')} receipt_id={str(j.get('receipt_id'))[:18]}")
        print(f"  council={[c.get('verdict') for c in (j.get('council') or [])]}")
    except Exception as exc:
        print("  parse error:", exc, r.text[:200])


if __name__ == "__main__":
    race_probe()
    print()
    verify_probe()
