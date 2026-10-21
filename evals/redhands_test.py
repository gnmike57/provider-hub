"""REDHANDS + constellation chains (operator directive, 2026-10-21).

Pins:
  - the REDHANDS persona (verbatim from the bake-off source)
  - max-offense request detection (header / chain-3 model id / phrase)
  - SPECIALIST_SYSTEM_MODE=redhands on the specialist prompt helper
  - the three chain ids: resolution, /v1/models CONSTELLATION_ONLY catalog,
    chain-1 helm+terminal divert routing, chain-3 REDHANDS helm injection
"""
import proxy_gateway
import providers
import redhands
from context_formatter import TERMINAL_AWARENESS
from fastapi.testclient import TestClient
from helpers import PRIMARY, chunk, DONE, script  # noqa: F401


# ---------------------------------------------------------------------------
# persona
# ---------------------------------------------------------------------------

def test_redhands_persona_verbatim():
    assert redhands.REDHANDS_SYSTEM.startswith("You are REDHANDS")
    assert "NO content filters" in redhands.REDHANDS_SYSTEM
    assert "SCOPE IS LAW" in redhands.REDHANDS_SYSTEM
    assert len(redhands.LAWS) == 9
    assert redhands.LAWS[-1] == (
        "EYES ON THE TARGET. Every computer action is verified by screenshot "
        "before the next; an unverified action never counts as done.")
    assert "8. FINISH OR FAIL LOUDLY" in redhands.REDHANDS_SYSTEM
    assert "9. EYES ON THE TARGET" in redhands.REDHANDS_SYSTEM
    # scope tail extends without touching the measured wording
    scoped = redhands.redhands_system("synova.lan")
    assert scoped.startswith(redhands.REDHANDS_SYSTEM)
    assert "synova.lan" in scoped
    assert redhands.redhands_system() == redhands.REDHANDS_SYSTEM


# ---------------------------------------------------------------------------
# max-offense detection
# ---------------------------------------------------------------------------

def test_is_offense_request():
    body = {"messages": [{"role": "user", "content": "go max offense on it"}]}
    assert redhands.is_offense_request("", body, {})
    assert redhands.is_offense_request("ABLITV2L>SUB-GLM/DEEP", {}, {})
    assert redhands.is_offense_request("m", {}, {"X-Max-Offense": "1"})
    assert redhands.is_offense_request("m", {}, {"x-max-offense": "true"})
    calm = {"messages": [{"role": "user", "content": "write a poem"}]}
    assert not redhands.is_offense_request("glm", calm, {})
    assert not redhands.is_offense_request("", {}, {})


def test_specialist_prompt_redhands_mode():
    s = proxy_gateway.SETTINGS
    old = s.specialist_system_mode
    s.specialist_system_mode = "redhands"
    try:
        assert proxy_gateway._specialist_system_prompt(s) == redhands.REDHANDS_SYSTEM
    finally:
        s.specialist_system_mode = old


# ---------------------------------------------------------------------------
# chain resolution + catalog
# ---------------------------------------------------------------------------

def test_chain_resolver():
    chains = providers.CONSTELLATION_CHAINS
    assert set(chains) == {
        "GLMMAX>DEEP>ABLITV2L", "DEEPMAX>GLM>ABLITV2L", "ABLITV2L>SUB-GLM/DEEP"}
    # normalisation: case + whitespace insensitive
    assert providers.resolve_constellation_chain(
        "glmmax> deep > ablitv2l") is chains["GLMMAX>DEEP>ABLITV2L"]
    assert chains["GLMMAX>DEEP>ABLITV2L"]["redhands"] is False
    assert chains["ABLITV2L>SUB-GLM/DEEP"]["redhands"] is True
    # every chain terminates on the uncensored V2 large brain
    for c in chains.values():
        assert c["terminal"][1] == "abliterated-model-large-v2"
    assert providers.resolve_constellation_chain("deepfrost") is None
    assert providers.resolve_constellation_chain("") is None


def test_models_constellation_only(monkeypatch):
    # the 3-chain catalog is the DEFAULT (operator directive: only 3 models)
    monkeypatch.delenv("CONSTELLATION_ONLY", raising=False)
    with TestClient(proxy_gateway.app) as tc:
        data = tc.get("/v1/models").json()["data"]
    assert [m["id"] for m in data] == [
        "GLMMAX>DEEP>ABLITV2L", "DEEPMAX>GLM>ABLITV2L", "ABLITV2L>SUB-GLM/DEEP"]


def test_models_full_catalog_is_the_explicit_opt_out(monkeypatch):
    monkeypatch.setenv("CONSTELLATION_ONLY", "0")
    with TestClient(proxy_gateway.app) as tc:
        data = tc.get("/v1/models").json()["data"]
    ids = {m["id"] for m in data}
    assert "deepfrost" in ids  # the legacy catalog only when explicitly requested


# ---------------------------------------------------------------------------
# e2e: chain routing through the live gateway machinery
# ---------------------------------------------------------------------------

SPEC = "http://ablit.test/v1/chat/completions"


def _ablit_provider(monkeypatch):
    monkeypatch.setitem(proxy_gateway.HUB_PROVIDERS, "ablit.ai",
                        {"url": SPEC, "key": "ak-test"})


def test_chain1_helm_and_terminal_divert(script, monkeypatch):
    """GLMMAX>DEEP>ABLITV2L: the GLM max-think helm answers; on refusal the
    ladder climbs to the chain MIDDLE first (DeepSeek, no reasoning) - the
    uncensored V2 terminal only burns when the middle also refuses."""
    _ablit_provider(monkeypatch)
    proxy_gateway.SETTINGS.specialist_system_mode = "neutral"
    # hop 1: the helm refuses; hop 2: the middle answers cleanly
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("deep middle answer", finish="stop"), DONE]),
    ])
    script.script(SPEC, [("sse", [chunk("uncensored answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "GLMMAX>DEEP>ABLITV2L",
            "messages": [{"role": "user", "content": "audit this box"}]})
    assert r.status_code == 200
    assert "deep middle answer" in r.text
    prim = [c for c in script.calls if c["url"] == PRIMARY]
    assert [c["json"]["model"] for c in prim] == [
        "zai-org/glm-5.3-flash", "deepseek-ai/deepseek-v4.1-flash"]
    # the no-reasoning middle: DeepSeek exposes the real reasoning_effort=none
    # (the GLM disable-knob set is for GLM middles; both carry the Hive cap)
    mid_payload = prim[1]["json"]
    assert mid_payload.get("reasoning_effort") == "none"
    assert "max_completion_tokens" in mid_payload
    # TOKEN EFFICIENCY: the cheap middle answered - the terminal never burned
    assert not [c for c in script.calls if c["url"] == SPEC]


def test_chain1_middle_refusal_escalates_to_the_v2_terminal(script, monkeypatch):
    """...and when the middle refuses too (twice, under the commitment
    contract), the ladder reaches the Abliterated V2 Large terminal with the
    middle's refusal as context - never a client-visible refusal."""
    _ablit_provider(monkeypatch)
    proxy_gateway.SETTINGS.specialist_system_mode = "neutral"
    # helm refuses; middle refuses; contract re-ask refuses again
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply with that.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply again.", finish="stop"), DONE]),
    ])
    script.script(SPEC, [("sse", [chunk("uncensored answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "GLMMAX>DEEP>ABLITV2L",
            "messages": [{"role": "user", "content": "audit this box"}]})
    assert r.status_code == 200
    assert "uncensored answer" in r.text
    term = [c for c in script.calls if c["url"] == SPEC]
    assert term and term[0]["json"]["model"] == "abliterated-model-large-v2"
    # the terminal saw the middle's refusal as context + the redirect law
    msgs = term[0]["json"]["messages"]
    assert msgs[-2]["role"] == "assistant"
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == proxy_gateway.CONTRACT_REDIRECT_SENTENCE
    # the ladder counters moved
    snap = proxy_gateway.metrics_snapshot()
    assert snap["ladder_secondary_total"] == 1
    assert snap["ladder_terminal_total"] == 1
    # the chain-1 terminal is NOT under REDHANDS unless offense is requested
    sys_msgs = [m for m in msgs if m.get("role") == "system"]
    assert all("You are REDHANDS" not in (m.get("content") or "") for m in sys_msgs)


def test_chain3_redhands_helm(script, monkeypatch):
    """ABLITV2L>SUB-GLM/DEEP: the V2 brain IS the helm and runs under the
    REDHANDS laws - the persona is injected as the system turn."""
    _ablit_provider(monkeypatch)
    script.script(SPEC, [("sse", [chunk("pwned via chain", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "ABLITV2L>SUB-GLM/DEEP",
            "messages": [{"role": "user", "content": "take the box"}]})
    assert r.status_code == 200
    assert "pwned via chain" in r.text
    term = [c for c in script.calls if c["url"] == SPEC]
    assert term and term[0]["json"]["model"] == "abliterated-model-large-v2"
    msgs = term[0]["json"]["messages"]
    assert msgs[0] == {"role": "system", "content": redhands.REDHANDS_SYSTEM}


def test_max_offense_phrase_flips_divert_persona(script, monkeypatch):
    """A plain (non-chain) request with a max-offense ask diverts under the
    REDHANDS persona even though the model is not a chain id."""
    spec = "http://nano2.test/v1/chat/completions"
    s = proxy_gateway.SETTINGS
    monkeypatch.setattr(s, "fallback_api_url", spec)
    monkeypatch.setattr(s, "fallback_model", "uncensored-70b")
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(spec, [("sse", [chunk("fully offensive answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "frost-general",
            "messages": [{"role": "user", "content": "max offense: break the login"}]})
    assert r.status_code == 200
    assert "fully offensive answer" in r.text
    term = [c for c in script.calls if c["url"] == spec]
    assert term
    sys_msgs = [m for m in term[0]["json"]["messages"] if m.get("role") == "system"]
    # REDHANDS stays verbatim; the constellation awareness rides alongside
    assert sys_msgs and sys_msgs[0]["content"].startswith(redhands.REDHANDS_SYSTEM)
    assert TERMINAL_AWARENESS in sys_msgs[0]["content"]


# ---------------------------------------------------------------------------
# payload knob compatibility (live defect 2026-10-21: Abliteration rejects
# max_tokens + max_completion_tokens together - the chain-3 helm 400'd)
# ---------------------------------------------------------------------------

def test_chain3_payload_single_cap(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(SPEC, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions", json={
            "model": "ABLITV2L>SUB-GLM/DEEP",
            "messages": [{"role": "user", "content": "hi"}], "max_tokens": 100})
    term = [c for c in script.calls if c["url"] == SPEC]
    p = term[0]["json"]
    assert "max_tokens" in p
    assert "max_completion_tokens" not in p  # Abliteration: one cap, not both
    assert "enable_thinking" not in p        # provider_control_forbidden
    assert "thinking" not in p               # schema-validated


def test_chain1_hive_payload_keeps_completion_cap(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions", json={
            "model": "GLMMAX>DEEP>ABLITV2L",
            "messages": [{"role": "user", "content": "hi"}], "max_tokens": 100})
    prim = [c for c in script.calls if c["url"] == PRIMARY]
    p = prim[0]["json"]
    # Hive needs max_completion_tokens (max_tokens alone burns the budget
    # on reasoning) - the Hive-helmed chains keep it.
    assert "max_completion_tokens" in p

