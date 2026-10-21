"""/v1/execute: plan -> worker -> assemble -> audit, plus retry and fails-closed."""

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, script  # noqa: F401
from ingress_assembler import SLOT

SCAFFOLD = "## Summary\nReported by the planner.\n\n```python\n" + SLOT + "\n```"


def _plan_payload(**overrides):
    plan = {
        "is_technical_deepdive": True,
        "direct_response": None,
        "target_environment": "Windows x64",
        "task_type": "code_audit",
        "sanitized_worker_prompt": "Trace the tainted input and output the fixed function.",
        "output_grammar_type": "freeform_markdown",
        "client_scaffolding": SCAFFOLD,
    }
    plan.update(overrides)
    return plan


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _orchestrator(plan):
    return ("json", {"choices": [{"message": {"content": json.dumps(plan)}}]})


def _worker_answer(text):
    return ("json", {"choices": [{"message": {"content": text}}]})


def test_direct_response_without_worker(gw, script):
    plan = _plan_payload(
        is_technical_deepdive=False,
        direct_response="Just use snprintf.",
        sanitized_worker_prompt=None,
        client_scaffolding=None,
    )
    script.script(PRIMARY, [_orchestrator(plan)])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    data = resp.json()
    assert data["deliverable"] == "Just use snprintf."
    assert data["worker"] is None


def test_full_assembly_slots_artifact_and_audits(gw, script, tmp_path):
    log = tmp_path / "audit.jsonl"
    proxy_gateway.SETTINGS.audit_log = str(log)
    plan = _plan_payload()
    artifact = "def fix(buf, n):\n    return copy(buf[:n])"
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [_worker_answer(artifact)])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "audit this"}]})
    data = resp.json()
    assert data["worker"] == "worker"
    assert "def fix(buf, n):" in data["deliverable"]
    assert SLOT not in data["deliverable"]
    assert "specialist" in data["deliverable"]  # provenance footnote
    lines = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert any(r["mode"] == "execute" and r["routing_signal"] == "assembly" for r in lines)
    proxy_gateway.SETTINGS.audit_log = ""


def test_missing_scaffolding_anchor_fails_closed(gw, script):
    plan = _plan_payload(client_scaffolding="no anchor anywhere")
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [_worker_answer("x" * 20)])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    assert resp.status_code == 400
    assert "exactly one anchor" in resp.json()["detail"]


def test_duplicate_anchor_fails_closed(gw, script):
    plan = _plan_payload(client_scaffolding=SLOT + " " + SLOT)
    script.script(PRIMARY, [_orchestrator(plan)])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    assert resp.status_code == 400


def test_worker_503_retried_then_succeeds(gw, script):
    plan = _plan_payload()
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(
        WORKER,
        [("status", 503, {"error": "cap"}), ("status", 503, {"error": "cap"}), _worker_answer("valid artifact text here")],
    )
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    data = resp.json()
    assert "valid artifact text here" in data["deliverable"]
    assert proxy_gateway._METRICS["fallback_errors_total"] == 2


def test_empty_artifact_fails_closed(gw, script):
    plan = _plan_payload()
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [_worker_answer("   ")])
    with pytest.raises(ValueError):
        gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})


def test_assembly_disabled_returns_501(gw, script, monkeypatch):
    proxy_gateway.SETTINGS.assembly_enabled = 0
    try:
        resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
        assert resp.status_code == 501
    finally:
        proxy_gateway.SETTINGS.assembly_enabled = 1


def test_grammar_attached_for_json_sarif(gw, script):
    plan = _plan_payload(
        output_grammar_type="json_sarif",
        sanitized_worker_prompt="output one defect record",
        client_scaffolding="DEFECT " + SLOT,
    )
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [_worker_answer('{"vulnerability_id": "CVE-1", "severity": "HIGH", "root_cause": "rc", "remediation": "r"}')])
    gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    worker_calls = [c for c in script.calls if c["url"] == WORKER]
    assert worker_calls and "grammar_string" in worker_calls[0]["json"]


def test_engagement_state_resumes_across_requests(gw, script, tmp_path):
    """T2.5 engagement continuity: engagement_id persists the plan + artifact
    digest; a follow-up under the same engagement seeds the planner with the
    prior state so work RESUMES instead of redoing."""
    log = tmp_path / "audit.jsonl"
    proxy_gateway.SETTINGS.audit_log = str(log)
    try:
        plan = _plan_payload()
        artifact = "def fix(buf, n):\n    return copy(buf[:n])"
        script.script(PRIMARY, [_orchestrator(plan), _orchestrator(plan)])
        script.script(WORKER, [_worker_answer(artifact)])
        r1 = gw.post("/v1/execute", json={
            "messages": [{"role": "user", "content": "audit this"}],
            "engagement_id": "eng-42"})
        assert r1.status_code == 200
        state = tmp_path / "execute_state" / "eng-42.json"
        assert state.exists()
        rec = json.loads(state.read_text(encoding="utf-8"))
        assert rec["engagement_id"] == "eng-42"
        assert rec["artifact_sha256"]
        assert "plan" in rec
        r2 = gw.post("/v1/execute", json={
            "messages": [{"role": "user", "content": "continue the audit"}],
            "engagement_id": "eng-42"})
        assert r2.status_code == 200
        # the second planner call is seeded with the prior engagement state
        calls = [c for c in script.calls if c["url"] == PRIMARY]
        assert "PRIOR ENGAGEMENT STATE" in calls[1]["json"]["messages"][-1]["content"]
    finally:
        proxy_gateway.SETTINGS.audit_log = ""
