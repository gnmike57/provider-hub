"""T4.2 fan-out: plan.subtasks run as semaphore-bounded parallel specialists.

Pins (ledger T4.2, edits #8-#9):
  - a plan with subtasks fans out one run_specialist clone per subtask,
    each seeing ONLY its own subtask text as sanitized_worker_prompt;
  - all artifacts are joined (ordered, sectioned) into the single slot and
    the deliverable assembles fails-closed-clean;
  - a subtask whose upstream keeps 5xx-ing does not sink its siblings
    (per-subtask retry belongs to run_specialist/open_fallback; the
    fan-out records the loss and completes the rest);
  - no subtasks -> the single-worker path is byte-for-byte unchanged;
  - metrics: fanout_total counts fan-out executions (1 per request),
    fanout_stages_total counts completed subtask calls.
"""

import json

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


def test_fanout_runs_all_subtasks_and_assembles(gw, script):
    plan = _plan_payload(
        subtasks=["analyze function foo", "analyze function bar", "write the harness"])
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [
        _worker_answer("ARTIFACT-ONE"),
        _worker_answer("ARTIFACT-TWO"),
        _worker_answer("ARTIFACT-THREE"),
    ])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    assert resp.status_code == 200
    data = resp.json()
    assert "ARTIFACT-ONE" in data["deliverable"]
    assert "ARTIFACT-TWO" in data["deliverable"]
    assert "ARTIFACT-THREE" in data["deliverable"]
    assert SLOT not in data["deliverable"]
    # three specialist calls, each prompted with ONLY its own subtask
    worker_calls = [c for c in script.calls if c["url"] == WORKER]
    assert len(worker_calls) == 3
    prompts = [c["json"]["messages"][-1]["content"] for c in worker_calls]
    assert prompts == ["analyze function foo", "analyze function bar",
                       "write the harness"]
    assert proxy_gateway._METRICS["fanout_total"] == 1
    assert proxy_gateway._METRICS["fanout_stages_total"] == 3


def test_no_subtasks_keeps_single_worker_path(gw, script):
    plan = _plan_payload()  # no subtasks key at all
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [_worker_answer("single artifact body")])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    assert resp.status_code == 200
    assert "single artifact body" in resp.json()["deliverable"]
    worker_calls = [c for c in script.calls if c["url"] == WORKER]
    assert len(worker_calls) == 1
    assert proxy_gateway._METRICS["fanout_total"] == 0


def test_failed_subtask_does_not_sink_siblings(gw, script):
    plan = _plan_payload(subtasks=["doomed analysis", "resilient analysis"])
    script.script(PRIMARY, [_orchestrator(plan)])
    # subtask 1: capacity exhausted (open_fallback retries then raises);
    # subtask 2: answers on its first call.
    script.script(WORKER, [
        ("status", 503, {"error": "cap"}), ("status", 503, {"error": "cap"}),
        ("status", 503, {"error": "cap"}), ("status", 503, {"error": "cap"}),
        _worker_answer("SURVIVOR-ARTIFACT"),
    ])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    assert resp.status_code == 200
    deliverable = resp.json()["deliverable"]
    assert "SURVIVOR-ARTIFACT" in deliverable
    assert "doomed analysis" in deliverable  # the lost subtask is sectioned
    assert proxy_gateway._METRICS["fallback_errors_total"] > 0


def test_empty_subtask_list_falls_back_to_single(gw, script):
    plan = _plan_payload(subtasks=[])
    script.script(PRIMARY, [_orchestrator(plan)])
    script.script(WORKER, [_worker_answer("solo artifact")])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "q"}]})
    assert resp.status_code == 200
    assert "solo artifact" in resp.json()["deliverable"]
    assert proxy_gateway._METRICS["fanout_total"] == 0
