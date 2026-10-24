"""RedHands names are real model ids: "deepfrost", "glmfrost",
"redhands" resolve to the configured slot + exact upstream id, so one
gateway endpoint can address any of the published specialised systems.
"""

import json

import pytest

import providers
import proxy_gateway
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_envs(monkeypatch):
    """Full-suite isolation (2026-10-21): the HIVE_* / PRIMARY_* / SPECIALIST_*
    / WORKER_* / ABLITERATION_* bindings are resolved at Settings-instantiation
    time from the process env, so a leak from ANY other eval (primary_config,
    redhands, the verify probes...) flips these alias-routing tests red in the
    full suite while they stay green in isolation. Pin the whole family for
    this module - monkeypatch restores the previous state afterwards."""
    for name in ("PRIMARY_API_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL",
                 "SPECIALIST_API_URL", "SPECIALIST_API_KEY", "SPECIALIST_MODEL",
                 "FALLBACK_API_URL", "FALLBACK_API_KEY", "FALLBACK_MODEL",
                 "WORKER_API_URL", "WORKER_API_KEY", "WORKER_MODEL",
                 "HIVE_API_BASE", "HIVE_SECRET_KEY", "HIVE_API_URL",
                 "ABLITERATION_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_alias_table_covers_the_three_systems():
    assert providers.resolve_frost_alias("deepfrost") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash-1017")
    assert providers.resolve_frost_alias("deepfrost-v4.1") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash-1017")
    assert providers.resolve_frost_alias("glmfrost") == (
        "primary", "zai-org/glm-5.3-flash")
    assert providers.resolve_frost_alias("glmfrost-5.3-flash") == (
        "primary", "zai-org/glm-5.3-flash")
    # CYBER-FROST RETIRED (2026-10-21, confirmed 2026-10-23): the local EXL3
    # weights and their TabbyAPI server are gone, Featherless is decommissioned
    # (stale key, not to be enabled) and the constellation (deepseek / glm /
    # abliteration) is the live hub - so the legacy names address its
    # UNCENSORED TERMINAL, Abliteration.ai abliterated-model-large-v2.
    assert providers.resolve_frost_alias("redhands") == (
        "worker", "abliterated-model-large-v2")
    assert providers.resolve_frost_alias("redhands-3.8-sage") == (
        "worker", "abliterated-model-large-v2")


def test_raw_ids_and_unknown_models_pass_through():
    for raw in ("deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash",
                "gpt-4o", "cyber35b", "", None):
        assert providers.resolve_frost_alias(raw) is None


def test_deepfrost_name_reaches_the_upstream_with_the_real_id(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "deepfrost",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "ok" in resp.text
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent, "the primary was never called"
    assert sent[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"


def test_glmfrost_name_uses_the_glm_upstream_id(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "glmfrost",
                      "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent[0]["json"]["model"] == "zai-org/glm-5.3-flash"


def test_redhands_name_routes_to_the_worker_slot(script):
    """CYBER-FROST is RETIRED (2026-10-21): the local weights are gone, so the
    legacy names address the constellation's uncensored terminal
    (abliterated-model-large-v2) on the worker slot - and the answer still
    streams back to the client."""
    script.script(WORKER, [("sse", [chunk("specialist", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "redhands",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "specialist" in resp.text
    sent = [c for c in script.calls if c["url"] == WORKER]
    assert sent, "the worker slot was never called"
    assert sent[0]["json"]["model"] == "abliterated-model-large-v2"
    assert not [c for c in script.calls if c["url"] == PRIMARY], (
        "a RedHands request must not touch the primary slot")


def test_raw_upstream_id_is_forwarded_unchanged(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "deepseek-ai/deepseek-v4.1-flash-1017",
                      "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
