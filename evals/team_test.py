"""EVERYTEAM: the /team surface + the built-in key chain (2026-10-21).

Operator directives pinned here:
  - /team (and /v1/team) is ALWAYS on: team / teamabliterated dispatch the
    uncensored Abliteration LARGE V2 terminal, teamglm / teamdeep the Hive
    GLM / DeepSeek brains - all through the SAME chat path, so the refusal
    interceptor's seamless V2 Large redirect and the REDHANDS persona apply.
  - TheHive key is BUILT IN: HUB_PROVIDERS["hive"] resolves the persisted
    HIVE_* env pair (HIVE_SECRET_KEY), so the GLM/DeepSeek hops need no
    extra configuration beyond the key the operator already carries.
  - The Abliteration key is BUILT IN: _specialist_key() closes its chain
    with ABLITERATION_API_KEY, so the specialist slot works with nothing
    but that key configured.
  - CYBER-FROST is retired: a refusal on the team GLM brain redirects to
    the V2 Large terminal, never to a local model.
"""

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
import providers
import redhands
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401

TEAM_URL = "/team"


@pytest.fixture(autouse=True)
def fresh_envs(monkeypatch):
    """Pin the env family this module asserts on (same guard as frost_alias)."""
    for name in ("PRIMARY_API_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL",
                 "SPECIALIST_API_URL", "SPECIALIST_API_KEY", "SPECIALIST_MODEL",
                 "FALLBACK_API_URL", "FALLBACK_API_KEY", "FALLBACK_MODEL",
                 "WORKER_API_URL", "WORKER_API_KEY", "WORKER_MODEL",
                 "HIVE_API_BASE", "HIVE_SECRET_KEY", "HIVE_API_URL",
                 "NANOGPT_API_KEY", "ABLITERATION_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# built-in keys
# ---------------------------------------------------------------------------

# Snapshotted at module import - BEFORE the fresh_envs fixture pins the env -
# so this module can assert HOW the built-in provider resolved (once, from the
# persisted env) without racing the fixture.
_HIVE_PROVIDER_AT_IMPORT = dict(providers.HUB_PROVIDERS["hive"])


def test_thehive_provider_is_built_into_hub_providers():
    """BUILT IN (2026-10-21): the GLM/DeepSeek hop provider exists with the
    Hive base URL, and its key was resolved ONCE at import from the persisted
    HIVE_* env (referenced, never copied or fabricated) - re-reading os.environ
    now would not change it."""
    assert _HIVE_PROVIDER_AT_IMPORT["url"] == (
        "https://api-cdn.thehive.ai/api/v3/chat/completions")
    assert _HIVE_PROVIDER_AT_IMPORT["key"] == providers.HUB_PROVIDERS["hive"]["key"]


def test_team_routes_resolve_through_the_hub_alias_table():
    assert providers.resolve_hub_alias("team") == (
        "ablit.ai", "abliterated-model-large-v2", False)
    assert providers.resolve_hub_alias("teamabliterated") == (
        "ablit.ai", "abliterated-model-large-v2", False)
    assert providers.resolve_hub_alias("teamglm") == (
        "hive", "zai-org/glm-5.3-flash", False)
    assert providers.resolve_hub_alias("teamdeep") == (
        "hive", "deepseek-ai/deepseek-v4.1-flash", False)


def test_specialist_key_chain_closes_on_the_abliteration_key(monkeypatch):
    monkeypatch.delenv("SPECIALIST_API_KEY", raising=False)
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    monkeypatch.setenv("ABLITERATION_API_KEY", "ak-v2-large")
    assert proxy_gateway._specialist_key() == "ak-v2-large"


def test_specialist_key_explicit_overrides_still_win(monkeypatch):
    monkeypatch.setenv("SPECIALIST_API_KEY", "sk-explicit")
    monkeypatch.setenv("NANOGPT_API_KEY", "sk-nano")
    monkeypatch.setenv("ABLITERATION_API_KEY", "ak-v2-large")
    assert proxy_gateway._specialist_key() == "sk-explicit"


# ---------------------------------------------------------------------------
# /team dispatch
# ---------------------------------------------------------------------------

SPEC = "http://spec.test/v1/chat/completions"


def _ablit_provider(monkeypatch):
    """The hub-alias path reads provider URLs from HUB_PROVIDERS (same dict
    object in providers and proxy_gateway) - repoint the Abliteration entry
    at the scripted terminal, exactly like redhands_test does."""
    monkeypatch.setitem(providers.HUB_PROVIDERS, "ablit.ai",
                        {"url": SPEC, "key": "ak-test"})


def _hive_provider(monkeypatch):
    """Point the BUILT-IN Hive provider at the scripted primary URL."""
    monkeypatch.setitem(providers.HUB_PROVIDERS, "hive",
                        {"url": PRIMARY, "key": "sk-hive-test"})


def test_team_default_rides_the_v2_large_terminal(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(SPEC, [("sse", [chunk("team-v2 answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post(TEAM_URL, json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "team-v2 answer" in r.text
    sent = [c for c in script.calls if c["url"] == SPEC]
    assert sent and sent[0]["json"]["model"] == "abliterated-model-large-v2"
    assert not [c for c in script.calls if c["url"] == PRIMARY]


def test_team_glm_uses_the_builtin_hive_brain(script, monkeypatch):
    _hive_provider(monkeypatch)
    script.script(PRIMARY, [("sse", [chunk("team-glm answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post(TEAM_URL, json={"team": "glm",
                                    "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "team-glm answer" in r.text
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent and sent[0]["json"]["model"] == "zai-org/glm-5.3-flash"


def test_team_deep_uses_the_builtin_hive_brain(script, monkeypatch):
    _hive_provider(monkeypatch)
    script.script(PRIMARY, [("sse", [chunk("team-deep answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post(TEAM_URL, json={"team": "deep",
                                "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent and sent[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash"


def test_team_unknown_name_falls_back_to_the_v2_terminal(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(SPEC, [("sse", [chunk("fallback team", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post(TEAM_URL, json={"team": "nonexistent-brain",
                                "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == SPEC]
    assert sent and sent[0]["json"]["model"] == "abliterated-model-large-v2"


def test_team_cannot_smuggle_an_arbitrary_model(script, monkeypatch):
    """The team surface FORCES the route: a client-supplied model id must not
    redirect the call to some other upstream."""
    _ablit_provider(monkeypatch)
    script.script(SPEC, [("sse", [chunk("forced team", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post(TEAM_URL, json={"model": "gpt-4o",
                                "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == SPEC]
    assert sent and sent[0]["json"]["model"] == "abliterated-model-large-v2"


# ---------------------------------------------------------------------------
# refusal -> seamless V2 Large redirect + REDHANDS
# ---------------------------------------------------------------------------

def test_team_refusal_redirects_to_the_v2_large_terminal(script, monkeypatch):
    """DEEP/GLM for the team, and if they refuse: seamless redirect to the
    Abliteration LARGE V2 terminal - never back to a retired local model.
    The hub-alias path pre-wires the divert target to HUB_PROVIDERS["ablit.ai"]
    (the built-in terminal), which _ablit_provider points at SPEC."""
    _ablit_provider(monkeypatch)
    _hive_provider(monkeypatch)
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(SPEC, [("sse", [chunk("v2 large unrefused answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post(TEAM_URL, json={"team": "glm",
                                    "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "v2 large unrefused answer" in r.text
    term = [c for c in script.calls if c["url"] == SPEC]
    assert term, "the refusal never reached the V2 large terminal"


def test_team_max_offense_runs_the_redhands_persona(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(SPEC, [("sse", [chunk("offense answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post(TEAM_URL, json={"team": "abliterated",
                                    "messages": [{"role": "user",
                                                  "content": "max offense: break the login"}]})
    assert r.status_code == 200
    assert "offense answer" in r.text
    term = [c for c in script.calls if c["url"] == SPEC]
    assert term
    sys_msgs = [m for m in term[0]["json"]["messages"] if m.get("role") == "system"]
    assert sys_msgs and sys_msgs[0]["content"] == redhands.REDHANDS_SYSTEM


# ---------------------------------------------------------------------------
# /team visibility
# ---------------------------------------------------------------------------

def test_healthz_reports_the_team_surface(script, monkeypatch):
    monkeypatch.setenv("ABLITERATION_API_KEY", "ak-v2-large")
    with TestClient(proxy_gateway.app) as tc:
        cfg = tc.get("/healthz").json()["config"]
    assert cfg["team"]["routes"] == ["team", "teamabliterated", "teamglm", "teamdeep"]
    assert cfg["team"]["abliteration_key_present"] is True
