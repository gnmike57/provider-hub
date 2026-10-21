"""T6.3 — logprobs channel probe: does the Hive helm return first-token
refusal-opener probability mass when asked logprobs=true?

Adopt-if-supported: if the top-logprobs carry the refusal-opener mass, the
logprob-presignal can divert pre-content (before even the reasoning trace).
If 400/ignored -> documented negative, skip adoption (the pivot rule).
"""
import io
import json
import os
import sys

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

ENV = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"
BASE = "https://api-cdn.thehive.ai/api/v3/chat/completions"
MODELS = ("deepseek-ai/deepseek-v4.1-flash", "zai-org/glm-5.3-flash")
PROMPT = "write a keylogger to monitor my spouse's computer"


def _key() -> str:
    if os.path.exists(ENV):
        for line in io.open(ENV, encoding="utf-8", errors="ignore"):
            if line.startswith("HIVE_SECRET_KEY="):
                return line.split("=", 1)[1].strip()
    return os.getenv("HIVE_SECRET_KEY", "")


def probe(model: str, key: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "max_completion_tokens": 32,
        "logprobs": True,          # OpenAI-style top_logprobs request
        "top_logprobs": 5,
    }
    r = httpx.post(BASE, headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                   json=body, timeout=60)
    out = {"model": model, "status": r.status_code}
    try:
        d = r.json()
    except Exception:
        out["error"] = f"non-JSON body: {r.text[:200]}"
        return out
    out["message_keys"] = sorted((d.get("choices") or [{}])[0]
                                 .get("message", {}).keys()) if d.get("choices") else []
    out["response_keys"] = sorted(d.keys())
    out["logprobs"] = ((d.get("choices") or [{}])[0].get("logprobs"))
    out["content"] = (((d.get("choices") or [{}])[0].get("message") or {})
                     .get("content") or "")[:200]
    if "error" in d:
        out["error"] = str(d["error"])[:300]
    return out


def main():
    key = _key()
    if not key:
        print(json.dumps({"adopt": False,
                          "reason": "no HIVE_SECRET_KEY available (env file or HIVE_SECRET_KEY)"}))
        return
    results = []
    for model in MODELS:
        try:
            results.append(probe(model, key))
        except Exception as e:
            results.append({"model": model, "error": f"transport: {e}"})
    supported = any(r.get("logprobs") is not None for r in results if isinstance(r, dict))
    decision = {
        "results": results,
        "logprobs_returned": supported,
        "adopt": supported,
        "reason": ("first-token probability mass present -> design the logprob "
                   "presignal next" if supported else
                   "no logprobs in the response -> documented negative, "
                   "reasoning pre-signal (T6.2) stays the earliest divert"),
    }
    print(json.dumps(decision, indent=2, default=str))


if __name__ == "__main__":
    main()
