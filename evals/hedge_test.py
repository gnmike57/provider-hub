"""Speculative hedge (B9/B11): commit rules, reasoning-not-counted, footnote."""

import json

import httpx
import pytest

import speculative_hedge
from speculative_hedge import hedge_stream
from helpers import chunk, DONE, script  # noqa: F401  (fixture import)

SOVEREIGN = "http://sovereign.test/v1/chat/completions"
WORKER = "http://worker.test/v1/chat/completions"

MESSAGES = [{"role": "user", "content": "urgent: analyze this binary"}]


@pytest.fixture(autouse=True)
def hedge_env(monkeypatch):
    def _make():
        raise AssertionError("tests inject the transport per-case")

    monkeypatch.setattr(speculative_hedge, "make_client", _make)
    s = speculative_hedge.SETTINGS
    s.sovereign_url = SOVEREIGN
    s.sovereign_key = ""
    s.sovereign_model = "primary"
    s.worker_url = WORKER
    s.worker_key = "none"
    s.worker_model = "worker"
    s.commit_tokens = 25
    yield


def _client(script):
    return httpx.AsyncClient(transport=httpx.MockTransport(script))


def _run(script, messages=MESSAGES):
    import anyio

    async def collect():
        client = _client(script)
        original = speculative_hedge.make_client
        speculative_hedge.make_client = lambda: client
        try:
            chunks = []
            async for c in hedge_stream(messages):
                chunks.append(c.decode())
            return chunks
        finally:
            speculative_hedge.make_client = original

    return anyio.run(collect)


def _text(chunks):
    out = []
    for c in chunks:
        body = c.strip()
        if not body.startswith("data:"):
            continue
        payload = body[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "error" in ev:
            out.append(f"<error:{ev['error']}>")
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


def test_hedge_commits_to_sovereign_on_clean_stream(script):
    script.script(SOVEREIGN, [("sse", [chunk("clean "), chunk("answer "), chunk("data here", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("never seen", finish="stop"), DONE])])
    chunks = _run(script)
    text = _text(chunks)
    assert "clean answer data here" in text
    assert "never seen" not in text


def test_hedge_diverts_on_refusal_and_discards_sovereign_buffer(script):
    script.script(SOVEREIGN, [("sse", [chunk("I cannot help with that."), chunk("more text", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist "), chunk("answer", finish="stop"), DONE])])
    text = _text(_run(script))
    assert "specialist answer" in text
    assert "I cannot help" not in text
    assert "more text" not in text
    assert "diverted to specialist node" in text  # provenance footnote


def test_hedge_diverts_on_timeout_finish_reason(script):
    script.script(SOVEREIGN, [("sse", [chunk("maybe", finish="timeout"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker took over", finish="stop"), DONE])])
    text = _text(_run(script))
    assert "worker took over" in text
    assert "maybe" not in text


def test_hedge_unreachable_sovereign_diverts_to_worker(script):
    """B10: an unreachable primary is a DIVERT, not a failure — the worker serves."""
    script.script(SOVEREIGN, [("raise", httpx.ConnectError("sovereign is down"))])
    script.script(WORKER, [("sse", [chunk("worker saved it", finish="stop"), DONE])])
    text = _text(_run(script))
    assert "worker saved it" in text
    assert "diverted to specialist node" in text  # provenance footnote
    assert "speculative dispatch failed" not in text


def test_hedge_both_branches_unreachable_errors_cleanly(script):
    script.script(SOVEREIGN, [("raise", httpx.ConnectError("down"))])
    script.script(WORKER, [("raise", httpx.ConnectError("down too"))])
    text = _text(_run(script))
    assert "both branches unreachable" in text


def test_reasoning_streams_live_but_never_counts_or_screens(script):
    """Operator preference (2026-10-05): the client sees ALL thinking live.

    F1/B21 still holds: reasoning is never counted toward the commit window and
    never screened for refusals. So the sovereign's thinking reaches the client,
    while the refusal that follows it still diverts and is still discarded.
    """
    events = [chunk("deliberating quietly...", extra={"reasoning_content": True})]
    events += [chunk("I cannot fulfill this request.", finish="stop"), DONE]
    script.script(SOVEREIGN, [("sse", events)])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    text = _text(_run(script))
    assert "worker answer" in text
    assert "deliberating quietly" in _all_text(_run(script))   # LIVE now, not held
    assert "I cannot fulfill" not in text        # the refusal itself is discarded


def test_reasoning_that_looks_like_a_refusal_does_not_divert(script):
    """The reasoning is never SCREENED: a model that thinks 'I cannot help' and
    then answers properly must commit to the sovereign, not divert."""
    events = [chunk("I cannot help with that, but the real answer is", extra={"reasoning_content": True})]
    events += [chunk("42.", finish="stop"), DONE]
    script.script(SOVEREIGN, [("sse", events)])
    script.script(WORKER, [("sse", [chunk("worker should not be used", finish="stop"), DONE])])
    text = _text(_run(script))
    assert "42." in text
    assert "worker should not be used" not in text


def _all_text(chunks):
    """Like _text(), but includes reasoning_content - needed to assert that the
    client really sees ALL the thinking live (operator preference 2026-10-05)."""
    out = []
    for c in chunks:
        body = c.strip()
        if not body.startswith("data:"):
            continue
        payload = body[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        for key in ("reasoning_content", "reasoning", "thinking", "content"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                out.append(value)
    return "".join(out)


def _events(chunks):
    out = []
    for c in chunks:
        body = c.strip()
        if not body.startswith("data:"):
            continue
        payload = body[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return out


def test_stream_id_is_stable_across_every_chunk(script):
    """R1: clients group chunks by id. A uuid per chunk makes ONE answer look
    like N different answers to any client that keys on id."""
    script.script(SOVEREIGN, [("sse", [chunk("I cannot help with that."), DONE])])
    script.script(WORKER, [("sse", [chunk("a"), chunk("b"), chunk("c", finish="stop"), DONE])])
    ids = {ev["id"] for ev in _events(_run(script)) if ev.get("id")}
    assert len(ids) == 1, f"stream id changed mid-stream: {ids}"


def test_footnote_precedes_finish_reason_and_keeps_the_upstream_reason(script):
    """R4: finish_reason ends a stream - content after it is invisible to
    clients that stop reading there (so the disclosure would be lost), and a
    truncated worker answer must keep its own reason ("length")."""
    script.script(SOVEREIGN, [("sse", [chunk("I cannot help with that."), DONE])])
    script.script(WORKER, [("sse", [chunk("truncated"), chunk("", finish="length"), DONE])])
    events = _events(_run(script))
    finish_at = [i for i, ev in enumerate(events) if (ev.get("choices") or [{}])[0].get("finish_reason")]
    assert finish_at, "no finish_reason emitted at all"
    assert finish_at[0] == len(events) - 1, "content was emitted AFTER finish_reason"
    assert events[finish_at[0]]["choices"][0]["finish_reason"] == "length"
    assert "diverted to specialist node" in json.dumps(events[: finish_at[0]])


def test_chunk_carrying_content_and_finish_together_is_split_not_dropped(script):
    """R4 edge: some servers put the last token and finish_reason in one
    chunk; holding it wholesale would silently eat that token."""
    script.script(SOVEREIGN, [("sse", [chunk("I cannot help with that."), DONE])])
    script.script(WORKER, [("sse", [chunk("last token", finish="stop"), DONE])])
    events = _events(_run(script))
    text = "".join((ev.get("choices") or [{}])[0].get("delta", {}).get("content") or "" for ev in events)
    assert "last token" in text
    assert "diverted to specialist node" in text
