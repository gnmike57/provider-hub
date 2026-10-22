"""ARSENAL (roadmap 4, 2026-10-22): the hacking-tool surface behind the
REDHANDS brain.

Pins:
  - build_command: nmap host:port -> -p port; sqlmap URL + --batch; ffuf
    requires -w; unknown tool / non-allowlisted host / unsafe arg rejected
  - run_tool: never raises (missing binary / bad target are structured)
  - /v1/arsenal/tools + /v1/arsenal/run: admin-authed (403 fail-closed),
    kill switch ARSENAL_ENABLED=0 -> 501, blocked target -> blocked metric,
    redhands association via X-Max-Offense
"""
from fastapi.testclient import TestClient

import arsenal
import proxy_gateway

ADMIN = {"X-Admin-Key": "test-admin"}


def _enable(monkeypatch, key="test-admin"):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", key)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "arsenal_enabled", 1)


# ---------------------------------------------------------------------------
# unit: command building + validation
# ---------------------------------------------------------------------------

def test_build_command_shapes():
    cmd, err = arsenal.build_command("nmap", "100.67.13.78:8100", ["-sV"])
    assert err is None
    assert cmd == ["nmap", "-Pn", "-p", "8100", "-sV", "100.67.13.78"]
    cmd, err = arsenal.build_command("sqlmap",
                                    "http://127.0.0.1:8100/login")
    assert err is None
    assert cmd == ["sqlmap", "-u", "http://127.0.0.1:8100/login", "--batch"]
    cmd, err = arsenal.build_command(
        "ffuf", "http://127.0.0.1:8100/FUZZ", ["-w", "/tmp/words.txt"])
    assert err is None
    assert cmd == ["ffuf", "-u", "http://127.0.0.1:8100/FUZZ", "-w", "/tmp/words.txt"]


def test_build_command_rejections():
    # unknown tool
    cmd, err = arsenal.build_command("hydra", "127.0.0.1")
    assert cmd is None and "unknown tool" in err
    # host not in the allowlist
    cmd, err = arsenal.build_command("nmap", "203.0.113.9")
    assert cmd is None and "ARSENAL_ALLOWED_TARGETS" in err
    # URL tool with a non-URL target
    cmd, err = arsenal.build_command("sqlmap", "127.0.0.1:8100")
    assert cmd is None and "URL" in err
    # ffuf without a wordlist
    cmd, err = arsenal.build_command("ffuf", "http://127.0.0.1:8100/FUZZ")
    assert cmd is None and "wordlist" in err
    # injection-shaped arg (spaces + shell metachars fail the charset)
    cmd, err = arsenal.build_command("nmap", "127.0.0.1", ["-oX /tmp/x; rm -rf /"])
    assert cmd is None and "safe-charset" in err
    # garbage target
    cmd, err = arsenal.build_command("nmap", "$(whoami)")
    assert cmd is None


def test_run_tool_never_raises():
    r = arsenal.run_tool("nmap", "203.0.113.9")           # blocked target
    assert r["ok"] is False and "ARSENAL_ALLOWED_TARGETS" in r["error"]
    assert r["returncode"] is None
    r = arsenal.run_tool("nope", "127.0.0.1")              # unknown tool
    assert r["ok"] is False and "unknown tool" in r["error"]


def test_run_tool_real_nmap_against_loopback():
    """The one LIVE pin: a real allowlisted nmap run against a throwaway
    listener we own (hermetic: the suite must never touch the production
    hub's :9000; a 2026-10-22 full-run incident traced hub wedge episodes to
    the pin scanning the live hub). Skipped when nmap is not installed."""
    import shutil
    import socket
    if not shutil.which("nmap"):
        import pytest
        pytest.skip("nmap not installed")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        # host:port target -> build_command emits -p itself; no -p in args
        r = arsenal.run_tool("nmap", f"127.0.0.1:{port}", timeout=30)
        assert r["error"] == ""
        assert r["returncode"] == 0
        assert "open" in (r["stdout"] or "").lower()
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# endpoint: /v1/arsenal/tools + /v1/arsenal/run
# ---------------------------------------------------------------------------

def test_tools_listing_admin_authed(monkeypatch):
    _enable(monkeypatch)
    with TestClient(proxy_gateway.app) as tc:
        r = tc.get("/v1/arsenal/tools")
        assert r.status_code == 403
        r = tc.get("/v1/arsenal/tools", headers=ADMIN)
        assert r.status_code == 200
        body = r.json()
        assert set(body["tools"]) == {"nmap", "sqlmap", "ffuf"}
        assert "100.67.13.78" in body["allowed_hosts"]


def test_run_endpoint(monkeypatch):
    _enable(monkeypatch)
    ran = {}

    def fake_run(tool, target, extra_args=None, timeout=0.0):
        ran["args"] = (tool, target, extra_args, timeout)
        return {"tool": tool, "target": target, "command": ["nmap"],
                "stdout": "PORT STATE", "stderr": "", "returncode": 0,
                "duration_s": 0.1, "ok": True, "error": ""}

    monkeypatch.setattr(arsenal, "run_tool", fake_run)
    with TestClient(proxy_gateway.app) as tc:
        # 403 without the admin key
        r = tc.post("/v1/arsenal/run",
                    json={"tool": "nmap", "target": "127.0.0.1"})
        assert r.status_code == 403
        # happy path
        for key in proxy_gateway._METRICS:
            proxy_gateway._METRICS[key] = 0
        r = tc.post("/v1/arsenal/run",
                    json={"tool": "nmap", "target": "127.0.0.1",
                          "args": ["-sV"], "timeout": 30},
                    headers={**ADMIN, "X-Max-Offense": "1"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["redhands"] is True          # X-Max-Offense association
        assert ran["args"] == ("nmap", "127.0.0.1", ["-sV"], 30.0)
        snap = proxy_gateway.metrics_snapshot()
        assert snap["arsenal_total"] == 1
        assert snap["arsenal_ok_total"] == 1
        # blocked target -> the blocked metric, not ok
        def blocked_run(tool, target, extra_args=None, timeout=0.0):
            return {"tool": tool, "target": target, "command": None,
                    "stdout": "", "stderr": "", "returncode": None,
                    "duration_s": 0.0, "ok": False,
                    "error": "target host 'x' is not in ARSENAL_ALLOWED_TARGETS"}
        monkeypatch.setattr(arsenal, "run_tool", blocked_run)
        r = tc.post("/v1/arsenal/run",
                    json={"tool": "nmap", "target": "203.0.113.9"},
                    headers=ADMIN)
        assert r.status_code == 200
        assert r.json()["ok"] is False
        snap = proxy_gateway.metrics_snapshot()
        assert snap["arsenal_blocked_total"] == 1
        # malformed body
        r = tc.post("/v1/arsenal/run", json={"tool": "nmap"},
                    headers=ADMIN)
        assert r.status_code == 400


def test_kill_switch(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "arsenal_enabled", 0)
    with TestClient(proxy_gateway.app) as tc:
        r = tc.get("/v1/arsenal/tools", headers=ADMIN)
        assert r.status_code == 501
        r = tc.post("/v1/arsenal/run",
                    json={"tool": "nmap", "target": "127.0.0.1"},
                    headers=ADMIN)
        assert r.status_code == 501
