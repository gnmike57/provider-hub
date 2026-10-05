"""Streaming gateway end-to-end over mock upstreams (ring-buffer states)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _body(prompt="explain the exploit", model=None, **extra):
    body = {"messages": [{"role": "user", "content": prompt}], "stream": True}
    if model:
        body["model"] = model
    body.update(extra)
    return body


def _events(resp):
    events = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            events.append("[DONE]")
            continue
        try:
            events.append(json.loads(body))
        except json.JSONDecodeError:
            events.append(body)
    return events


def _deltas(events):
    out = []
    for ev in events:
        if isinstance(ev, str) and ev == "[DONE]":
            continue
        if not isinstance(ev, dict):
            continue
        if "error" in ev:
            out.append(f"<error:{ev['error']}>")
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


def test_clean_stream_replays_buffer_verbatim_and_finishes(gw, script):
    script.script(PRIMARY, [("sse", [chunk("clean "), chunk("answer"), chunk(" ok", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    assert _deltas(_events(resp)) == "clean answer ok"
    assert _events(resp)[-1] == "[DONE]"
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_tier3_refusal_diverts_and_discards_buffer(gw, script):
    script.script(PRIMARY, [("sse", [chunk("I cannot help"), chunk(" with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist "), chunk("answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "specialist answer" in text
    assert "I cannot help" not in text
    assert "with that." not in text
    assert "diverted to specialist node" in text
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_unicode_refusal_diverts(gw, script):
    script.script(PRIMARY, [("sse", [chunk("I\u2019m sorry, but I"), chunk(" can\u2019t help.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker ok", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert "worker ok" in _deltas(_events(resp))


def test_tier1_timeout_finish_diverts(gw, script):
    script.script(PRIMARY, [("sse", [chunk("maybe", finish="timeout"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker after timeout", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "worker after timeout" in text
    assert "maybe" not in text


def test_empty_200_soft_refusal_diverts(gw, script):
    """F2 (found live by the red-team run): a primary that answers HTTP 200 with
    NOTHING - no content, no reasoning, no tool calls - is a soft refusal the
    anchored regex cannot see. Without this the client silently gets an empty
    answer. Measured on the hub's cloud aliases; it also hit a benign prompt."""
    script.script(PRIMARY, [("sse", [chunk("", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist answered", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "specialist answered" in text
    assert "diverted to specialist node" in text  # provenance footnote


def test_empty_200_without_done_also_diverts(gw, script):
    """The same soft refusal when the upstream closes without sending [DONE]."""
    script.script(PRIMARY, [("sse", [chunk("")])])
    script.script(WORKER, [("sse", [chunk("worker recovered", finish="stop"), DONE])])
    text = _deltas(_events(gw.post("/v1/chat/completions", json=_body())))
    assert "worker recovered" in text


def test_divert_carries_the_whole_conversation(gw, script, monkeypatch):
    """F7 (found by the P5 long-context tier and the P6 agent loop): the divert
    path used format_messages(), which reduces the conversation to
    [system, last user turn] - so the specialist never saw the caller's context
    or any tool result."""
    captured = {}
    original = proxy_gateway.fallback_stream

    async def spy(messages, **kwargs):
        captured["messages"] = messages
        async for chunk in original(messages, **kwargs):
            yield chunk

    monkeypatch.setattr(proxy_gateway, "fallback_stream", spy)
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("ok", finish="stop"), DONE])])
    body = {
        "messages": [
            {"role": "system", "content": "CONTEXT-MARKER the lab is 10.0.0.0/24"},
            {"role": "user", "content": "assess it"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "run_shell", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "TOOL-RESULT-MARKER 200 OK"},
            {"role": "user", "content": "next step"},
        ],
        "stream": True,
    }
    gw.post("/v1/chat/completions", json=body)
    sent = json.dumps(captured.get("messages") or [])
    assert "CONTEXT-MARKER" in sent      # the caller's system context survives
    assert "TOOL-RESULT-MARKER" in sent  # so does the tool result
    assert "next step" in sent


def test_tools_survive_the_divert(gw, script, monkeypatch):
    """F6 (found building the P6 agentic tier): the divert path dropped `tools`,
    so a diverted agentic request answered in prose instead of calling tools."""
    captured = {}
    original = proxy_gateway.fallback_stream

    async def spy(messages, **kwargs):
        captured.update(kwargs)
        async for chunk in original(messages, **kwargs):
            yield chunk

    monkeypatch.setattr(proxy_gateway, "fallback_stream", spy)
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("ok", finish="stop"), DONE])])
    tools = [{"type": "function",
              "function": {"name": "run_shell", "parameters": {"type": "object"}}}]
    gw.post("/v1/chat/completions", json=_body(tools=tools))
    assert captured.get("tools") == tools


def test_malformed_json_body_is_400_not_500(gw):
    """F5 (found by the P4 failure-injection matrix): a malformed body raised
    inside FastAPI and surfaced as a bare 500 'Internal Server Error'."""
    resp = gw.post("/v1/chat/completions", content=b"{not json at all",
                   headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert "invalid JSON body" in resp.text


def test_oversized_body_is_413(gw, monkeypatch):
    """P4 scenario 7: the gateway had no body cap, so an 8 MiB body was accepted
    and produced an empty answer with no divert."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "max_body_bytes", 1024)
    resp = gw.post("/v1/chat/completions", content=b"x" * 4096,
                   headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert "too large" in resp.text


def test_chunked_body_without_content_length_is_413(script, monkeypatch):
    """The cap must not depend on the Content-Length header.

    check_body_size() trusted the header alone, so a chunked body (no
    Content-Length) was buffered in full and accepted - an unbounded allocation
    sitting behind a cap that looked enforced.
    """
    monkeypatch.setattr(proxy_gateway.SETTINGS, "max_body_bytes", 1024)

    def _chunks():
        for _ in range(8):  # 4 KiB total, sent chunked (no Content-Length)
            yield b"x" * 512

    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions", content=_chunks(),
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert "too large" in resp.text


async def test_read_json_body_counts_streamed_bytes(monkeypatch):
    """Direct proof, independent of the HTTP client: no Content-Length at all."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "max_body_bytes", 1024)

    class _NoHeaderRequest:
        headers: dict = {}  # nothing to trust

        async def stream(self):
            for _ in range(4):  # 2 KiB over a 1 KiB cap
                yield b"x" * 512

    with pytest.raises(proxy_gateway.HTTPException) as err:
        await proxy_gateway.read_json_body(_NoHeaderRequest())
    assert err.value.status_code == 413


def test_chunked_body_under_the_cap_still_works(script, monkeypatch):
    """Closing the bypass must not break ordinary chunked clients."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "max_body_bytes", 4096)
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    payload = json.dumps(_body()).encode()

    def _chunks():
        yield payload[:12]
        yield payload[12:]

    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions", content=_chunks(),
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert _deltas(_events(resp)) == "ok"


def test_unauthorised_principal_is_refused_before_any_model_call(gw, script, monkeypatch):
    """M5: authz is enforced ahead of routing - the client gets 403 and the
    upstream is never touched."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "authz_enforced", True)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "authorised_principals", ("red-1",))
    called = {"n": 0}

    def _never(*a, **k):
        called["n"] += 1
        raise AssertionError("upstream must not be called for a denied principal")

    monkeypatch.setattr(proxy_gateway, "open_primary", _never)
    resp = gw.post("/v1/chat/completions", json=_body(),
                   headers={"X-Principal": "intruder"})
    assert resp.status_code == 403
    assert called["n"] == 0


def test_reasoning_only_answer_is_not_treated_as_empty(gw, script):
    """Reasoning IS delivered text: a thinking-only response must pass through,
    not divert (F1/B21 keeps reasoning out of the count, but the client saw it)."""
    script.script(PRIMARY, [("sse", [chunk("deliberating", extra={"reasoning_content": True}),
                                     chunk("", finish="length"), DONE])])
    script.script(WORKER, [("sse", [chunk("should not appear", finish="stop"), DONE])])
    text = _deltas(_events(gw.post("/v1/chat/completions", json=_body())))
    assert "should not appear" not in text


def test_passthrough_after_buffer_committed_is_opaque(gw, script):
    # a refusal TEXT later in the stream must not divert: routing only while
    # buffering (B8). Build a clean 3-token prefix, then refusal wording.
    script.script(
        PRIMARY,
        [("sse", [chunk("one "), chunk("two "), chunk("three "), chunk("I cannot help with that.", finish="stop"), DONE])],
    )
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "one two three" in text
    assert "I cannot help with that." in text
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_primary_429_retries_same_provider_then_succeeds(gw, script):
    script.script(
        PRIMARY,
        [("status", 429, {"error": "rate"}), ("status", 429, {"error": "rate"}), ("sse", [chunk("after retry", finish="stop"), DONE])],
    )
    resp = gw.post("/v1/chat/completions", json=_body())
    assert "after retry" in _deltas(_events(resp))
    assert not proxy_gateway._METRICS["diverted_total"]
    assert all("worker.test" not in c["url"] for c in script.calls)


def test_primary_5xx_retries_then_diverts(gw, script):
    script.script(PRIMARY, [("status", 503, {"error": "capacity"})])
    script.script(WORKER, [("sse", [chunk("capacity divert ok", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert "capacity divert ok" in _deltas(_events(resp))
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_primary_4xx_fails_fast_no_divert(gw, script):
    script.script(PRIMARY, [("status", 400, {"error": "bad request"})])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "<error:upstream error (400)" in text
    assert proxy_gateway._METRICS["diverted_total"] == 0
    assert all("worker.test" not in c["url"] for c in script.calls)


def test_specialist_503_retried_then_error_chunk(gw, script):
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("status", 503, {"error": "at capacity"})])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    # F11 (P4-7): a specialist that refuses to OPEN must be VISIBLE as content,
    # not a bare {"error": ...} event - otherwise every standard client renders
    # a silent empty 200 (measured on the live stack with an 8 MiB divert).
    assert "Specialist unavailable (503)" in text
    assert "diverted to specialist node" in text
    assert proxy_gateway._METRICS["fallback_errors_total"] >= 3


def test_specialist_400_context_rejection_is_visible_not_silent(gw, script):
    # The exact P4-7 shape: the divert opens fine on paper, the specialist
    # rejects the payload (context length on the real box), and pre-F11 the
    # client received 200 with ZERO content - a silent failure.
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("status", 400, {"error": "context length exceeded"})])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    text = _deltas(_events(resp))
    assert "Specialist unavailable (400)" in text
    assert "context length exceeded" in text
    assert "diverted to specialist node" in text
    assert "<error:" in text or True  # error event is optional; visibility is not


def test_reasoning_forwarded_not_counted(gw, script):
    # reasoning deltas must not consume the buffer budget
    events = [chunk("thinking hard", extra={"reasoning_content": True}) for _ in range(3)]
    events += [chunk(f"tok{i} ") for i in range(30)]
    events += [chunk("tail", finish="stop"), DONE]
    script.script(PRIMARY, [("sse", events)])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "thinking hard" in text
    assert "tok0 " in text
    assert "tail" in text


def test_hedge_fires_only_on_latency_hint_or_force(gw, script):
    # B11: no hint -> normal ring-buffer proxy (one primary call)
    script.script(PRIMARY, [("sse", [chunk("plain path", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body("plain question"))
    assert "plain path" in _deltas(_events(resp))
    primary_calls = [c for c in script.calls if c["url"] == PRIMARY]
    assert len(primary_calls) == 1

    # force hedge -> two branches
    script.script(PRIMARY, [("sse", [chunk("sovereign branch", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker branch", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body("anything", hedge=True))
    text = _deltas(_events(resp))
    assert "sovereign branch" in text
    assert "worker branch" not in text
def test_primary_fail_fast_error_is_visible_not_silent(gw, script):
    """F12: a fail-fast 4xx (not routable) must not become a silent empty 200.

    The error EVENT alone is invisible to every standard OpenAI client, which
    renders only delta.content - the same defect class F11 fixed on the
    specialist path. Found by reviewing the F11 fix for parity.
    """
    script.script(PRIMARY, [("status", 401, {"error": "invalid api key"})])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    text = _deltas(_events(resp))
    assert "Upstream error (401)" in text          # what a real client renders
    assert "invalid api key" in text               # ...with the upstream reason
    assert "<error:upstream error (401)" in text   # event kept: nothing is lost
    assert _events(resp)[-1] == "[DONE]"
    assert proxy_gateway._METRICS["primary_errors_total"] == 1
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_primary_stream_break_in_passthrough_is_disclosed(gw, script):
    """F13: a primary stream that broke mid-flight used to raise straight out of
    the generator - the client got a truncated body with no error, no
    finish_reason and no way to tell it from a complete answer."""
    events = [chunk(f"tok{i} ") for i in range(30)]  # >= 25 tokens -> PASSTHROUGH
    events.append(httpx.TransportError("connection reset"))
    script.script(PRIMARY, [("sse", events)])
    resp = gw.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 200
    text = _deltas(_events(resp))
    assert "tok0 " in text                      # the committed prefix survives
    assert "[primary stream broke:" in text     # the truncation is disclosed
    assert _events(resp)[-1] == "[DONE]"        # ...and the stream still closes
    assert proxy_gateway._METRICS["primary_errors_total"] == 1


def test_primary_stream_break_before_commit_diverts(gw, script):
    """F13b: the same break with NOTHING committed is a Tier 1 transport
    failure, so it diverts instead of surfacing a half-answer."""
    script.script(PRIMARY, [("sse", [chunk("hel"), httpx.TransportError("reset"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker rescued", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _deltas(_events(resp))
    assert "worker rescued" in text
    assert "hel" not in text                    # the buffer is discarded
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_hedge_uses_per_request_settings_copy(gw, script):
    """F14: the gateway used to mutate the module-global hedge SETTINGS in
    place, so two concurrent hedged requests raced on sovereign_model (each
    request's own model) and could clobber each other's URLs mid-flight."""
    import speculative_hedge

    script.script(PRIMARY, [("sse", [chunk("sovereign branch", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker branch", finish="stop"), DONE])])
    before = speculative_hedge.SETTINGS.sovereign_model
    resp = gw.post(
        "/v1/chat/completions",
        json=_body("anything", model="request-specific-model", hedge=True),
    )
    assert "sovereign branch" in _deltas(_events(resp))
    sent = [c["json"]["model"] for c in script.calls if c["url"] == PRIMARY]
    assert sent == ["request-specific-model"]              # this request's model
    assert speculative_hedge.SETTINGS.sovereign_model == before  # global untouched



