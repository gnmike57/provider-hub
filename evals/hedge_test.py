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

    # deliberation streams long before any content: must NOT commit the hedge
    # to the sovereign, and on the worker path the held reasoning is discarded.
    events = [chunk("deliberating quietly...", extra={"reasoning_content": True})]
    events += [chunk("I cannot fulfill this request.", finish="stop"), DONE]
    script.script(SOVEREIGN, [("sse", events)])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    text = _text(_run(script))
    assert "worker answer" in text
    assert "deliberating quietly" not in text
    assert "I cannot fulfill" not in text
