"""Specialist binding resolution (operator requirement, 2026-10).

The refusal-interception specialist (worker slot) is configured using the
operator's Windows-env NANOGPT_API_KEY, so the uncensored credential lives in
the environment rather than being copied into another variable. The
SPECIALIST_API_URL/MODEL names override the historical FALLBACK_* ones.
"""

import proxy_gateway
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401


def test_key_resolution_precedence(monkeypatch):
    monkeypatch.setenv("SPECIALIST_API_KEY", "spec")
    monkeypatch.setenv("FALLBACK_API_KEY", "fb")
    monkeypatch.setenv("NANOGPT_API_KEY", "nano")
    assert proxy_gateway._specialist_key() == "spec"
    monkeypatch.delenv("SPECIALIST_API_KEY")
    assert proxy_gateway._specialist_key() == "fb"
    monkeypatch.delenv("FALLBACK_API_KEY")
    assert proxy_gateway._specialist_key() == "nano"
    monkeypatch.delenv("NANOGPT_API_KEY")
    assert proxy_gateway._specialist_key() == "none"


def test_nanogpt_key_becomes_the_specialist_key(monkeypatch):
    monkeypatch.delenv("SPECIALIST_API_KEY", raising=False)
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    monkeypatch.setenv("NANOGPT_API_KEY", "sk-nano-test")
    assert proxy_gateway.Settings().fallback_api_key == "sk-nano-test"


def test_worker_key_chain_mirrors_the_specialist(monkeypatch):
    """The hedge WORKER slot resolves its credential the SAME way as the
    divert SPECIALIST slot (2026-10-16). It used to stop at FALLBACK_API_KEY
    with a "none" default, so a NanoGPT-backed worker was handed "none" and
    sent no Authorization header - every hedge branch died with a 401 that the
    commit rule hid (the clean sovereign won and the worker buffer was dropped).
    The two slots now share SPECIALIST_API_KEY -> FALLBACK_API_KEY ->
    NANOGPT_API_KEY."""
    import speculative_hedge

    for var in ("WORKER_API_KEY", "SPECIALIST_API_KEY", "FALLBACK_API_KEY", "NANOGPT_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("NANOGPT_API_KEY", "sk-nano-test")
    assert speculative_hedge.HedgeSettings().worker_key == "sk-nano-test"

    monkeypatch.setenv("FALLBACK_API_KEY", "fb")
    assert speculative_hedge.HedgeSettings().worker_key == "fb"

    monkeypatch.setenv("SPECIALIST_API_KEY", "spec")
    assert speculative_hedge.HedgeSettings().worker_key == "spec"

    monkeypatch.setenv("WORKER_API_KEY", "worker-key")
    assert speculative_hedge.HedgeSettings().worker_key == "worker-key"

    monkeypatch.delenv("WORKER_API_KEY", raising=False)
    monkeypatch.delenv("SPECIALIST_API_KEY", raising=False)
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    assert speculative_hedge.HedgeSettings().worker_key == "none"


def test_worker_and_specialist_models_are_independent(monkeypatch):
    """Operator requirement (2026-10-16): WORKER = the mimo hedge branch and
    SPECIALIST = the v2-large divert target are DISTINCT NanoGPT models. The
    hedge reads WORKER_MODEL; the gateway reads SPECIALIST_MODEL - so the two
    slots must not collapse onto each other."""
    import speculative_hedge

    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    monkeypatch.setenv("SPECIALIST_MODEL", "abliteration-ai/abliterated-model-large-v2")
    monkeypatch.setenv("WORKER_MODEL", "xiaomi/mimo-v2.6-flash-abliterated")
    assert proxy_gateway.Settings().fallback_model == "abliteration-ai/abliterated-model-large-v2"
    assert speculative_hedge.HedgeSettings().worker_model == "xiaomi/mimo-v2.6-flash-abliterated"


def test_specialist_url_and_model_override_fallback(monkeypatch):
    monkeypatch.setenv("SPECIALIST_API_URL", "https://nano-gpt.com/api/v1/chat/completions")
    monkeypatch.setenv("SPECIALIST_MODEL", "abliteration-ai/abliterated-model-large-v2")
    s = proxy_gateway.Settings()
    assert s.fallback_api_url == "https://nano-gpt.com/api/v1/chat/completions"
    assert s.fallback_model == "abliteration-ai/abliterated-model-large-v2"


def test_fallback_names_still_win_when_specialist_unset(monkeypatch):
    monkeypatch.delenv("SPECIALIST_API_URL", raising=False)
    monkeypatch.delenv("SPECIALIST_MODEL", raising=False)
    monkeypatch.setenv("FALLBACK_API_URL", "http://hub.local:4000/v1/chat/completions")
    monkeypatch.setenv("FALLBACK_MODEL", "cyberfrost")
    s = proxy_gateway.Settings()
    assert s.fallback_api_url == "http://hub.local:4000/v1/chat/completions"
    assert s.fallback_model == "cyberfrost"


def test_divert_calls_the_resolved_specialist_with_the_env_key(script, monkeypatch):
    """A refusal diverts to the specialist slot, carrying the NanoGPT bearer."""
    spec = "http://nano.test/v1/chat/completions"
    # hermetic (2026-10-21): the operator's User-scope env carries
    # SPECIALIST_API_KEY; NANOGPT_API_KEY only wins when it is absent.
    monkeypatch.delenv("SPECIALIST_API_KEY", raising=False)
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    monkeypatch.setenv("NANOGPT_API_KEY", "sk-nano-test")
    s = proxy_gateway.SETTINGS
    monkeypatch.setattr(s, "fallback_api_url", spec)
    monkeypatch.setattr(s, "fallback_api_key", proxy_gateway._specialist_key())
    monkeypatch.setattr(s, "fallback_model", "abliteration-ai/abliterated-model-large-v2")
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(spec, [("sse", [chunk("uncensored answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "uncensored answer" in resp.text
    sent = [c for c in script.calls if c["url"] == spec]
    assert sent, "the specialist (NanoGPT) endpoint was never called"
    assert s.fallback_api_key == "sk-nano-test"
