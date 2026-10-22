"""Multi-account credential pool (account_pool.py) - hermetic regression tests.

Adapted from the operator's Hive/Abliteration weighted-cascade reference
(2026-10-21): token buckets, weighted-least-in-flight, sticky route hashing,
429 cooldown, 401/402/405 depletion, fail-closed egress hook, gateway wiring.

No network: httpx.MockTransport everywhere; the pool file lives in the
session quarantine dir (conftest redirects ACCOUNT_POOL_FILE at import time
via the env-var switch below).
"""

import asyncio
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

import account_pool
import proxy_gateway

# The pool file lives in the session quarantine dir: conftest redirects
# ACCOUNT_POOL_FILE at import time (same pattern as the abliteration pool),
# so the singleton starts EMPTY. Tests load accounts per-case via
# ACCOUNT_POOL_KEYS (re-read on every reload - see account_pool._reload).


@pytest.fixture(autouse=True)
def _pool_env(monkeypatch):
    """Hermetic pool state per test: env override + fresh singleton."""
    monkeypatch.setenv("ACCOUNT_POOL_ENABLED", "1")
    monkeypatch.delenv("ACCOUNT_POOL_KEYS", raising=False)
    account_pool.reload_pool()
    yield
    account_pool.reload_pool()


def _load_env(monkeypatch, pairs):
    monkeypatch.setenv("ACCOUNT_POOL_KEYS", ",".join(pairs))
    account_pool.reload_pool()


# ---------------------------------------------------------------------------
# AccountKey semantics
# ---------------------------------------------------------------------------

def test_token_bucket_refills_and_blocks_bursts(monkeypatch):
    monkeypatch.setenv("ACCOUNT_POOL_COOLDOWN_S", "5.0")
    a = account_pool.AccountKey("hive", "k", "t", max_rps=2.0)
    assert a.try_acquire() and a.try_acquire()
    # Bucket empty now (2.0 rps, fresh): the third immediate acquire fails.
    assert not a.try_acquire()
    assert a.available()  # not depleted, not cooling - just out of tokens


def test_429_puts_the_account_on_cooldown_not_depleted():
    a = account_pool.AccountKey("hive", "k", "t", max_rps=10.0)
    outcome = a.note_result(429)
    assert outcome == "cooldown"
    assert not a.depleted
    assert not a.available()
    assert a.summary()["cooling_down"] is True


def test_401_402_405_deplete_the_account():
    for status in (401, 402, 405):
        a = account_pool.AccountKey("hive", "k", "t", max_rps=10.0)
        outcome = a.note_result(status)
        assert outcome == "depleted"
        assert a.depleted
        assert not a.available()


def test_200_and_transport_errors_change_nothing():
    a = account_pool.AccountKey("hive", "k", "t", max_rps=10.0)
    assert a.note_result(200) is None
    assert a.note_result(None) is None
    assert a.available() and not a.depleted


def test_summary_redacts_the_key_value():
    a = account_pool.AccountKey("hive", "sk-very-secret-value-0123456789", "t")
    s = a.summary()
    assert "sk-very-secret-value-0123456789" not in json.dumps(s)
    assert s["redacted"].endswith("6789") and "..." in s["redacted"]
# ---------------------------------------------------------------------------
# Selection: sticky hash + WLIF + rotation
# ---------------------------------------------------------------------------

def test_sticky_route_hash_is_deterministic(monkeypatch):
    # Deep buckets: the assertions here are about HASHING, not throughput.
    monkeypatch.setenv("ACCOUNT_POOL_HIVE_RPS", "1000")
    _load_env(monkeypatch, ["hive:k1", "hive:k2", "hive:k3", "hive:k4"])
    picks = {account_pool.POOL.acquire(
        "https://api-cdn.thehive.ai/api/v3/chat/completions",
        route_key="route-X").key for _ in range(5)}
    assert len(picks) == 1  # same route -> same account, every time


def test_wlif_balances_in_flight_load(monkeypatch):
    monkeypatch.setenv("ACCOUNT_POOL_HIVE_RPS", "1000")
    _load_env(monkeypatch, ["hive:k1", "hive:k2"])
    url = "https://api-cdn.thehive.ai/api/v3/chat/completions"
    pool = account_pool.POOL
    sticky = pool.acquire(url, route_key="burst")
    seen = {sticky.key}
    # Drain the sticky account's bucket: WLIF must hand the next pick to the
    # OTHER token-ready account instead of failing or hammering the drained one.
    sticky.tokens = 0.0
    other = pool.acquire(url, route_key="burst")
    assert other is not None
    seen.add(other.key)
    pool.release(sticky)
    pool.release(other)
    assert len(seen) == 2, seen


def test_depleted_accounts_are_skipped_and_none_when_all_dead(monkeypatch):
    _load_env(monkeypatch, ["hive:k1", "hive:k2"])
    url = "https://api-cdn.thehive.ai/api/v3/chat/completions"
    pool = account_pool.POOL
    for a in pool._pools["hive"]:
        a.depleted = True
    assert pool.acquire(url) is None  # all dead -> caller keeps its key
    # Revive one: it serves again.
    pool._pools["hive"][0].depleted = False
    assert pool.acquire(url) is not None


def test_env_pairs_accept_bare_prefixed_keys(monkeypatch):
    _load_env(monkeypatch, [
        "ak_ablit-bare", "cat_nano-bare", "c2VjcmV0==",
        "hive:explicit-hive"])
    pools = account_pool.POOL._pools
    assert [a.key for a in pools.get("ablit", [])] == ["ak_ablit-bare"]
    assert [a.key for a in pools.get("nano", [])] == ["cat_nano-bare"]
    assert any(a.key == "explicit-hive" for a in pools.get("hive", []))
    # the bare ==-suffixed secret sniffed to hive
    assert any(a.key == "c2VjcmV0==" for a in pools.get("hive", []))


def test_unknown_provider_urls_never_pick(monkeypatch):
    _load_env(monkeypatch, ["hive:k1"])
    assert account_pool.POOL.acquire(
        "http://127.0.0.1:4000/v1/chat/completions") is None


# ---------------------------------------------------------------------------
# Egress hook: fail-closed contract
# ---------------------------------------------------------------------------

def test_routed_headers_passthrough_identity_when_pool_empty(monkeypatch):
    _load_env(monkeypatch, ["nano:k-only"])  # no hive accounts
    h = {"Authorization": "Bearer configured", "Content-Type": "application/json"}
    out, acct = account_pool.routed_headers(
        h, "https://api-cdn.thehive.ai/api/v3/chat/completions")
    assert out is h  # the INPUT object, untouched
    assert acct is None
    assert out["Authorization"] == "Bearer configured"


def test_routed_headers_overrides_authorization_when_pooled(monkeypatch):
    _load_env(monkeypatch, ["hive:pooled-secret"])
    h = {"Authorization": "Bearer configured"}
    out, acct = account_pool.routed_headers(
        h, "https://api-cdn.thehive.ai/api/v3/chat/completions")
    assert out is not h
    assert out["Authorization"] == "Bearer pooled-secret"
    assert h["Authorization"] == "Bearer configured"  # input never mutated
    assert acct.key == "pooled-secret"


def test_routed_headers_disabled_pool_is_passthrough(monkeypatch):
    _load_env(monkeypatch, ["hive:k1"])
    monkeypatch.setenv("ACCOUNT_POOL_ENABLED", "0")
    h = {"Authorization": "Bearer configured"}
    out, acct = account_pool.routed_headers(
        h, "https://api-cdn.thehive.ai/api/v3/chat/completions")
    assert out is h and acct is None


def test_corrupt_pool_file_degrades_to_empty(monkeypatch, tmp_path):
    bad = tmp_path / "pool.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("ACCOUNT_POOL_FILE", str(bad))
    account_pool.reload_pool()
    assert account_pool.POOL.acquire(
        "https://api-cdn.thehive.ai/api/v3/chat/completions") is None
    assert account_pool.pool_summary()["size"] == 0
# ---------------------------------------------------------------------------
# Hot reload + gateway wiring (open_primary / open_fallback) + metrics
# ---------------------------------------------------------------------------

def test_pool_file_additions_hot_reload_by_mtime(monkeypatch, tmp_path):
    pf = tmp_path / "pool.json"
    pf.write_text(json.dumps(
        {"accounts": [{"provider": "hive", "key": "k1", "label": "a"}]}),
        encoding="utf-8")
    monkeypatch.setenv("ACCOUNT_POOL_FILE", str(pf))
    account_pool.reload_pool()
    url = "https://api-cdn.thehive.ai/api/v3/chat/completions"
    assert account_pool.POOL.acquire(url).key == "k1"
    # Rewrite with a NEW key (different size guarantees an mtime+size change).
    pf.write_text(json.dumps(
        {"accounts": [{"provider": "hive", "key": "k2-longer", "label": "b"}]}),
        encoding="utf-8")
    assert account_pool.POOL.acquire(url).key == "k2-longer"
    assert account_pool.POOL.acquire(url).key == "k2-longer"  # reload stuck


def _sse_ok():
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=b"data: [DONE]\n\n")


def test_open_primary_rotates_hive_accounts_on_429(monkeypatch):
    """The adapted-cascade promise: a 429 from one Hive account rotates to a
    fresh account on the next attempt instead of hammering the same key."""
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        if len(seen_auth) == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _sse_ok()

    _load_env(monkeypatch, ["hive:acct-a", "hive:acct-b", "hive:acct-c"])
    monkeypatch.setenv("ACCOUNT_POOL_COOLDOWN_S", "60.0")
    account_pool.reload_pool()
    proxy_gateway._METRICS["account_pool_acquired_total"] = 0
    proxy_gateway._METRICS["account_pool_cooldown_total"] = 0

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            s = proxy_gateway.Settings()
            s.primary_api_url = "https://api-cdn.thehive.ai/api/v3/chat/completions"
            s.max_attempts = 3
            s.retry_base_delay = 0.0
            resp = await proxy_gateway.open_primary(
                client, {"model": "m"},
                {"Authorization": "Bearer configured"}, s)
            assert resp.status_code == 200
            await resp.aclose()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(seen_auth) == 2
    assert seen_auth[0] != seen_auth[1], "429 must rotate to a different account"
    assert all(a in ("Bearer acct-a", "Bearer acct-b", "Bearer acct-c")
               for a in seen_auth)
    assert proxy_gateway._METRICS["account_pool_acquired_total"] >= 2
    assert proxy_gateway._METRICS["account_pool_cooldown_total"] == 1
def test_open_fallback_uses_pooled_ablit_credential(monkeypatch):
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        return _sse_ok()

    _load_env(monkeypatch, ["ablit:pooled-ablit"])
    proxy_gateway._METRICS["account_pool_acquired_total"] = 0

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            s = proxy_gateway.Settings()
            s.fallback_api_url = "https://api.abliteration.ai/v1/chat/completions"
            s.fallback_api_key = "ak-configured"
            s.fallback_max_attempts = 1
            s.retry_base_delay = 0.0
            proxy_gateway.BREAKER = proxy_gateway.SpecialistCircuitBreaker()
            resp = await proxy_gateway.open_fallback(
                client, {"model": "m"},
                {"Authorization": "Bearer ak-configured"}, s)
            assert resp.status_code == 200
            await resp.aclose()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert seen_auth == ["Bearer pooled-ablit"]
    assert proxy_gateway._METRICS["account_pool_acquired_total"] == 1


def test_local_hub_urls_stay_on_the_configured_key(monkeypatch):
    """A non-pooled URL (the gx10 hub) must never be re-keyed."""
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        return _sse_ok()

    _load_env(monkeypatch, ["hive:k1", "ablit:k2"])
    proxy_gateway._METRICS["account_pool_fallback_total"] = 0

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            s = proxy_gateway.Settings()
            s.fallback_api_url = "http://worker.test/v1/chat/completions"
            s.fallback_api_key = "ak-configured"
            s.fallback_max_attempts = 1
            s.retry_base_delay = 0.0
            proxy_gateway.BREAKER = proxy_gateway.SpecialistCircuitBreaker()
            resp = await proxy_gateway.open_fallback(
                client, {"model": "m"},
                {"Authorization": "Bearer ak-configured"}, s)
            assert resp.status_code == 200
            await resp.aclose()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert seen_auth == ["Bearer ak-configured"]
    assert proxy_gateway._METRICS["account_pool_fallback_total"] == 1


def test_healthz_reports_the_pool_without_leaking_secrets(monkeypatch):
    _load_env(monkeypatch, ["hive:sk-healthz-probe-0123456789"])
    with TestClient(proxy_gateway.app) as tc:
        block = tc.get("/healthz").json()["config"]["account_pool"]
    blob = json.dumps(block)
    assert "sk-healthz-probe-0123456789" not in blob
    assert block["size"] >= 1
    assert all("redacted" in a for a in block["accounts"])



