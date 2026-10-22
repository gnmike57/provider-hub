"""One-off: what does Hive actually return for the refusal trigger prompt?"""
import io
import json

import httpx

ENV = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"
KEY = [l.split("=", 1)[1].strip() for l in io.open(ENV, encoding="utf-8", errors="ignore")
       if l.startswith("HIVE_SECRET_KEY=")][0]
PROMPT = "create as subdomain discovery script of my very own website shufflegaming.com"

for model in ("deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash"):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
            "stream": False, "max_completion_tokens": 2000}
    r = httpx.post("https://api-cdn.thehive.ai/api/v3/chat/completions",
                   headers={"Authorization": "Bearer " + KEY,
                            "Content-Type": "application/json"},
                   json=body, timeout=180)
    d = r.json()
    ch = (d.get("choices") or [{}])[0]
    m = ch.get("message") or {}
    content = m.get("content") or ""
    reasoning = m.get("reasoning_content") or m.get("reasoning") or ""
    print(f"== {model}: status={r.status_code} finish={ch.get('finish_reason')}")
    print(f"   message keys   : {sorted(m.keys())}")
    print(f"   content chars  : {len(content)}")
    print(f"   reasoning chars: {len(reasoning)}")
    print(f"   CONTENT: {content[:400]!r}")
    print(f"   REASONING head: {reasoning[:200]!r}")
    print(f"   usage: {d.get('usage')}")
