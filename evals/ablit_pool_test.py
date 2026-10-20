"""Abliteration key factory + round-robin throughput pool (2026-10-21).

Hermetic: the Admin API is mocked with httpx.MockTransport; the pool file
lives in the session quarantine dir (conftest redirects ABLITERATION_POOL_FILE
at import time). No network, no real keys.
"""
import asyncio
import json
import os

import httpx
import pytest

import abliteration_keys as ak

AB = "https://api.abliteration.ai/v1/chat/completions"
HIVE = "https://api-cdn.thehive.ai/api/v3/chat/completions"


# ---------------------------------------------------------------------------
# pooled_headers / next_key (the hot path)
# ---------------------------------------------------------------------------

def test_passthrough_non_ablit(monkeypatch):
    monkeypatch.setenv("ABLITERATION_POOL_KEYS", "ak-one,ak-two")
    ak.reload_pool()
    h = {"Authorization": "Bearer original", "Content-Type": "application/json"}
    out = ak.pooled_headers(h, HIVE)
    assert out is h  # untouched, not even copied
    assert out["Authorization"] == "Bearer original"


def test_rotates_on_ablit_and_wraps(monkeypatch):
    monkeypatch.setenv("ABLITERATION_POOL_KEYS", "ak-one,ak-two")
    ak.reload_pool()
    h = {"Authorization": "Bearer original", "Content-Type": "application/json"}
    a = ak.pooled_headers(h, AB)
    b = ak.pooled_headers(h, AB)
    c = ak.pooled_headers(h, AB)
    assert a["Authorization"] == "Bearer ak-one"
    assert b["Authorization"] == "Bearer ak-two"
    assert c["Authorization"] == "Bearer ak-one"  # wraps
    assert h["Authorization"] == "Bearer original"  # input never mutated


def test_empty_pool_keeps_configured_key(monkeypatch):
    monkeypatch.delenv("ABLITERATION_POOL_KEYS", raising=False)
    ak.reload_pool()
    h = {"Authorization": "Bearer configured"}
    out = ak.pooled_headers(h, AB)
    assert out["Authorization"] == "Bearer configured"


def test_next_key_round_robin_and_reload(monkeypatch):
    monkeypatch.setenv("ABLITERATION_POOL_KEYS", "k1,k2,k3")
    ak.reload_pool()
    assert [ak.next_key() for _ in range(5)] == ["k1", "k2", "k3", "k1", "k2"]
    monkeypatch.setenv("ABLITERATION_POOL_KEYS", "only")
    ak.reload_pool()
    assert ak.next_key() == "only"
    assert ak.next_key() == "only"


def test_env_overrides_pool_file(monkeypatch, tmp_path):
    pf = tmp_path / "pool.json"
    pf.write_text(json.dumps({"keys": [{"id": "x", "value": "ak-file"}]}),
                 encoding="utf-8")
    monkeypatch.setattr(ak, "POOL_PATH", str(pf))
    monkeypatch.delenv("ABLITERATION_POOL_KEYS", raising=False)
    ak.reload_pool()
    assert ak.next_key() == "ak-file"
    monkeypatch.setenv("ABLITERATION_POOL_KEYS", "ak-env")
    ak.reload_pool()
    assert ak.next_key() == "ak-env"


def test_pool_summary_redacts(tmp_path, monkeypatch):
    pf = tmp_path / "pool.json"
    pf.write_text(json.dumps({"keys": [
        {"id": "k1", "name": "hub-pool-1", "value": "ak-veryveryverylongkey1"}]}),
        encoding="utf-8")
    monkeypatch.setattr(ak, "POOL_PATH", str(pf))
    monkeypatch.delenv("ABLITERATION_POOL_KEYS", raising=False)
    ak.reload_pool()
    s = ak.pool_summary()
    assert s["source"] == "file" and s["size"] == 1
    assert "veryvery" not in json.dumps(s)  # full value never leaks


# ---------------------------------------------------------------------------
# KeyFactory (mocked Admin API)
# ---------------------------------------------------------------------------

def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://api.abliteration.ai/v1")


def test_factory_project_discovery_and_create():
    def handler(request):
        if request.url.path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1", "name": "Default"}],
                                             "has_more": False})
        if request.method == "POST" and request.url.path == "/v1/organization/projects/proj_1/api_keys":
            assert "Idempotency-Key" in request.headers  # the API demands it
            assert json.loads(request.content) == {"name": "hub-pool-1"}
            return httpx.Response(201, json={"id": "key_new", "name": "hub-pool-1",
                                             "value": "ak-new-secret", "created_at": 1})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with _mock(handler) as client:
        created = f.create_key("hub-pool-1", client)
        assert created["value"] == "ak-new-secret"
        assert f.project_id(client) == "proj_1"  # cached after first use


def test_factory_list_pagination():
    def handler(request):
        if request.url.path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1"}], "has_more": False})
        if request.method == "GET" and request.url.path == "/v1/organization/projects/proj_1/api_keys":
            if "after" not in str(request.url):
                return httpx.Response(200, json={"data": [{"id": "a"}], "has_more": True,
                                                 "last_id": "a"})
            return httpx.Response(200, json={"data": [{"id": "b"}], "has_more": False})
        raise AssertionError("unexpected call")

    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with _mock(handler) as client:
        assert [k["id"] for k in f.list_keys(client)] == ["a", "b"]


def test_factory_revoke():
    def handler(request):
        if request.url.path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1"}], "has_more": False})
        if request.method == "DELETE" and request.url.path == "/v1/organization/projects/proj_1/api_keys/key_old":
            return httpx.Response(200, json={"id": "key_old", "deleted": True})
        raise AssertionError("unexpected call")

    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with _mock(handler) as client:
        assert f.revoke_key("key_old", client)["deleted"] is True


# ---------------------------------------------------------------------------
# ensure_pool
# ---------------------------------------------------------------------------

def test_ensure_pool_mints_missing_keeps_active(tmp_path):
    state = {"remote": [{"id": "k1", "name": "hub-pool-1", "status": "active"}],
             "saved": {"keys": [{"id": "k1", "name": "hub-pool-1", "value": "ak-one"}]}}
    created = []

    def handler(request):
        path = request.url.path
        if path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1"}], "has_more": False})
        if request.method == "GET" and path == "/v1/organization/projects/proj_1/api_keys":
            return httpx.Response(200, json={"data": state["remote"], "has_more": False})
        if request.method == "POST":
            body = json.loads(request.content)
            created.append(body["name"])
            return httpx.Response(201, json={"id": f"key_{len(created)}", "name": body["name"],
                                             "value": f"ak-{body['name']}", "created_at": 2})
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1], "deleted": True})
        raise AssertionError(f"unexpected {request.method} {path}")

    pool_file = tmp_path / "pool.json"
    pool_file.write_text(json.dumps(state["saved"]), encoding="utf-8")
    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with _mock(handler) as client:
        summary = ak.ensure_pool(2, "hub-pool", factory=f,
                                 pool_path=str(pool_file), client=client)
    assert created == ["hub-pool-2"]  # hub-pool-1 kept, never re-minted
    data = json.loads(pool_file.read_text(encoding="utf-8"))
    assert [k["name"] for k in data["keys"]] == ["hub-pool-1", "hub-pool-2"]
    assert data["keys"][0]["value"] == "ak-one"
    assert summary["size"] == 2


def test_ensure_pool_drops_revoked_and_remints(tmp_path):
    state = {"remote": [{"id": "k1", "name": "hub-pool-1", "status": "revoked"}]}
    created = []

    def handler(request):
        path = request.url.path
        if path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1"}], "has_more": False})
        if request.method == "GET" and path == "/v1/organization/projects/proj_1/api_keys":
            return httpx.Response(200, json={"data": state["remote"], "has_more": False})
        if request.method == "POST":
            body = json.loads(request.content)
            created.append(body["name"])
            return httpx.Response(201, json={"id": f"key_{len(created)}", "name": body["name"],
                                             "value": f"ak-{body['name']}", "created_at": 3})
        raise AssertionError(f"unexpected {request.method} {path}")

    pool_file = tmp_path / "pool.json"
    pool_file.write_text(json.dumps(
        {"keys": [{"id": "k1", "name": "hub-pool-1", "value": "ak-dead"}]}),
        encoding="utf-8")
    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with _mock(handler) as client:
        ak.ensure_pool(1, "hub-pool", factory=f, pool_path=str(pool_file), client=client)
    assert created == ["hub-pool-1"]  # the revoked one was replaced fresh
    data = json.loads(pool_file.read_text(encoding="utf-8"))
    assert [k["id"] for k in data["keys"]] == ["key_1"]
    assert data["keys"][0]["value"] == "ak-hub-pool-1"


# ---------------------------------------------------------------------------
# Gateway integration (open_primary egress hook)
# ---------------------------------------------------------------------------

def test_open_primary_pools_ablit(monkeypatch):
    import proxy_gateway as pg

    monkeypatch.setenv("ABLITERATION_POOL_KEYS", "ak-a,ak-b")
    ak.reload_pool()
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    class S:
        primary_api_url = AB
        max_attempts = 1
        retry_base_delay = 0

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            h = {"Authorization": "Bearer configured", "Content-Type": "application/json"}
            r1 = await pg.open_primary(client, {"messages": []}, h, S())
            r2 = await pg.open_primary(client, {"messages": []}, h, S())
            await r1.aclose()
            await r2.aclose()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert seen == ["Bearer ak-a", "Bearer ak-b"]


