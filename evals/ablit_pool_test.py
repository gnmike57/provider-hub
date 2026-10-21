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


# ---------------------------------------------------------------------------
# Edge cases (2026-10-21 bulletproofing pass)
# ---------------------------------------------------------------------------

def test_env_of_only_blank_entries_is_empty_pool(monkeypatch):
    # "size 0" env: every entry blank -> empty pool, hot path stays quiet.
    monkeypatch.setenv("ABLITERATION_POOL_KEYS", " , ,")
    ak.reload_pool()
    assert ak.next_key() == ""
    h = {"Authorization": "Bearer configured"}
    out = ak.pooled_headers(h, AB)
    assert out is h  # passthrough, not even copied
    assert out["Authorization"] == "Bearer configured"


def test_malformed_pool_file_degrades_to_empty(tmp_path, monkeypatch):
    # Corrupt JSON, a JSON array, and a dict with a non-list "keys" must all
    # degrade to an empty pool instead of crashing the hot path.
    monkeypatch.delenv("ABLITERATION_POOL_KEYS", raising=False)
    monkeypatch.setattr(ak, "POOL_PATH", str(tmp_path / "pool.json"))
    for body in ["not json {{{", "[]", '[1, 2, 3]',
                 json.dumps({"keys": {"value": "x"}})]:
        (tmp_path / "pool.json").write_text(body, encoding="utf-8")
        ak.reload_pool()
        assert ak.next_key() == ""
        summary = ak.pool_summary()
        assert summary["size"] == 0
        assert summary["source"] == "file"


def test_pool_file_without_saved_at_still_reloads(tmp_path, monkeypatch):
    # Legacy/hand-edited files carry no `saved_at`; reload detection must key
    # on file identity (mtime+size), not that field.
    pf = tmp_path / "pool.json"
    monkeypatch.delenv("ABLITERATION_POOL_KEYS", raising=False)
    monkeypatch.setattr(ak, "POOL_PATH", str(pf))
    pf.write_text(json.dumps({"keys": [{"id": "a", "value": "ak-v1"}]}),
                  encoding="utf-8")
    ak.reload_pool()
    assert ak.next_key() == "ak-v1"
    # Rewrite without saved_at and with a DIFFERENT length (size is part of
    # the spec even if mtime resolution were coarse).
    pf.write_text(json.dumps({"keys": [{"id": "a", "value": "ak-v2-longer"}]}),
                  encoding="utf-8")
    ak.reload_pool()
    assert ak.next_key() == "ak-v2-longer"


def test_redact_tolerates_none_and_tiny_values():
    assert ak._redact(None) == ""          # used to crash (len(None))
    assert ak._redact("") == ""
    assert ak._redact("ab") == "ab..."     # short value, no slice errors
    assert ak._redact("abcdefghij") == "abcde...ghij"
    # A pool entry whose value is null must not crash the summary either.
    s = ak.pool_summary_from_keys([{"id": "k", "name": "n", "value": None}])
    assert s["keys"][0]["redacted"] == ""


def test_factory_list_pagination_without_cursor_stops():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if request.url.path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1"}],
                                             "has_more": False})
        # has_more=True but NO last_id: a broken page. The old loop spun
        # forever; it must stop after this single page instead.
        return httpx.Response(200, json={"data": [{"id": "a"}], "has_more": True})

    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with _mock(handler) as client:
        assert [k["id"] for k in f.list_keys(client)] == ["a"]
    assert calls["n"] == 2  # project discovery + exactly one key page


def test_ensure_pool_rejects_bad_sizes_before_any_request(tmp_path):
    def handler(request):
        raise AssertionError(
            f"no request may be made, got {request.method} {request.url.path}")

    pool_file = tmp_path / "pool.json"
    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    for bad in (0, -3, True):  # True: bool must not slip through as size 1
        with pytest.raises(ValueError):
            with _mock(handler) as client:
                ak.ensure_pool(bad, "hub-pool", factory=f,
                               pool_path=str(pool_file), client=client)
    assert not pool_file.exists()  # nothing was written either


def test_ensure_pool_persists_partial_on_mid_run_failure(tmp_path):
    # Part 4 - crash safety. hub-pool-1 exists and is active; minting
    # hub-pool-2 succeeds, minting hub-pool-3 fails with a 500. Everything
    # confirmed so far (the existing entry plus the successful mint) must be
    # persisted BEFORE the error propagates - hub-pool-2's full value is
    # shown exactly once and would otherwise be orphaned forever. The
    # failure path must also revoke NOTHING (revocation belongs to the
    # surplus trim, which only runs after every mint succeeded).
    remote = [{"id": "k1", "name": "hub-pool-1", "status": "active"}]
    created = []
    revoked = []

    def handler(request):
        path = request.url.path
        if path == "/v1/organization/projects":
            return httpx.Response(200, json={"data": [{"id": "proj_1"}],
                                             "has_more": False})
        if request.method == "GET" and \
                path == "/v1/organization/projects/proj_1/api_keys":
            return httpx.Response(200, json={"data": remote, "has_more": False})
        if request.method == "POST":
            body = json.loads(request.content)
            created.append(body["name"])
            if body["name"] == "hub-pool-3":
                return httpx.Response(500, json={"error": "mint boom"})
            return httpx.Response(201, json={
                "id": f"key_{len(created)}", "name": body["name"],
                "value": f"ak-full-{body['name']}", "created_at": 4})
        if request.method == "DELETE":
            revoked.append(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1],
                                             "deleted": True})
        raise AssertionError(f"unexpected {request.method} {path}")

    pool_file = tmp_path / "pool.json"
    pool_file.write_text(json.dumps(
        {"keys": [{"id": "k1", "name": "hub-pool-1", "value": "ak-one"}]}),
        encoding="utf-8")
    f = ak.KeyFactory(base_url="https://api.abliteration.ai/v1", key="sk-test")
    with pytest.raises(httpx.HTTPStatusError):
        with _mock(handler) as client:
            ak.ensure_pool(3, "hub-pool", factory=f,
                           pool_path=str(pool_file), client=client)
    assert created == ["hub-pool-2", "hub-pool-3"]  # died on the 2nd mint
    assert revoked == []  # failure path never revokes healthy keys
    data = json.loads(pool_file.read_text(encoding="utf-8"))
    assert [k["name"] for k in data["keys"]] == ["hub-pool-1", "hub-pool-2"]
    # the once-shown full value survived the crash
    assert data["keys"][1]["value"] == "ak-full-hub-pool-2"
    assert data["project_id"] == "proj_1"


