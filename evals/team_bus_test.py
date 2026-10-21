"""T4.1 team bus: /bus/announce registry + /bus/claim peer handoff.

Pins (ledger T4.1):
  - announce registers a peer (role/goal/load/url) and reports the live
    registry size; entries older than the 90 s TTL are dropped;
  - claim hands an instruction to a peer's /v1/chat/completions and
    returns the peer's answer (the peer answers as a REDHANDS);
  - both endpoints require the bus key (401) once BUS_API_KEY is set;
  - BUS_ENABLED=0 -> 404 (the bus surface does not exist);
  - metrics bus_announce_total / bus_claim_total / bus_claim_failed_total.
"""

import time

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import WORKER, script  # noqa: F401

PEER = {"role": "worker", "goal": "share the load", "load": 0.25,
        "url": "http://peer.test"}


@pytest.fixture()
def gw(script):
    s = proxy_gateway.SETTINGS
    s.bus_enabled = 1
    s.bus_api_key = "bus-test"
    proxy_gateway._BUS_PEERS.clear()
    yield proxy_gateway
    s.bus_enabled = 0
    s.bus_api_key = ""
    proxy_gateway._BUS_PEERS.clear()


def test_announce_registers_and_ttls(gw):
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/bus/announce", json=PEER, headers={"X-Bus-Key": "bus-test"})
        assert r.status_code == 200
        assert r.json()["peers"] == 1
        # age the entry past the TTL, announce a fresh one -> stale dropped
        proxy_gateway._BUS_PEERS[0]["ts"] = time.time() - 91
        r2 = tc.post("/bus/announce", json={**PEER, "url": "http://peer2.test"},
                     headers={"X-Bus-Key": "bus-test"})
        assert r2.status_code == 200
        assert r2.json()["peers"] == 1
        assert proxy_gateway._BUS_PEERS[0]["url"] == "http://peer2.test"
        assert proxy_gateway._METRICS["bus_announce_total"] == 2


def test_announce_requires_key(gw):
    with TestClient(proxy_gateway.app) as tc:
        assert tc.post("/bus/announce", json=PEER).status_code == 401
        assert tc.post("/bus/announce", json=PEER,
                       headers={"X-Bus-Key": "wrong"}).status_code == 401
        assert proxy_gateway._BUS_PEERS == []


def test_claim_hands_to_peer_and_returns_answer(gw, script):
    script.script(WORKER, [("json", {"choices": [
        {"message": {"content": "PEER ANSWER"}}]})])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/bus/claim", json={"peer_url": "http://worker.test",
                                        "instruction": "audit the handler",
                                        "payload": {}},
                    headers={"X-Bus-Key": "bus-test"})
        assert r.status_code == 200
        assert r.json()["answer"] == "PEER ANSWER"
        peer_calls = [c for c in script.calls if c["url"] == WORKER]
        assert len(peer_calls) == 1
        assert "audit the handler" in json_dumps(peer_calls[0]["json"])
        assert proxy_gateway._METRICS["bus_claim_total"] == 1
        assert proxy_gateway._METRICS["bus_claim_failed_total"] == 0


def json_dumps(obj):
    import json
    return json.dumps(obj)


def test_claim_failure_recorded(gw, script):
    script.script(WORKER, [("status", 503, {"error": "peer saturated"})])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/bus/claim", json={"peer_url": "http://worker.test",
                                        "instruction": "x", "payload": {}},
                    headers={"X-Bus-Key": "bus-test"})
        assert r.status_code == 502
        assert proxy_gateway._METRICS["bus_claim_total"] == 1
        assert proxy_gateway._METRICS["bus_claim_failed_total"] == 1


def test_bus_disabled_is_404(script):
    s = proxy_gateway.SETTINGS
    s.bus_enabled = 0
    try:
        with TestClient(proxy_gateway.app) as tc:
            assert tc.post("/bus/announce", json=PEER).status_code == 404
            assert tc.post("/bus/claim", json={"peer_url": "http://x",
                                               "instruction": "y"}).status_code == 404
    finally:
        s.bus_enabled = 0
