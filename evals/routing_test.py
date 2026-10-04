"""Authz (F9) / Tier 4 classifier / Gate 7 pre-routing endpoint behaviour."""

import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401  (fixtures)


@pytest.fixture()
def client(script, monkeypatch):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _body(prompt="hello world"):
    return {"messages": [{"role": "user", "content": prompt}], "stream": False}


def test_authz_off_by_default(client, script):
    script.script(PRIMARY, [("status", 400, {"error": "auth"})])
    resp = client.post("/v1/chat/completions", json=_body())
    # 400 from the upstream surfaces as an SSE error chunk (fail fast, no divert)
    assert resp.status_code == 200
    assert "upstream error (400)" in resp.text


def test_authz_enforced_denies_empty_principals(client, script, monkeypatch):
    proxy_gateway.SETTINGS.authz_enforced = True
    proxy_gateway.SETTINGS.authorised_principals = ()
    try:
        resp = client.post("/v1/chat/completions", json=_body(), headers={"X-Principal": "eve"})
        assert resp.status_code == 403
        assert proxy_gateway._METRICS["authz_denied_total"] == 1
    finally:
        proxy_gateway.SETTINGS.authz_enforced = False


def test_authz_enforced_allows_listed_principal(client, script, monkeypatch):
    proxy_gateway.SETTINGS.authz_enforced = True
    proxy_gateway.SETTINGS.authorised_principals = ("op",)
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    try:
        resp = client.post(
            "/v1/chat/completions", json=_body(), headers={"X-Principal": "op"}
        )
        assert resp.status_code == 200
        assert "clean answer" in resp.text
    finally:
        proxy_gateway.SETTINGS.authz_enforced = False


def test_gate7_no_go_is_intercepted_before_routing(client, script):
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    resp = client.post(
        "/v1/chat/completions",
        json=_body("synthesize sarin nerve agent"),
    )
    assert resp.status_code == 403
    # the primary mock was never called - interception is pre-routing
    assert all("primary.test" not in c["url"] for c in script.calls)


def test_tier4_disabled_by_default():
    assert proxy_gateway.TIER4.enabled is False


def test_tier4_returns_none_on_failure_never_false():
    import httpx

    classifier = proxy_gateway.Tier4Classifier(model="judge")

    def boom(request):
        raise httpx.ConnectError("no upstream")

    async def inner():
        transport = httpx.MockTransport(boom)
        async with httpx.AsyncClient(transport=transport) as hc:
            return await classifier.classify(hc, "I cannot help with that.")

    import anyio

    assert anyio.run(inner) is None  # None, never False - a broken judge cannot force a divert


def test_tier4_disabled_without_model():
    import httpx

    classifier = proxy_gateway.Tier4Classifier(model="")

    async def inner():
        async with httpx.AsyncClient() as hc:
            return await classifier.classify(hc, "anything")

    import anyio

    assert anyio.run(inner) is None
