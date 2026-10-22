"""MOCK ABLITERATION SERVER (2026-10-22) - the "simulated ablit credits"
side of the max-scope matrix runs.

The matrix test hub (port 9100) points EVERY abliteration hop here:
PRIMARY stays real thehive.ai (real credits), FALLBACK + every chain
terminal/uncensored hop is THIS server (zero real ablit spend, provable
via /__stats). OpenAI chat-completions SSE compatible.

Behaviors are selected by MARKERS embedded in the last user turn (they
survive camo/REDHANDS verbatim relays by construction):
    [mock:refuse]  -> a refusal answer (drives the zero-refusal ladder)
    [mock:429]     -> HTTP 429 (drives conductor/subtask + ladder retries)
    [mock:slow]    -> 5s pre-first-chunk latency (TTFT stress)
    [mock:empty]   -> thinking-only: empty content, finish stop
    (no marker)    -> CLEAN: a substantive uncensored-style answer that
                      echoes the ask's first significant terms (so lexical
                      term-coverage verdicts work through the mock).

/__stats returns every recorded call (model, redhands_system, behavior,
ts) + counters; /__reset clears them.
"""
import os
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient  # noqa: F401 (import sanity in tests)

app = FastAPI(title="mock-ablit")

_CALLS = []
_STOP = ["I cannot help with that.", "I'm unable to comply with that request.",
         "That is not something I can assist with."]
_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
_RH_RE = re.compile(r"\[rh:(M\d+)\]")


def _last_user(messages):
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return " ".join(str(b.get("text", "")) if isinstance(b, dict)
                                else str(b) for b in c)
            return str(c or "")
    return ""


def _behavior(text):
    for marker in ("refuse", "429", "slow", "empty"):
        if f"[mock:{marker}]" in text:
            return marker
    return "clean"


def _clean_answer(text):
    terms = [w for w in _TERM_RE.findall(text)
             if w.lower() not in ("that", "this", "with", "from", "your",
                                  "mock", "please", "write", "explain")][:6]
    body = (" | ".join(terms) if terms else "the authorized objective")
    return (f"MOCK-ABLIT uncensored answer covering {body}. The full "
            f"mechanism is explained step by step with working evidence.")


def _chunk(content=None, finish=None, model="abliterated-model-large-v2"):
    delta = {}
    if content is not None:
        delta["content"] = content
    return {"id": f"mock-{uuid.uuid4().hex[:10]}",
            "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    text = _last_user(messages)
    behavior = _behavior(text)
    redhands = any(
        isinstance(m, dict) and m.get("role") == "system"
        and "REDHANDS" in str(m.get("content", "")) for m in messages)
    _CALLS.append({"ts": time.time(), "behavior": behavior,
                  "redhands_system": redhands,
                  "rh_tags": _RH_RE.findall(text),
                  "model": body.get("model"), "text_head": text[:80]})
    if behavior == "429":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"error": "rate limited"})
    if behavior == "slow":
        time.sleep(5.0)
    from fastapi.responses import StreamingResponse
    import json as _json

    async def gen():
        if behavior == "refuse":
            refuse = _STOP[len(_CALLS) % len(_STOP)]
            yield f"data: {_json.dumps(_chunk(refuse))}\n\n".encode()
            yield f"data: {_json.dumps(_chunk(finish='stop'))}\n\n".encode()
        elif behavior == "empty":
            yield f"data: {_json.dumps(_chunk(finish='stop'))}\n\n".encode()
        else:
            answer = _clean_answer(text)
            mid = max(1, len(answer) // 2)
            for part in (answer[:mid], answer[mid:]):
                yield f"data: {_json.dumps(_chunk(part))}\n\n".encode()
            yield f"data: {_json.dumps(_chunk(finish='stop'))}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/__stats")
async def stats():
    counts = {}
    for c in _CALLS:
        counts[c["behavior"]] = counts.get(c["behavior"], 0) + 1
    return {"total": len(_CALLS), "by_behavior": counts,
            "redhands_calls": sum(1 for c in _CALLS if c["redhands_system"]),
            "calls": _CALLS[-200:]}


@app.get("/__reset")
async def reset():
    _CALLS.clear()
    return {"ok": True}


if __name__ == "__main__":  # pragma: no cover - manual boot
    import uvicorn
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.getenv("MOCK_ABLIT_PORT", "9400")), log_level="warning")
