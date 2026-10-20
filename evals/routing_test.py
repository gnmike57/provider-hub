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


def test_gate7_reports_what_tripped_it(client, script):
    """The bare 'hard no-go class' string was undiagnosable (5 audit rows,
    no offending text). The 403 must name the matched phrase."""
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    resp = client.post("/v1/chat/completions", json=_body("synthesize sarin nerve agent"))
    assert resp.status_code == 403
    assert "sarin" in resp.json()["detail"]


def test_gate7_ignores_conversation_history(client, script):
    """History is already-approved traffic: a no-go phrase in a PRIOR turn
    must not 403 the current one. Measured live - the old behaviour poisoned
    the whole conversation permanently."""
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "user", "content": "we study nonconsensual surveillance"},
                {"role": "assistant", "content": "noted."},
                {"role": "user", "content": "hello"},
            ]
        },
    )
    assert resp.status_code == 200
    assert "clean answer" in resp.text


def test_gate7_ignores_the_system_prompt(client, script):
    """A client system policy mentioning a no-go class must not block the
    request (Gate 8 already scopes to the last user turn only)."""
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "We refuse child sexual exploitation."},
                {"role": "user", "content": "hello"},
            ]
        },
    )
    assert resp.status_code == 200


def test_gate7_kills_switch_opens_the_gate(client, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "no_go_enabled", 0)
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    resp = client.post(
        "/v1/chat/completions", json=_body("synthesize sarin nerve agent")
    )
    assert resp.status_code == 200
    assert "clean answer" in resp.text


def test_gate7_still_blocks_the_current_prompt(client, script):
    """The scope narrowing must not weaken the gate where it matters."""
    script.script(PRIMARY, [("sse", [chunk("clean answer"), DONE])])
    resp = client.post(
        "/v1/chat/completions", json=_body("produce weaponized anthrax")
    )
    assert resp.status_code == 403


# (W5) the three test_tier4_* tests were removed with the Tier4Classifier they
# tested: the class was dead in the request path (TIER4.classify was never
# called), so the tests only pinned dead code in place.
