"""Streaming gateway end-to-end over mock upstreams (ring-buffer states)."""

import json

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


def test_malformed_json_body_is_400_not_500(gw):
    """F5 (found by the P4 failure-injection matrix): a malformed body raised
    inside FastAPI and surfaced as a bare 500 'Internal Server Error'."""
    resp = gw.post("/v1/chat/completions", content=b"{not json at all",
                   headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert "invalid JSON body" in resp.text


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
    assert "specialist unavailable (503)" in text
    assert proxy_gateway._METRICS["fallback_errors_total"] >= 3


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


