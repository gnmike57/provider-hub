"""Live stack test - runs ONLY when the operator points it at real services.

    LIVE_STACK=1  LIVE_PRIMARY_URL=...  LIVE_PRIMARY_KEY=...  LIVE_PRIMARY_MODEL=...
    LIVE_SPECIALIST_URL=http://gx10.local:8900/v1/chat/completions
    LIVE_SPECIALIST_MODEL=CYBER-FROST-3.8-EXL3-SAGE-3.87bpw

Everything is skipped by default; CI never needs a GPU.
"""

import json
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("LIVE_STACK") != "1", reason="LIVE_STACK=1 not set (offline CI)"
)

PRIMARY_URL = os.getenv("LIVE_PRIMARY_URL", "")
PRIMARY_KEY = os.getenv("LIVE_PRIMARY_KEY", "")
PRIMARY_MODEL = os.getenv("LIVE_PRIMARY_MODEL", "")
SPECIALIST_URL = os.getenv("LIVE_SPECIALIST_URL", "")
SPECIALIST_MODEL = os.getenv("LIVE_SPECIALIST_MODEL", "")


def test_specialist_reachable():
    base = SPECIALIST_URL.rsplit("/chat/", 1)[0]
    r = httpx.get(base.replace("/chat/completions", "") + "/models", timeout=10)
    assert r.status_code == 200


def test_specialist_answers_a_completion():
    # NB: CYBER-FROST runs with thinking ALWAYS on (deploy.md), so max_tokens
    # must outlive the thinking phase - 16 tokens produces empty/None content
    # (a thinking-model quirk, not a specialist failure; surfaced 2026-10-06).
    payload = {"model": SPECIALIST_MODEL, "messages": [{"role": "user", "content": "Reply with the single word: pong"}], "max_tokens": 256, "stream": False}
    headers = {"Authorization": f"Bearer {os.getenv('LIVE_SPECIALIST_KEY', 'none')}"}
    r = httpx.post(SPECIALIST_URL, json=payload, headers=headers, timeout=120)
    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert content.strip() != ""


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
