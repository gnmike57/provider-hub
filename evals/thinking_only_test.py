"""Thinking-only responses are re-dispatched to the worker instead of being
delivered as "just thinking".

Found live 2026-10-07 on the DeepFrost endpoint (9311): the thinking-on
primaries (deepseek-v4.1-flash / glm-5.3-flash) answer a short prompt with a
hidden reasoning block and stop writing text, so the client got an answer that
said nothing but "thinking". Same class as the empty-sovereign rule: the
gateway now detects reasoning-without-content at the end of the stream and
re-dispatches to the worker with a footnote.
"""

import proxy_gateway
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401 (fixture import)


def _thinking_only_chunk(text="thinking..."):
    return chunk(extra={"reasoning_content": text}, finish=None)


def test_thinking_only_is_re_routed_to_the_worker(script):
    script.script(PRIMARY, [("sse", [_thinking_only_chunk(), DONE])])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "DeepFrost v4.1",
                             "messages": [{"role": "user", "content": "hey"}],
                             "max_tokens": 300, "max_completion_tokens": 300})
    assert resp.status_code == 200
    assert "worker answer" in resp.text, "thinking-only must not be the answer"
    assert "diverted to specialist node" in resp.text, "divert must be disclosed"


def test_thinking_only_at_done_is_re_routed(script):
    """Same defect at the [DONE] commit site (no finish_reason on the last
    delta): the stream ends with reasoning only and [DONE]."""
    script.script(PRIMARY, [("sse", [_thinking_only_chunk("reasoning only"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker reply", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "hey"}],
                             "max_tokens": 300, "max_completion_tokens": 300})
    assert resp.status_code == 200
    assert "worker reply" in resp.text


def test_reasoning_plus_content_still_commits(script):
    """A real answer that includes a reasoning block is not thinking-only."""
    script.script(PRIMARY, [("sse", [_thinking_only_chunk("thinking here "),
                                     chunk("clean answer", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("never seen", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "hi"}],
                             "max_tokens": 300, "max_completion_tokens": 300})
    assert resp.status_code == 200
    assert "clean answer" in resp.text
    assert "never seen" not in resp.text
    assert "diverted to specialist node" not in resp.text


def test_content_only_without_reasoning_still_commits(script):
    script.script(PRIMARY, [("sse", [chunk("plain answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "hi"}],
                             "max_tokens": 300, "max_completion_tokens": 300})
    assert resp.status_code == 200
    assert "plain answer" in resp.text
    assert "diverted to specialist node" not in resp.text
