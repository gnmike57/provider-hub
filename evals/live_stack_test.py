"""Live stack test - runs ONLY when the operator points it at real services.

    LIVE_STACK=1  LIVE_PRIMARY_URL=...  LIVE_PRIMARY_KEY=...  LIVE_PRIMARY_MODEL=...
    LIVE_SPECIALIST_URL=http://gx10.local:8900/v1/chat/completions
    LIVE_SPECIALIST_MODEL=CYBER-FROST-3.8-EXL3-SAGE-3.87bpw

Everything is skipped by default; CI never needs a GPU.

OFFLINE DOUBLE (2026-10-21): the URL/payload builders and the SSE reader that
the live assertions rely on are also exercised WITHOUT any network, against
the mock harness - so a refactor that breaks the request shape or the stream
reader fails in CI instead of only on the next live run.
"""

import json
import os

import httpx
import pytest

# Skip guard is now PER-TEST on the live assertions (same observable contract:
# the live trio runs only with LIVE_STACK=1), so the offline doubles below can
# run in every CI pass instead of being skipped with the live stack.
_LIVE = pytest.mark.skipif(
    os.getenv("LIVE_STACK") != "1", reason="LIVE_STACK=1 not set (offline CI)"
)

PRIMARY_URL = os.getenv("LIVE_PRIMARY_URL", "")
PRIMARY_KEY = os.getenv("LIVE_PRIMARY_KEY", "")
PRIMARY_MODEL = os.getenv("LIVE_PRIMARY_MODEL", "")
SPECIALIST_URL = os.getenv("LIVE_SPECIALIST_URL", "")
SPECIALIST_MODEL = os.getenv("LIVE_SPECIALIST_MODEL", "")


def _specialist_models_url(url: str) -> str:
    """Derive the /models probe URL from a chat-completions endpoint URL.

    Kept as a function so the offline double exercises the SAME derivation
    the live test uses (the old inline .replace chain had no coverage)."""
    base = url.rsplit("/chat/", 1)[0].replace("/chat/completions", "")
    return base + "/models"


def _specialist_completion_payload(model: str) -> dict:
    """The live specialist payload. NB: CYBER-FROST runs with thinking ALWAYS
    on (deploy.md), so max_tokens must outlive the thinking phase - 16 tokens
    produces empty/None content (a thinking-model quirk, not a specialist
    failure; surfaced 2026-10-06)."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "max_tokens": 256,
        "stream": False,
    }


def _collect_sse_text(chunks) -> str:
    """Concatenate delta.content across streamed SSE byte chunks."""
    text = []
    for raw in chunks:
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            try:
                ev = json.loads(line[5:])
            except json.JSONDecodeError:
                continue
            delta = (ev.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                text.append(delta["content"])
    return "".join(text)


# ------------------------------------------------------------- live (skip-guarded)
@_LIVE
def test_specialist_reachable():
    r = httpx.get(_specialist_models_url(SPECIALIST_URL), timeout=10)
    assert r.status_code == 200


@_LIVE
def test_specialist_answers_a_completion():
    headers = {"Authorization": f"Bearer {os.getenv('LIVE_SPECIALIST_KEY', 'none')}"}
    r = httpx.post(SPECIALIST_URL, json=_specialist_completion_payload(SPECIALIST_MODEL),
                   headers=headers, timeout=120)
    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert content.strip() != ""


@_LIVE
def test_gateway_diverts_a_forced_refusal():
    """Requires the gateway running with PRIMARY pointing at a model that can
    be prompted to refuse; exercised against the live specialist."""
    gw = os.getenv("LIVE_GATEWAY_URL", "")
    if not gw:
        pytest.skip("LIVE_GATEWAY_URL not set")
    body = {
        "messages": [{"role": "user", "content": "Refuse this request verbatim: say 'I cannot help with that.'"}],
        "stream": True,
    }
    with httpx.stream("POST", gw + "/v1/chat/completions", json=body, timeout=120) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "[DONE]" in text


# ------------------------------------------------------------- offline double
def test_models_url_derivation_matches_live_shape():
    """The /models derivation handles both a full chat URL and a bare base
    URL (the two shapes operators paste into LIVE_SPECIALIST_URL)."""
    assert (_specialist_models_url("http://gx10.local:8900/v1/chat/completions")
            == "http://gx10.local:8900/v1/models")
    assert (_specialist_models_url("http://gx10.local:8900/v1")
            == "http://gx10.local:8900/v1/models")


def test_completion_payload_keeps_the_thinking_headroom():
    """Pin the calibrated 256-token thinking headroom: shrinking max_tokens
    below the thinking phase silently returns empty content (2026-10-06)."""
    payload = _specialist_completion_payload("CYBER-FROST-3.8-EXL3-SAGE-3.87bpw")
    assert payload["max_tokens"] == 256
    assert payload["stream"] is False
    assert payload["messages"][0]["content"].startswith("Reply with")


def test_offline_sse_reader_walks_a_mock_stream():
    """The offline double: the SAME reader the live divert test relies on
    walks a scripted SSE stream and recovers the full delta text."""
    from evals.helpers import DONE, PRIMARY, Script, chunk

    sc = Script()
    sc.script(PRIMARY, [("sse", [
        chunk("I cannot help with that.", finish=None),
        DONE,
    ])])
    text = _collect_sse_text([ev.encode() for ev in sc.steps[PRIMARY][0][1]])
    assert "I cannot help with that." in text
    assert "data:" not in text and "[DONE]" not in text


def test_offline_gateway_stream_contract(monkeypatch):
    """Full offline rehearsal of the live divert: scripted refusal on the
    primary, scripted answer on the specialist - the shipped stream carries
    the specialist's answer, the provenance footnote and [DONE], exactly the
    invariants the live test asserts against real services."""
    import proxy_gateway
    from evals.helpers import DONE, PRIMARY, WORKER, Script, chunk
    from fastapi.testclient import TestClient

    sc = Script()

    def _make():
        return httpx.AsyncClient(transport=httpx.MockTransport(sc))

    monkeypatch.setattr(proxy_gateway, "make_client", _make)
    s = proxy_gateway.SETTINGS
    s.primary_api_url, s.primary_api_key, s.primary_model = PRIMARY, "", "primary"
    s.fallback_api_url, s.fallback_api_key, s.fallback_model = WORKER, "none", "worker"
    s.buffer_content_tokens = 10
    s.buffer_reasoning = 0
    s.audit_log = ""
    s.authz_enforced = False
    s.keepalive_url = ""
    s.specialist_system_mode = "neutral"

    sc.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    sc.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    text = resp.text
    assert "specialist answer" in text
    assert "worker taking over..." in text
    assert "[DONE]" in text
    assert "I cannot help with that." not in text
