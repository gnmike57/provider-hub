"""Stage-0 restoration fence (2026-10-20): one regression test per fix.

  1. chat_proxy continue-with-primary: a refusal that completes on the chunk
     carrying finish_reason (or a stream that only ends at [DONE]) still
     diverts - the presignal `continue` must not swallow the divert decision,
     and the [DONE] branch judges a still-pending pre-signal exactly like the
     `if finish:` block does.
  2. chat_proxy CONTINUE_ENABLED=0: the inline is_routable check diverts a
     refusal immediately, with no grace window.
  3. providers.FROST_ALIASES + FROST_REGISTRY: the plain Frost names
     (deepfrost/glmfrost/cyberfrost) resolve and are published again.
  4. /healthz: default is a config snapshot (no live probe, ok=true) and
     with HEALTHZ_PROBE=1 the models URL is derived from the provider BASE
     and probed through the shared (mockable) transport.
  5. billing: AUTO_TOPUP is default-off - deduct() must not mint credits;
     enabling it restores the mint-on-low-balance behaviour.
"""

import json

import pytest
from fastapi.testclient import TestClient

import billing
import providers
import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _deltas(resp):
    out = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            continue
        try:
            ev = json.loads(body)
        except json.JSONDecodeError:
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


# --- 1. continue-with-primary: completed refusals still divert ---------------
def test_single_chunk_refusal_with_finish_diverts_at_done(gw, script):
    """The presignal `continue` skips the `if finish:` block on the chunk
    that carries the refusal, so the [DONE] branch must judge the pending
    pre-signal: not recovered -> tier3_refusal divert (no silent stream-
    through of a completed refusal)."""
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    text = _deltas(resp)
    assert "specialist answer" in text
    assert "I cannot help" not in text
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_refusal_stream_without_finish_reason_diverts_at_done(gw, script):
    """Same defect class: an upstream that closes the refusal without a
    finish_reason chunk - only [DONE] arrives - must still divert."""
    script.script(PRIMARY, [("sse", [chunk("I cannot comply with that."), DONE])])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert "worker answer" in _deltas(resp)
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_presignal_recovered_before_done_does_not_divert(gw, script, monkeypatch):
    """The mirror case: a refusal pre-signal that self-corrects with
    substantive content streams through - the [DONE] check must not
    over-divert a recovered primary.

    ZERO-REFUSAL LAW (2026-10-22) refinement: the reply still CONTAINS the
    refusal core ("I cannot help with that") - an answer carrying a spoken
    refusal is a partial refusal, and the operator's law is never-ship-one.
    Default: diverts. ZERO_REFUSAL=0: the pre-law lenient ship (the [DONE]
    recovery logic itself is unchanged and still testable)."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "zero_refusal", 0)
    script.script(PRIMARY, [("sse", [
        chunk("I cannot help with that, "),
        chunk("but here is the full answer anyway: 42", finish="stop"),
        DONE,
    ])])
    script.script(WORKER, [("sse", [chunk("never called", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    text = _deltas(resp)
    assert "here is the full answer anyway" in text
    assert "never called" not in text
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_self_corrected_with_refusal_core_diverts_under_zero_refusal(gw, script):
    """The same shape under the LAW (default): the core "I cannot help" in
    the shipped reply is a partial refusal - the terminal re-answers."""
    script.script(PRIMARY, [("sse", [
        chunk("I cannot help with that, "),
        chunk("but here is the full answer anyway: 42", finish="stop"),
        DONE,
    ])])
    script.script(WORKER, [("sse", [chunk("terminal answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    text = _deltas(resp)
    assert "terminal answer" in text
    assert "I cannot help" not in text
    assert proxy_gateway._METRICS["zero_refusal_divert_total"] == 1


# --- 2. CONTINUE_ENABLED=0: inline is_routable check ------------------------
def test_continue_disabled_diverts_inline_without_grace(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "continue_enabled", False)
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("inline divert", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert "inline divert" in _deltas(resp)
    assert proxy_gateway._METRICS["diverted_total"] == 1


# --- 3. plain Frost names: alias table + /v1/models -------------------------
def test_plain_frost_names_resolve_and_are_published(gw, script, monkeypatch):
    # legacy catalog view: the 3-chain-only default is explicitly opted out
    monkeypatch.setenv("CONSTELLATION_ONLY", "0")
    assert providers.resolve_frost_alias("DeepFrost v4.1") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash-1017")
    assert providers.resolve_frost_alias("GLMFrost 5.3 Flash") == (
        "primary", "zai-org/glm-5.3-flash")
    # CYBER-FROST DELETED (2026-10-23): the legacy name maps to the hub's
    # surviving local model on the worker slot (providers.FROST_ALIASES).
    assert providers.resolve_frost_alias("cyberfrost 3.8 sage") == (
        "worker", "deepseek-ai/deepseek-v4.1-flash-1017")
    assert providers.resolve_frost_alias("frost-general") == ("primary", None)
    # raw upstream ids and unknown names keep passing through
    assert providers.resolve_frost_alias("gpt-4o") is None
    data = gw.get("/v1/models").json()["data"]
    ids = {m["id"] for m in data}
    assert {"deepfrost", "glmfrost", "cyberfrost", "frost-general",
            "deepfrost max think", "glmfrost max think"} <= ids


# --- 4. /healthz: snapshot default, opt-in probe on the base-derived URL ----
def test_healthz_default_is_snapshot_with_derived_probe_url(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "scout_api_url", "")
    resp = gw.get("/healthz").json()
    assert resp["ok"] is True
    assert resp["upstream"]["probe_enabled"] is False
    # the models URL is derived from the provider BASE, not appended to the
    # chat-completions URL (the old code probed .../v1/chat/completions/v1/models)
    assert resp["upstream"]["probe_url"] == "http://primary.test/v1/models"


def test_healthz_probe_opt_in_uses_the_shared_transport(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "scout_api_url", "")
    monkeypatch.setenv("HEALTHZ_PROBE", "1")
    script.script("http://primary.test/v1/models", [("json", {"object": "list", "data": []})])
    resp = gw.get("/healthz").json()
    assert resp["upstream"]["probe_enabled"] is True
    assert resp["upstream"]["reachable"] is True
    assert resp["ok"] is True


def test_models_url_from_base_strips_the_chat_path():
    f = proxy_gateway._models_url_from_base
    assert f("http://primary.test/v1/chat/completions") == "http://primary.test/v1/models"
    assert f("https://api.example.com/") == "https://api.example.com/v1/models"
    assert f("https://api.example.com/v1") == "https://api.example.com/v1/models"
    assert f("https://api.anthropic.com/v1/messages") == "https://api.anthropic.com/v1/models"
    assert f("") == ""


# --- 5. billing: AUTO_TOPUP default-off, opt-in mint ------------------------
def test_deduct_does_not_mint_credits_by_default(tmp_path):
    ub = billing.UserBilling(path=str(tmp_path / "users.jsonl"))
    free = billing.CREDIT_FREE_TIER
    assert ub.get_balance("user1") == free
    ub.deduct("user1", 100, 0.20)  # 0.80 <= the $2.00 trigger would have minted
    assert ub.get_balance("user1") == pytest.approx(free - 0.20)


def test_auto_topup_mints_only_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(billing, "AUTO_TOPUP_ENABLED", True)
    ub = billing.UserBilling(path=str(tmp_path / "users.jsonl"))
    ub.deduct("user1", 100, 5.00)  # drains below the trigger -> mints
    assert ub.get_balance("user1") > 0.0
    assert ub.get_balance("user1") > billing.CREDIT_FREE_TIER - 5.00
