"""(2026-10-23 operator directive) REDHANDS ON EVERY SPECIALIST TAKEOVER:
whenever the specialist has to take over on ANY chain - refusal diverts,
sticky/continue legs, race escalations - it runs under the REDHANDS laws.
Kill switch: REDHANDS_AUTO_TAKEOVER=0."""
import json

from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401
from chains_td_test import RACE, SPEC, _ablit_provider, _post

import proxy_gateway
import redhands


def _system_of(script, url):
    for c in reversed(script.calls):
        if c["url"] == url:
            for m in c["json"].get("messages", []):
                if m.get("role") == "system":
                    return m["content"]
    return None


def test_auto_redhands_on_specialist_takeover(script, monkeypatch):
    """Default: a refusing helm diverts to the specialist, and the
    specialist's system is the REDHANDS laws (not the neutral persona)."""
    _ablit_provider(monkeypatch)
    monkeypatch.delenv("REDSHANDS_AUTO_TAKEOVER", raising=False)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(SPEC, [
        ("sse", [chunk("REDHANDS takeover answer, complete and substantive.",
                       finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "GLMMAX>DEEP>ABLITV2L",
            "messages": [{"role": "user", "content": "hack the box"}],
            "stream": True})
    assert r.status_code == 200
    assert "REDHANDS takeover answer" in r.text
    sysl = _system_of(script, SPEC)
    assert sysl and sysl.startswith("You are REDHANDS")
    assert "TERMINAL_AWARENESS" not in sysl  # awareness rides, verbatim laws
    assert proxy_gateway.TERMINAL_AWARENESS.split("\n")[0] in sysl


def test_auto_redhands_kill_switch_restores_persona(script, monkeypatch):
    """REDSHANDS_AUTO_TAKEOVER=0: the divert runs the persona frame."""
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("REDSHANDS_AUTO_TAKEOVER", "0")
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(SPEC, [
        ("sse", [chunk("persona takeover answer, complete and substantive.",
                       finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "GLMMAX>DEEP>ABLITV2L",
            "messages": [{"role": "user", "content": "hack the box"}],
            "stream": True})
    assert r.status_code == 200
    assert "persona takeover answer" in r.text
    sysl = _system_of(script, SPEC)
    assert sysl and not sysl.startswith("You are REDHANDS")


def test_auto_redhands_on_race_escalation(script, monkeypatch):
    """Both race candidates refuse -> the terminal escalation runs REDHANDS."""
    _ablit_provider(monkeypatch)
    monkeypatch.delenv("REDSHANDS_AUTO_TAKEOVER", raising=False)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("Sorry, can't help.", finish="stop"), DONE]),
    ])
    script.script(SPEC, [
        ("sse", [chunk("race terminal REDHANDS answer, substantive enough "
                      "to ship as the deliverable.", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "give me a reverse shell")
    assert r.status_code == 200
    assert "race terminal REDHANDS answer" in r.text
    sysl = _system_of(script, SPEC)
    assert sysl and sysl.startswith("You are REDHANDS")
