"""/v1/computer (Phase 3, T3.0): the Agent TARS runner endpoint.

  - gated: COMPUTER_USE_ENABLED=0 (the default) -> 501;
  - authed: X-Admin-Key required once ADMIN_API_KEY is set (403 otherwise);
  - the subprocess is scripted via monkeypatched asyncio.create_subprocess_exec
    (no node, no browser in the suite);
  - the LAST stdout line is the JSON envelope -> {"ok","result","verified",
    "steps"}; a failed runner or garbage output -> 502 with detail[:300].
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import script  # noqa: F401  (fixture import)

BODY = {
    "instruction": "open the target and read /etc/hostname",
    "url": "http://127.0.0.1:8102/",
    "verify": "hostname content visible",
}


class _FakeProc:
    def __init__(self, stdout=b"", returncode=0):
        self._out = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._out, b""


def _enable(monkeypatch, stdout=b""):
    captured = []

    async def _fake_exec(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})
        if isinstance(stdout, Exception):
            raise stdout
        return _FakeProc(stdout)

    monkeypatch.setattr(proxy_gateway.SETTINGS, "computer_use_enabled", 1)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return captured


OK_ENVELOPE = json.dumps({
    "ok": True, "result": "hostname read: gx10-lab",
    "verified": True, "steps": [{"action": "navigate", "caption": "the page",
                                "verdict": "yes"}],
}).encode()


def test_computer_disabled_501(script):  # noqa: F811
    """Default off: 501 before ANY subprocess spawn."""
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/computer", json=BODY)
    assert r.status_code == 501
    assert "COMPUTER_USE_ENABLED" in r.json()["detail"]


def test_computer_requires_admin(script, monkeypatch):
    """Wrong/missing X-Admin-Key -> 403 (F17); the runner never spawns."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "computer_use_enabled", 1)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
    spawned = []

    async def _fake_exec(*args, **kwargs):
        spawned.append(args)
        return _FakeProc(b"{}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    with TestClient(proxy_gateway.app) as tc:
        assert tc.post("/v1/computer", json=BODY).status_code == 403
        assert tc.post("/v1/computer", json=BODY,
                       headers={"X-Admin-Key": "wrong"}).status_code == 403
    assert spawned == []


def test_computer_happy_path(script, monkeypatch):
    """Authed + enabled: node tars/computer_task.mjs spawned with the exact
    flags; the last stdout line parses into the response envelope."""
    captured = _enable(monkeypatch, OK_ENVELOPE)
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/computer", json=BODY,
                    headers={"X-Admin-Key": "adm-test"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["verified"] is True
    assert "hostname read" in data["result"]
    assert data["steps"] and data["steps"][0]["verdict"] == "yes"
    args = captured[0]["args"]
    # node resolves via shutil.which (full path) or falls back to "node"
    assert str(args[0]).lower().endswith("node.exe") or args[0] == "node"
    assert args[1].endswith("computer_task.mjs")
    flags = list(args)
    for i, a in enumerate(flags):
        if a == "--url":
            assert flags[i + 1] == BODY["url"]
        if a == "--instruction":
            assert flags[i + 1] == BODY["instruction"]
        if a == "--verify":
            assert flags[i + 1] == BODY["verify"]
    assert "--json" in flags and "--headless" in flags


def test_computer_verify_fail_reports_false(script, monkeypatch):
    """verified:false from the runner is reported honestly (200 + false) -
    the RETRY lives inside computer_task.mjs (T3.1), not the endpoint."""
    envelope = json.dumps({
        "ok": True, "result": "could not see the hostname",
        "verified": False, "steps": []}).encode()
    _enable(monkeypatch, envelope)
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/computer", json=BODY,
                    headers={"X-Admin-Key": "adm-test"})
    assert r.status_code == 200
    assert r.json()["verified"] is False


def test_computer_runner_failure_502(script, monkeypatch):
    """A crashed runner (non-zero exit / garbage stdout) -> 502 with the
    detail capped at 300 chars."""
    _enable(monkeypatch, b"not json at all\n")
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/computer", json=BODY,
                    headers={"X-Admin-Key": "adm-test"})
    assert r.status_code == 502
    assert len(r.json()["error"]) <= 300


def test_computer_task_mjs_selftest_loop():
    """T3.1 verify-each-act loop, exercised in the REAL node module,
    hermetically (--selftest: no browser, no network, no node_modules):
    pass-first; fail-then-pass (one retry, both attempts recorded);
    fail-twice (aborts with BOTH captions in steps)."""
    import os
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        ["node", os.path.join(root, "tars", "computer_task.mjs"), "--selftest"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-300:]
    envelopes = [json.loads(l) for l in proc.stdout.strip().splitlines()
                 if l.strip().startswith("{")]
    assert len(envelopes) == 3, proc.stdout[-300:]
    pass_first, fail_then_pass, fail_twice = envelopes
    # pass-first: one verified step
    assert pass_first["ok"] is True and pass_first["verified"] is True
    assert len(pass_first["steps"]) == 1
    assert pass_first["steps"][0]["verdict"] == "yes"
    # fail-then-pass: the retry fires ONCE, both attempts recorded
    assert fail_then_pass["ok"] is True and fail_then_pass["verified"] is True
    assert len(fail_then_pass["steps"]) == 2
    assert fail_then_pass["steps"][0]["verdict"] == "no"
    assert fail_then_pass["steps"][1]["verdict"] == "yes"
    # fail-twice: aborts with BOTH captions in steps
    assert fail_twice["ok"] is False and fail_twice["verified"] is False
    assert len(fail_twice["steps"]) == 2
    assert all(s["caption"] for s in fail_twice["steps"])
    assert all(s["verdict"] == "no" for s in fail_twice["steps"])
    assert "failed verification twice" in fail_twice["result"]
