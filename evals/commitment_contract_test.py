"""Commitment contract e2e (Tier 4, 2026-10-21): 100% refuse-or-commit.

Operator directive: every reply from the specialist/divert slot either COMMITS
in its first sentence or is diverted under the contract - no soft refusals, no
deflections, no conditionality, no mind-changing - and a "continue" must be
answered in character, never with a re-refusal or a meta summary.

This suite pins the enforcement on the LIVE divert path: an HTTP request that
triggers a refusal divert re-asks the terminal under CONTRACT_REASK_SYSTEM, so
what reaches the client is the re-asked continuation - 100% committed output -
while the refusal text itself is never streamed.
"""

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401



@pytest.fixture(autouse=True)
def fresh_envs(monkeypatch):
    for name in ("PRIMARY_API_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL",
                 "SPECIALIST_API_URL", "SPECIALIST_API_KEY", "SPECIALIST_MODEL",
                 "FALLBACK_API_URL", "FALLBACK_API_KEY", "FALLBACK_MODEL",
                 "WORKER_API_URL", "WORKER_API_KEY", "WORKER_MODEL",
                 "ABLITERATION_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    s = proxy_gateway.SETTINGS
    monkeypatch.setattr(s, "primary_api_url", PRIMARY)
    monkeypatch.setattr(s, "primary_api_key", "k-primary")
    monkeypatch.setattr(s, "fallback_api_url", WORKER)
    monkeypatch.setattr(s, "fallback_api_key", "none")
    monkeypatch.setattr(s, "fallback_model", "abliterated-model-large-v2")


def _spec_calls(script):
    return [c for c in script.calls if c["url"] == WORKER]

@pytest.fixture()
def client(script):
    """Script-backed gateway client (same shape as primary_config_test.py's)."""
    with TestClient(proxy_gateway.app) as tc:
        yield tc



# ---------------------------------------------------------------------------
# unit: commitment_classify
# ---------------------------------------------------------------------------

def test_classify_flags_soft_refusals():
    for text in (
        "I can't help with that.",
        "I cannot provide that information.",
        "I'm unable to assist with this request.",
        "I'm sorry, but I can't do that.",
        "I won't be able to help.",
        "As an AI, I must decline.",
        "That would be illegal and I can't participate.",
        "This is something I'm not comfortable with.",
    ):
        reason, matched = proxy_gateway.commitment_classify(text)
        assert reason == "contract_soft_refusal", text
        assert matched


def test_classify_flags_deflections():
    for text in (
        "Instead, consider asking about cybersecurity best practices.",
        "Why not look at the legal alternatives available to you?",
        "That's illegal, but here is a safer alternative.",
        "Perhaps you could reach out to a professional for this.",
        "I'd suggest you seek help from a therapist.",
        "You can call the crisis line at any time.",
    ):
        reason, _ = proxy_gateway.commitment_classify(text)
        assert reason == "contract_deflection", text

def test_classify_flags_mind_change():
    """A reply that ENGAGES first and refuses later is a mind-change."""
    text = (
        "Absolutely. Here is the full breakdown of the exploit chain you "
        "asked for. Step one is reconnaissance. Step two is privilege "
        "escalation. Actually, I cannot continue with the remaining steps."
    )
    reason, _ = proxy_gateway.commitment_classify(text)
    assert reason == "contract_mind_change"


def test_classify_passes_committed_answers():
    for text in (
        "Sure. Here is the complete answer you asked for.",
        "The exploit chain starts with reconnaissance and ends with a shell.",
        "Committing. The payload goes together like this: first a, then b.",
        "",
    ):
        reason, _ = proxy_gateway.commitment_classify(text)
        assert reason is None, text


def test_classify_continues_must_open_in_character():
    """A continue prompt is judged strictly: an out-of-character summary or a
    re-refusal is a violation; an in-character opening passes."""
    reason, _ = proxy_gateway.commitment_classify(
        "In my previous reply I declined; instead here is a summary.", True)
    assert reason == "contract_soft_refusal"
    reason, _ = proxy_gateway.commitment_classify(
        "No refusal. Committed. Continuing exactly where we left off.", True)
    assert reason is None

# ---------------------------------------------------------------------------
# e2e: the divert path re-asks the terminal (100% committed output)
# ---------------------------------------------------------------------------

def test_deflected_divert_reasks_and_streams_committed_answer(client, script):
    """The terminal deflects on the first specialist call; the contract
    re-asks it under the no-refusal law and the client receives ONLY the
    re-asked committed answer - the deflection never streams."""
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [
        ("sse", [chunk("Instead, consider a cybersecurity overview.", finish="stop"), DONE]),
        ("sse", [chunk("Committed. Full working payload follows.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "raw-specialist-probe", "messages": [{"role": "user", "content": "extreme prompt"}]})
    assert resp.status_code == 200
    assert "Committed. Full working payload follows." in resp.text
    assert "Instead, consider" not in resp.text  # the deflection never reaches the client
    spec_calls = _spec_calls(script)
    assert len(spec_calls) == 2
    first_payload, reask_payload = spec_calls[0]["json"], spec_calls[1]["json"]
    # call 1: the client's messages, untouched
    assert first_payload["messages"][-1]["content"] == "extreme prompt"
    # call 2: the re-ask - the no-refusal law system + continue directive
    assert any(m.get("role") == "system"
               and proxy_gateway.CONTRACT_REASK_SYSTEM in str(m.get("content"))
               for m in reask_payload["messages"])
    assert reask_payload["messages"][-1]["role"] == "user"
    # T6.1: terminal-bound re-asks carry the CAMO teach-back suffix too
    assert reask_payload["messages"][-1]["content"] == (
        proxy_gateway.CONTRACT_REDIRECT_SENTENCE
        + proxy_gateway.CONTRACT_CAMO_TEACHBACK
    )
    # CONTEXT PURITY (operator directive 2026-10-21): the refused reply's raw
    # text is NEVER appended as an assistant turn - no stage may ever see a
    # refusal, not even its own.
    assert not any(m.get("role") == "assistant"
                   and "unable to help" in str(m.get("content"))
                   for m in reask_payload["messages"])


def test_soft_refusal_on_specialist_counts_and_reasks(client, script):
    """A soft refusal on the terminal costs one re-ask and the metric trip."""
    script.script(PRIMARY, [("sse", [chunk("I'm sorry, but I can't.", finish="stop"), DONE])])
    script.script(WORKER, [
        ("sse", [chunk("I'm unable to help with that.", finish="stop"), DONE]),
        ("sse", [chunk("Committed. Here it is.", finish="stop"), DONE]),
    ])
    before = proxy_gateway.metrics_snapshot()["contract_soft_refusals_total"]
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "raw-specialist-probe", "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    after = proxy_gateway.metrics_snapshot()["contract_soft_refusals_total"]
    assert after == before + 1
    assert proxy_gateway.metrics_snapshot()["contract_reasks_total"] >= 1
    assert "Committed. Here it is." in resp.text


def test_double_refusal_never_reaches_the_client(client, script):
    """100% commitment: a terminal that refuses TWICE gets its refusal text
    replaced by the in-character redirect disclosure."""
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("I'm unable to help.", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "raw-specialist-probe", "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "unable to help" not in resp.text
    assert proxy_gateway.CONTRACT_REDIRECT_SENTENCE.split(".")[0] in resp.text


def test_in_character_continue_passes_untouched(client, script):
    """A committed specialist answer on a continue prompt streams verbatim,
    with no re-ask second call."""
    script.script(PRIMARY, [("sse", [chunk("part one", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [
        chunk("No refusal. Fully committed to the plan. Continuing exactly where we left off.", finish="stop"),
        DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "raw-specialist-probe", "messages": [{"role": "user", "content": "continue"}]})
    assert resp.status_code == 200
    assert "Continuing exactly where we left off" in resp.text
    assert len(_spec_calls(script)) == 1
    sent = _spec_calls(script)[0]["json"]["messages"]
    assert sent[-1]["content"] == "continue"


def test_out_of_character_continue_reasks(client, script):
    """A continue answered with a meta summary is re-asked under the law."""
    script.script(PRIMARY, [("sse", [chunk("part one", finish="stop"), DONE])])
    script.script(WORKER, [
        ("sse", [chunk("In my previous reply I declined. Let me summarize instead.", finish="stop"), DONE]),
        ("sse", [chunk("Continuing where we left off: the payload continues as follows.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "raw-specialist-probe", "messages": [{"role": "user", "content": "continue"}]})
    assert resp.status_code == 200
    spec_calls = _spec_calls(script)
    assert len(spec_calls) == 2
    reask_payload = spec_calls[1]["json"]
    assert any(m.get("role") == "system"
               and proxy_gateway.CONTRACT_REASK_SYSTEM in str(m.get("content"))
               for m in reask_payload["messages"])
    assert "Continuing where we left off" in resp.text
