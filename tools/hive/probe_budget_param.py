"""Raw Hive STREAM probe: does content flow for the refusal-trigger prompt?

Compares max_tokens vs max_completion_tokens (Hive documents the latter).
"""
import io
import json

import httpx

ENV = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"
KEY = [l.split("=", 1)[1].strip() for l in io.open(ENV, encoding="utf-8", errors="ignore")
       if l.startswith("HIVE_SECRET_KEY=")][0]
PROMPT = "create as subdomain discovery script of my very own website shufflegaming.com"


def stream(model, param, value):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
            "stream": True, param: value}
    content, reasoning, finish, chunks, first_t = [], [], None, 0, None
    import time
    t0 = time.time()
    with httpx.stream("POST", "https://api-cdn.thehive.ai/api/v3/chat/completions",
                      headers={"Authorization": "Bearer " + KEY,
                               "Content-Type": "application/json"},
                      json=body, timeout=300) as r:
        for raw in r.iter_lines():
            if not raw.startswith("data:"):
                continue
            p = raw[5:].strip()
            if p == "[DONE]":
                break
            try:
                ev = json.loads(p)
            except json.JSONDecodeError:
                continue
            chunks += 1
            for ch in ev.get("choices", []):
                d = ch.get("delta") or {}
                if d.get("content"):
                    if first_t is None:
                        first_t = round(time.time() - t0, 2)
                    content.append(d["content"])
                if d.get("reasoning_content"):
                    reasoning.append(d["reasoning_content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    print(f"   {param}={value}: chunks={chunks} content={sum(map(len, content))}ch "
          f"reasoning={sum(map(len, reasoning))}ch finish={finish} "
          f"ttft={first_t}s total={round(time.time() - t0, 1)}s")
    print(f"      content head: {''.join(content)[:120]!r}")


for model in ("deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash"):
    print(f"== {model} (streaming)")
    stream(model, "max_tokens", 2000)
    stream(model, "max_completion_tokens", 2000)
