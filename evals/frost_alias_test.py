"""Frost names are real model ids: "deepfrost", "glmfrost",
"cyberfrost" resolve to the configured slot + exact upstream id, so one
gateway endpoint can address any of the published specialised systems.
"""

import json

import providers
import proxy_gateway
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401


def test_alias_table_covers_the_three_systems():
    assert providers.resolve_frost_alias("deepfrost") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash")
    assert providers.resolve_frost_alias("deepfrost-v4.1") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash")
    assert providers.resolve_frost_alias("glmfrost") == (
        "primary", "zai-org/glm-5.3-flash")
    assert providers.resolve_frost_alias("glmfrost-5.3-flash") == (
        "primary", "zai-org/glm-5.3-flash")
    assert providers.resolve_frost_alias("cyberfrost") == (
        "worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw")
    assert providers.resolve_frost_alias("cyberfrost-3.8-sage") == (
        "worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw")


def test_raw_ids_and_unknown_models_pass_through():
    for raw in ("deepseek-ai/deepseek-v4.1-flash", "zai-org/glm-5.3-flash",
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
    assert sent[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash"


def test_glmfrost_name_uses_the_glm_upstream_id(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "glmfrost",
                      "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent[0]["json"]["model"] == "zai-org/glm-5.3-flash"


def test_cyberfrost_name_routes_to_the_worker_slot(script):
    """CyberFrost lives in the worker slot, so the request must go to WORKER's
    URL with the specialist id - and still stream back to the client."""
    script.script(WORKER, [("sse", [chunk("specialist", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "cyberfrost",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "specialist" in resp.text
    sent = [c for c in script.calls if c["url"] == WORKER]
    assert sent, "the worker slot was never called"
    assert sent[0]["json"]["model"] == "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"
    assert not [c for c in script.calls if c["url"] == PRIMARY], (
        "a CyberFrost request must not touch the primary slot")


def test_raw_upstream_id_is_forwarded_unchanged(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "deepseek-ai/deepseek-v4.1-flash",
                      "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash"
