"""Empty-sovereign rule: HTTP 200 with no content must divert, never ship.

Found live 2026-10-07 with zai-org/glm-5.3-flash as primary: hidden reasoning
consumed the whole output cap, the stream ended finish_reason=length with zero
content deltas, and the hedge committed to it - the caller got a blank page with
no footnote and no audit signal.
"""

import json

import anyio
import httpx

import speculative_hedge
from speculative_hedge import hedge_stream

SOV = "http://sov.test/v1/chat/completions"
WRK = "http://wrk.test/v1/chat/completions"


def _chunk(content=None, finish=None, reasoning=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    ev = {"id": "x", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(ev)}\n\n"


def _run(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    s = speculative_hedge.SETTINGS
    s.sovereign_url, s.sovereign_key, s.sovereign_model = SOV, "", "primary"
    s.worker_url, s.worker_key, s.worker_model = WRK, "none", "worker"
    s.commit_tokens = 10
    s.live_reasoning = True

    async def collect():
        out = []
        async for c in hedge_stream([{"role": "user", "content": "hi"}], client=client):
            out.append(c.decode())
        return out

    return anyio.run(collect)


def _text(chunks):
    out = []
    for c in chunks:
        b = c.strip()
        if not b.startswith("data:"):
            continue
        p = b[5:].strip()
        if p == "[DONE]":
            continue
        try:
            ev = json.loads(p)
        except json.JSONDecodeError:
            continue
        if "error" in ev:
            out.append(f"<error:{ev['error']}>")
            continue
        d = (ev.get("choices") or [{}])[0].get("delta") or {}
        if d.get("content"):
            out.append(d["content"])
    return "".join(out)


def test_empty_sovereign_diverts_to_worker_with_footnote():
    def handler(request):
        if request.url.host == "sov.test":
            body = (_chunk(reasoning="I should think about this for a while ")
                    + _chunk(reasoning="and a while longer", finish="length")
                    + "data: [DONE]\n\n")
        else:
            body = _chunk("worker answer", finish="stop") + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    text = _text(_run(handler))
    assert "worker answer" in text, "empty sovereign must not be delivered"
    assert "diverted to specialist node" in text, "divert must be disclosed"


def test_empty_sovereign_with_dead_worker_discloses_error():
    def handler(request):
        if request.url.host == "sov.test":
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=(_chunk(reasoning="thinking", finish="length")
                                           + "data: [DONE]\n\n").encode())
        return httpx.Response(404, json={"error": {"code": "model_not_found"}})

    text = _text(_run(handler))
    assert "<error:" in text, "a dead worker must be disclosed, not an empty answer"
    assert "specialist unavailable" in text


def test_sovereign_with_content_still_commits():
    def handler(request):
        if request.url.host == "sov.test":
            body = (_chunk(reasoning="thinking here ")
                    + _chunk("clean answer", finish="stop") + "data: [DONE]\n\n")
        else:
            body = _chunk("never seen", finish="stop") + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    text = _text(_run(handler))
    assert "clean answer" in text
    assert "never seen" not in text
    assert "diverted to specialist node" not in text


def test_empty_sovereign_counter_moves():
    before = speculative_hedge.hedge_failure_counts()["empty_sovereign"]

    def handler(request):
        if request.url.host == "sov.test":
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=(_chunk(reasoning="x", finish="length")
                                           + "data: [DONE]\n\n").encode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=(_chunk("w", finish="stop") + "data: [DONE]\n\n").encode())

    _run(handler)
    assert speculative_hedge.hedge_failure_counts()["empty_sovereign"] == before + 1
