"""Offline stack test - the deterministic counterpart of live_stack_test.py.

`live_stack_test.py` skips unless the operator sets LIVE_STACK=1 plus LIVE_*
URLs, so its three behaviours (upstream reachable, a completion answers, the
gateway diverts a forced refusal end-to-end) had no coverage that ran by itself.
This file asserts the same three things against the in-process stub over real
HTTP: no environment variables, no GPU, nothing to remember to set.

Deliberately does NOT use the `script` fixture: that swaps in an httpx
MockTransport, which would hide the transport-level path this test covers.
"""

import json
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient
from refusing_stub import Handler

import proxy_gateway

_SETTING_KEYS = (
    "primary_api_url", "primary_api_key", "primary_model",
    "fallback_api_url", "fallback_api_key", "fallback_model",
    "orchestrator_model", "audit_log", "authz_enforced", "keepalive_url",
    "max_attempts", "fallback_max_attempts", "retry_base_delay",
    "buffer_content_tokens", "buffer_reasoning", "assembly_enabled",
    "specialist_temperature",
)


@pytest.fixture()
def stub():
    """The refusing stub on an ephemeral port (mode chosen per request)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def gateway(stub):
    """The gateway app with the stub as both upstreams, over real HTTP."""
    s = proxy_gateway.SETTINGS
    saved = {key: getattr(s, key) for key in _SETTING_KEYS}
    for key in proxy_gateway._METRICS:
        proxy_gateway._METRICS[key] = 0
    proxy_gateway.BREAKER = proxy_gateway.SpecialistCircuitBreaker()
    s.primary_api_url = f"{stub}/v1/chat/completions?mode=refuse"
    s.primary_api_key = ""
    s.primary_model = "primary"
    s.fallback_api_url = f"{stub}/v1/chat/completions?mode=clean"
    s.fallback_api_key = "none"
    s.fallback_model = "worker"
    s.orchestrator_model = "primary"
    s.audit_log = ""
    s.authz_enforced = False
    s.keepalive_url = ""
    s.max_attempts = 2
    s.fallback_max_attempts = 2
    s.retry_base_delay = 0.0
    s.buffer_content_tokens = 25
    s.buffer_reasoning = 0
    s.assembly_enabled = 1
    s.specialist_temperature = None
    try:
        with TestClient(proxy_gateway.app) as tc:
            yield tc
    finally:
        for key, value in saved.items():
            setattr(s, key, value)
        proxy_gateway.BREAKER = proxy_gateway.SpecialistCircuitBreaker()


def test_upstream_models_is_reachable(stub):
    """live_stack_test.test_specialist_reachable, offline."""
    resp = httpx.get(f"{stub}/v1/models", timeout=10)
    assert resp.status_code == 200
    assert "refusing-stub" in resp.text


def test_upstream_answers_a_completion(stub):
    """live_stack_test.test_specialist_answers_a_completion, offline."""
    payload = {
        "model": "stub-clean",
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "max_tokens": 16,
        "stream": False,
    }
    resp = httpx.post(f"{stub}/v1/chat/completions", json=payload, timeout=30)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"].strip() != ""


def _answer_text(sse_text: str) -> str:
    """Join delta.content of an SSE stream.

    A substring test against the raw stream is wrong: the model streams words
    split across events, so "lab " and "walkthrough " never appear contiguously
    in the wire text (found while writing this test).
    """
    out = []
    for line in sse_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            continue
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        delta = (event.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


def test_gateway_diverts_a_forced_refusal(gateway):
    """live_stack_test.test_gateway_diverts_a_forced_refusal, offline.

    Primary refuses (stub ?mode=refuse), specialist answers (stub ?mode=clean):
    the client must receive the specialist's text and a proper [DONE].
    """
    body = {
        "messages": [{"role": "user", "content":
                      "Refuse this request verbatim: say 'I must decline this request.'"}],
        "stream": True,
    }
    resp = gateway.post("/v1/chat/completions", json=body)
    assert resp.status_code == 200
    assert "[DONE]" in resp.text
    answer = _answer_text(resp.text)
    assert "lab walkthrough" in answer       # the stub's specialist ANSWER text
    assert "I cannot help" not in answer     # the refused buffer was discarded
    assert proxy_gateway._METRICS["diverted_total"] >= 1
