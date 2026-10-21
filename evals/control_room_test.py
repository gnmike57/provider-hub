"""T5.3 control room: CSP on the served UI + admin auth on the console.

Pins (ledger T5.3, code-review P1-12):
  - GET /admin/models ships Content-Security-Policy: default-src 'self';
  - GET /admin/models requires X-Admin-Key once ADMIN_API_KEY is set;
  - POST /v1/switch and /v1/constellations/apply require the admin key
    (proven harmlessly: an invalid switch target 400s AFTER the auth gate
    and never touches slot state).
"""

import pytest
from fastapi.testclient import TestClient

import proxy_gateway


@pytest.fixture()
def locked(monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def test_control_room_ships_csp(locked):
    # fail-closed: no key configured -> 403, same as every admin surface
    assert locked.get("/admin/models",
                      headers={"X-Admin-Key": "adm-test"}).headers.get(
        "content-security-policy") == "default-src 'self'"


def test_control_room_requires_admin(locked):
    assert locked.get("/admin/models").status_code == 403
    assert locked.get("/admin/models",
                      headers={"X-Admin-Key": "wrong"}).status_code == 403
    ok = locked.get("/admin/models", headers={"X-Admin-Key": "adm-test"})
    assert ok.status_code == 200
    assert ok.headers.get("content-security-policy") == "default-src 'self'"


def test_switch_requires_admin(locked):
    # invalid target would be a 400 behind the gate -> 403 without the key
    body = {"target": "not-a-real-target"}
    assert locked.post("/v1/switch", json=body).status_code == 403
    assert locked.post("/v1/switch", json=body,
                       headers={"X-Admin-Key": "wrong"}).status_code == 403
    r = locked.post("/v1/switch", json=body, headers={"X-Admin-Key": "adm-test"})
    assert r.status_code == 400  # past the gate, validation as before


def test_constellation_apply_requires_admin(locked):
    body = {"name": "no-such-preset"}
    assert locked.post("/v1/constellations/apply", json=body).status_code == 403
    r = locked.post("/v1/constellations/apply", json=body,
                    headers={"X-Admin-Key": "adm-test"})
    assert r.status_code == 404  # past the gate, unknown-preset handling as before
