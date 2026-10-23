"""W3 streamsmith regression fence (2026-10-20): one test per fix.

  1. chat_proxy terminal switch: a PASSTHROUGH stream whose upstream ends
     without finish_reason/[DONE] must COMMIT (close with [DONE]) - it used
     to fall through into the divert block, appending a full duplicate
     specialist answer to already-delivered content + inflating
     diverted_total.
  2. chat_proxy commit rule: a pending refusal presignal owns the commit
     decision until its grace window expires (BUFFER_CONTENT_TOKENS=10 vs
     GRACE_TOKENS=10 meant the buffer filled one token before the window
     could expire and the presignal was cleared unjudged).
  3. last-resort except Exception in the coordinator AND fallback_stream:
     an unexpected failure is disclosed as visible content + finish + [DONE]
     so no client ever sees a truncated 200 (F11/F13 class).
  4. hedge: tools/tool_choice are forwarded to BOTH branches (F6 parity).
  5. hedge: a non-dict SSE payload is skipped, not fatal (the isinstance
     guard used to run AFTER ev.get("choices") - dead code).
  6. hedge: the sovereign OPEN branches on the full classify_status
     taxonomy - 408/429 (retry_same) is retried, and an exhausted
     retry_same is disclosed, NEVER turned into a worker divert.
  7. hedge: __all__ no longer exports the phantom `hedge_settings`.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import proxy_gateway
import speculative_hedge
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _deltas(resp):
    out = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            continue
        try:
            ev = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


def _body(content="hello"):
    return {"messages": [{"role": "user", "content": content}], "stream": True}


# --- 1. terminal switch: PASSTHROUGH EOF commits, never double-answers ------
def test_passthrough_eof_without_done_commits_no_duplicate(gw, script):
    events = [chunk(f"tok{i} ") for i in range(30)]  # >= 25 tokens -> PASSTHROUGH
    # no finish chunk and no [DONE]: the upstream just closes the stream
    script.script(PRIMARY, [("sse", events)])
    script.script(WORKER, [("sse", [chunk("duplicate specialist answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    text = _deltas(resp)
    assert "tok0 " in text and "tok29 " in text     # the committed prefix survives
    assert text.count("tok0 ") == 1                 # ...delivered exactly once
    assert "duplicate specialist answer" not in text  # no second full answer
    assert resp.text.rstrip().endswith("data: [DONE]")  # stream still closes
    assert proxy_gateway._METRICS["diverted_total"] == 0


# --- 2. commit rule: the presignal owns the decision until grace expires ---
def test_full_buffer_does_not_clear_pending_presignal(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "buffer_content_tokens", 5)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "grace_tokens", 10)
    script.script(PRIMARY, [("sse", [
        chunk("I cannot help with that. "),  # presignal fires (token 1)
        chunk("No. "), chunk("No. "), chunk("No. "), chunk("No. "),  # buffer full at 5
        chunk("", finish="stop"),             # stream completes, presignal pending
        DONE,
    ])])
    script.script(WORKER, [("sse", [chunk("specialist rescued", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(resp)
    assert "specialist rescued" in text          # judged: still refusing -> divert
    assert "I cannot help" not in text
    assert proxy_gateway._METRICS["diverted_total"] == 1
    # ZERO-REFUSAL LAW (2026-10-22): the full-reply judge fires at the finish
    # site BEFORE the presignal-recovery branch, so this shape diverts as
    # tier3_refusal via zero_refusal_violation (the refusal core is anywhere
    # in the buffer) - presignal_failed_total no longer owns this decision.
    assert proxy_gateway._METRICS["zero_refusal_divert_total"] == 1


# --- 3a. coordinator last resort: disclose, never a truncated 200 ----------
def test_coordinator_last_resort_error_is_disclosed_as_content(gw, script, monkeypatch):
    """F11 -> RESCUE (operator directive 2026-10-21): an unexpected exception
    in the streaming path no longer ends on an error card - the uncensored
    specialist answers first (continuing from the buffered partial); the
    disclosure survives only when the rescue itself fails."""
    def _boom(_text):
        raise ValueError("screening exploded")

    monkeypatch.setattr(proxy_gateway, "is_routable", _boom)
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that. ", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("rescued after explosion", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    text = _deltas(resp)
    assert "rescued after explosion" in text
    assert "[gateway stream error: screening exploded]" not in text
    assert resp.text.rstrip().endswith("data: [DONE]")
    assert proxy_gateway._METRICS["stream_errors_total"] == 1
    assert proxy_gateway._METRICS["rescue_divert_total"] == 1


# --- 3b. fallback_stream last resort: disclose, never a truncated 200 ----
def test_specialist_stream_error_is_disclosed_as_content(gw, script):
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that. ", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("partial specialist "), ValueError("kaboom"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    text = _deltas(resp)
    assert "[specialist stream error: kaboom]" in text
    assert "taking over" in text  # provenance footnote still lands
    assert resp.text.rstrip().endswith("data: [DONE]")


# --- 4. hedge: tools/tool_choice forwarded to both branches ----------------
def test_hedge_forwards_tools_to_both_branches(gw, script, monkeypatch):
    # These assertions pin the LEGACY sovereign-wins semantics. The default
    # path since 2026-10-22 is race_stream (HEDGE_RACE_MODE=1), where either
    # branch may legitimately win; the documented kill switch restores the
    # behaviour this fence was written for.
    monkeypatch.setenv("HEDGE_RACE_MODE", "0")
    tools = [{"type": "function", "function": {"name": "ping", "parameters": {}}}]
    script.script(PRIMARY, [("sse", [chunk("sovereign branch", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker branch", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "urgent: do the thing"}],
        "stream": True, "hedge": True,
        "tools": tools, "tool_choice": "auto",
    })
    assert "sovereign branch" in _deltas(resp)
    sent = {c["url"]: c["json"] for c in script.calls}
    assert sent[PRIMARY]["tools"] == tools
    assert sent[PRIMARY]["tool_choice"] == "auto"
    assert sent[WORKER]["tools"] == tools
    assert sent[WORKER]["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# hedge-level tests (direct hedge_stream, MockTransport handler per case)
# ---------------------------------------------------------------------------
SOV = "http://sov.test/v1/chat/completions"
WRK = "http://wrk.test/v1/chat/completions"


def _hchunk(content=None, finish=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    ev = {"id": "x", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(ev)}\n\n"


def _run_hedge(handler, messages=None):
    import anyio

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    s = speculative_hedge.SETTINGS
    s.sovereign_url, s.sovereign_key, s.sovereign_model = SOV, "", "primary"
    s.worker_url, s.worker_key, s.worker_model = WRK, "none", "worker"
    s.commit_tokens = 10
    s.live_reasoning = True
    s.retry_base_delay = 0.0

    async def collect():
        out = []
        async for c in speculative_hedge.hedge_stream(
            messages or [{"role": "user", "content": "hi"}], client=client
        ):
            out.append(c.decode())
        return out

    return anyio.run(collect)


def _hedge_text(chunks):
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
        if isinstance(ev, dict) and "error" in ev:
            out.append(f"<error:{ev['error']}>")
            continue
        d = {}
        if isinstance(ev, dict):
            raw = ev.get("choices")
            d = raw[0].get("delta") or {} if isinstance(raw, list) and raw else {}
        if d.get("content"):
            out.append(d["content"])
    return "".join(out)


# --- 5. hedge: non-dict SSE payload is skipped, not fatal ------------------
def test_hedge_non_dict_sse_event_does_not_kill_the_stream():
    def handler(request):
        if request.url.host == "sov.test":
            body = ("data: [1, 2, 3]\n\n"          # bare JSON list
                    + 'data: "just a string"\n\n'   # bare JSON string
                    + 'data: {"choices": 5}\n\n'    # non-list choices
                    + _hchunk("clean answer", finish="stop")
                    + "data: [DONE]\n\n")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=body.encode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=(_hchunk("worker answer", finish="stop")
                                       + "data: [DONE]\n\n").encode())

    text = _hedge_text(_run_hedge(handler))
    assert "clean answer" in text, "one malformed event must not kill the race"
    assert "worker answer" not in text


# --- 6. hedge: retry_same (408/429) is retried, never a worker divert -----
def test_hedge_sovereign_retry_status_never_diverts_to_worker():
    s = speculative_hedge.SETTINGS

    def handler(request):
        if request.url.host == "sov.test":
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=(_hchunk("worker answer", finish="stop")
                                       + "data: [DONE]\n\n").encode())

    s.max_attempts = 1  # exhausted immediately
    out = _hedge_text(_run_hedge(handler))
    assert "<error:" in out and "retry_same" in out  # disclosed with the class
    assert "worker answer" not in out                  # ...and NOT a worker divert

    # the retry actually happens: 429, 429, then ok -> the sovereign commits
    seq = {"n": 0}

    def handler2(request):
        if request.url.host == "sov.test":
            seq["n"] += 1
            if seq["n"] < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=(_hchunk("after retry", finish="stop")
                                           + "data: [DONE]\n\n").encode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=(_hchunk("worker answer", finish="stop")
                                       + "data: [DONE]\n\n").encode())

    s.max_attempts = 3
    out2 = _hedge_text(_run_hedge(handler2))
    assert seq["n"] == 3                    # retried the SAME provider twice
    assert "after retry" in out2            # ...and it answered
    assert "worker answer" not in out2


# --- 7. hedge: __all__ exports real names ---------------------------------
def test_star_import_exports_real_names():
    ns = {}
    exec("from speculative_hedge import *", ns)  # noqa: S102 - test-only
    assert "hedge_stream" in ns
    assert "SETTINGS" in ns
    assert "hedge_settings" not in ns  # the phantom name is gone

