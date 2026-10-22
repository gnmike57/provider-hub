"""Content-Length relay contract (the asserted twin of _probe_cl.py).

The throwaway probe measured (2026-10-21, this stack):

    no-body     -> content-length: '0'  (explicit header, present)
    empty-bytes -> content-length: '0'  (explicit header, present)
    json        -> content-length: str(len(bytes))  (exact byte length)
    raw-cl0     -> content-length: '0'  (a forced header passes through)

The gateway-visible consequence pinned here: a bodyless POST to
/v1/chat/completions arrives as an EMPTY body and must fail with a clean
400 "invalid JSON body" - not a hang, not a 500, not a partial response.

Run:  python -m pytest evals/cl_test.py -q
"""
import os
import sys

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import proxy_gateway  # noqa: E402
from evals.helpers import Script  # noqa: E402


# ---------------------------------------------------------------------------
# The probe's minimal echo surface, reproduced as a fixture.
# ---------------------------------------------------------------------------
app = FastAPI()


@app.post("/echo")
async def echo(request: Request):
    return {"cl": request.headers.get("content-length")}


CLIENT = TestClient(app)


def test_testclient_sends_content_length_zero_for_no_body():
    """TestClient does NOT omit content-length on a bodyless POST: the probe
    measured an explicit '0', and any gateway logic that trusts the header
    stays correct."""
    assert CLIENT.post("/echo").json() == {"cl": "0"}


def test_testclient_sends_content_length_zero_for_empty_bytes():
    assert CLIENT.post("/echo", content=b"").json() == {"cl": "0"}


def test_testclient_content_length_is_exact_byte_length():
    assert CLIENT.post("/echo", json={"a": 1}).json() == {"cl": "7"}


def test_forced_content_length_zero_header_passes_through():
    """A client-set content-length: 0 is relayed verbatim (never dropped),
    so header-based guard logic cannot be bypassed by omission alone."""
    assert CLIENT.post("/echo", headers={"content-length": "0"}).json() == {"cl": "0"}


# ---------------------------------------------------------------------------
# Gateway-visible consequence: the empty body must fail fast and clean.
# ---------------------------------------------------------------------------


def _wire_gateway(monkeypatch):
    def _make():
        return httpx.AsyncClient(transport=httpx.MockTransport(Script()))

    monkeypatch.setattr(proxy_gateway, "make_client", _make)
    s = proxy_gateway.SETTINGS
    s.primary_api_url, s.primary_api_key, s.primary_model = (
        "http://primary.test/v1/chat/completions", "", "primary")
    s.fallback_api_url, s.fallback_api_key, s.fallback_model = (
        "http://worker.test/v1/chat/completions", "none", "worker")
    s.audit_log = ""
    s.authz_enforced = False
    s.keepalive_url = ""


def test_gateway_empty_body_fails_clean_400(monkeypatch):
    """A bodyless POST reaches the gateway as an empty body and is rejected
    with 400 invalid-JSON - no upstream call, no hang, no 500."""
    _wire_gateway(monkeypatch)
    with TestClient(proxy_gateway.app) as tc:
        r1 = tc.post("/v1/chat/completions")
        r2 = tc.post("/v1/chat/completions", content=b"",
                     headers={"content-length": "0"})
    for resp in (r1, r2):
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid JSON body"