"""T-E /v1/verify (RARV-C): plan -> fan-out -> coverage judge -> council ->
tamper-evident receipt.

Pins (ledger T-E):
  - admin gate: X-Admin-Key required once ADMIN_API_KEY is set (403
    otherwise - fail-closed; the planner is never called);
  - body contract: instruction required (400); verify_checklist must be a
    list of strings (400);
  - happy path: the planner decomposes, the fan-out specialists answer, the
    coverage judge passes, both council reviewers agree VERIFIED ->
    verified: true, one sealed receipt line appended;
  - a fixed verify_checklist wins over the planner's checklist;
  - an uncovered checklist item -> coverage_ok false, uncovered names it,
    verified false (fail-closed);
  - council disagreement / an unreachable reviewer -> verified false
    (verify_council_disagree_total for the disagreement); on the
    constellation flashes the two reviewers ride DIFFERENT cheap models
    (GLM + DeepSeek) on the same provider binding;
  - planner failure degrades to the single whole-instruction subtask (200,
    never 502), recorded as planner_failed in the receipt facts;
  - tamper evidence: the receipt chain validates, seals differ per line;
    mutating a fact breaks that line's seal; forging a seal breaks the
    chain at that line;
  - a receipt write failure never kills the verdict;
  - metrics: verify_total / verify_verified_total / verify_receipt_failed_total.
"""

import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, script  # noqa: F401

INSTR = "verify the incident postmortem for the deploy"

SINGLE_PLAN = {
    "subtasks": [{"text": "Check the deploy stamp.", "nasty": False}],
    "checklist": ["deploy stamp verified"],
}

TWO_PLAN = {
    "subtasks": [{"text": "Measure the outage window.", "nasty": False},
                 {"text": "Audit the failover logs.", "nasty": False}],
    "checklist": ["outage window measured", "failover logs audited"],
}

COVERED = "The deploy stamp is verified and it matches the ledger."


def _json(content):
    return ("json", {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": content}, "finish_reason": "stop"}],
        "model": "primary"})


def _happy_steps(plan):
    return [_json(json.dumps(plan)), _json(COVERED),
            _json("VERIFIED"), _json("VERIFIED")]


def _post(gw, **body):
    return gw.post("/v1/verify", json=body, headers={"X-Admin-Key": "adm-test"})


def _prim(script):
    return [c for c in script.calls if c["url"] == PRIMARY]


@pytest.fixture()
def gw(script, tmp_path, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
    monkeypatch.setattr(proxy_gateway.SETTINGS, "audit_log",
                       str(tmp_path / "audit.jsonl"))
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def test_verify_requires_admin_key(gw, script):
    """403 without/with a wrong X-Admin-Key; the planner never fires."""
    assert gw.post("/v1/verify", json={"instruction": "x"}).status_code == 403
    assert gw.post("/v1/verify", json={"instruction": "x"},
                   headers={"X-Admin-Key": "wrong"}).status_code == 403
    assert not _prim(script)
    assert proxy_gateway._METRICS["verify_total"] == 0


def test_verify_body_contract(gw, script):
    """instruction is required; verify_checklist must be a list of strings."""
    assert _post(gw).status_code == 400
    assert _post(gw, instruction="   ").status_code == 400
    assert _post(gw, instruction="ok",
                 verify_checklist="nope").status_code == 400
    assert _post(gw, instruction="ok",
                 verify_checklist=["a", 2]).status_code == 400
    assert not _prim(script)
    assert proxy_gateway._METRICS["verify_total"] == 0


def test_verify_happy_path_verifies_and_seals(gw, script):
    """Plan -> fan-out -> judge -> council -> one sealed receipt line."""
    script.script(PRIMARY, [
        _json(json.dumps(TWO_PLAN)),
        _json("The outage window measured 14 minutes end to end."),
        _json("The failover logs audited show the retry storm."),
        _json("VERIFIED"), _json("VERIFIED"),
    ])
    r = _post(gw, instruction=INSTR)
    assert r.status_code == 200
    data = r.json()
    assert data["verified"] is True
    assert data["coverage_ok"] is True
    assert data["uncovered"] == []
    assert data["checklist"] == TWO_PLAN["checklist"]
    assert data["council"] == {"agreement": True,
                               "verdicts": ["VERIFIED", "VERIFIED"]}
    assert data["subtasks"] == [st["text"] for st in TWO_PLAN["subtasks"]]
    assert "### Measure the outage window." in data["evidence"]
    # task_0010 contract aliases
    assert data["gaps"] == []
    assert data["requirements"] == TWO_PLAN["checklist"]
    assert data["receipt_id"] == data["request_id"]
    # the call sequence: planner + 2 blind subtask hops + 2 council reviewers
    prim = _prim(script)
    assert len(prim) == 5
    assert prim[0]["json"]["stream"] is False
    assert prim[0]["json"]["messages"][1]["content"] == INSTR
    assert prim[1]["json"]["messages"] == [
        {"role": "user", "content": "Measure the outage window."}]
    assert prim[3]["json"]["messages"][0]["role"] == "system"
    assert prim[4]["json"]["messages"][0]["role"] == "system"
    # the receipt: one sealed line, chain valid, facts/assessments separated
    path = data["receipt"]["path"]
    assert path.endswith("verify_receipts.jsonl")
    assert data["receipt"]["line"] == 1
    ok, lines = proxy_gateway._verify_receipt_chain_valid(path)
    assert ok and lines == 1
    line = json.loads(open(path, encoding="utf-8").read().splitlines()[0])
    assert line["facts"]["instruction_sha256"]
    assert line["facts"]["checklist"] == TWO_PLAN["checklist"]
    assert line["assessments"]["verified"] is True
    assert "adm-test" not in json.dumps(line)  # secret-free (F9 parity)
    assert proxy_gateway._METRICS["verify_total"] == 1
    assert proxy_gateway._METRICS["verify_verified_total"] == 1
    assert proxy_gateway._METRICS["verify_receipt_failed_total"] == 0


def test_verify_fixed_checklist_wins(gw, script):
    """An explicit verify_checklist is the operator's contract - the
    planner's own checklist never overrides it."""
    script.script(PRIMARY, _happy_steps(SINGLE_PLAN))
    r = _post(gw, instruction="verify the deploy",
              verify_checklist=["deploy stamp matches ledger"])
    assert r.status_code == 200
    data = r.json()
    assert data["checklist"] == ["deploy stamp matches ledger"]
    assert data["coverage_ok"] is True
    assert data["verified"] is True


def test_verify_uncovered_item_fails_closed(gw, script):
    """A checklist item the evidence does not cover: coverage_ok false, the
    uncovered item named, verified false - an incomplete answer is never a
    verified one."""
    plan = {"subtasks": [{"text": "Check the deploy stamp.", "nasty": False}],
            "checklist": ["deploy stamp verified", "rollback plan staged"]}
    script.script(PRIMARY, _happy_steps(plan))
    r = _post(gw, instruction="verify the deploy")
    assert r.status_code == 200
    data = r.json()
    assert data["coverage_ok"] is False
    assert data["uncovered"] == ["2. rollback plan staged"]
    assert data["gaps"] == ["2. rollback plan staged"]
    assert data["verified"] is False
    assert proxy_gateway._METRICS["verify_verified_total"] == 0
    assert proxy_gateway._METRICS["verify_gaps_total"] == 1


def test_verify_council_disagreement_blocks(gw, script):
    """Coverage passes but the two reviewers disagree -> verified false and
    the disagreement counted."""
    script.script(PRIMARY, [
        _json(json.dumps(SINGLE_PLAN)), _json(COVERED),
        _json("VERIFIED"), _json("GAPS: the rollback plan is missing"),
    ])
    r = _post(gw, instruction="verify the deploy")
    assert r.status_code == 200
    data = r.json()
    assert data["coverage_ok"] is True
    assert data["council"] == {"agreement": False,
                               "verdicts": ["VERIFIED", "GAPS"]}
    assert data["verified"] is False
    assert proxy_gateway._METRICS["verify_council_disagree_total"] == 1


def test_verify_council_unavailable_fails_closed(gw, script):
    """A reviewer hop that errors is UNAVAILABLE - the council cannot agree
    and the verdict fails closed."""
    script.script(PRIMARY, [
        _json(json.dumps(SINGLE_PLAN)), _json(COVERED),
        _json("VERIFIED"), ("status", 503, {"error": "reviewer saturated"}),
    ])
    r = _post(gw, instruction="verify the deploy")
    assert r.status_code == 200
    data = r.json()
    assert data["council"]["verdicts"] == ["VERIFIED", "UNAVAILABLE"]
    assert data["council"]["agreement"] is False
    assert data["verified"] is False


def test_verify_planner_failure_degrades_to_single_subtask(gw, script):
    """A dead planner is never a client error: the whole instruction becomes
    the one (routine) subtask, recorded as planner_failed in the facts."""
    script.script(PRIMARY, [
        ("status", 500, {"error": "planner down"}),
        _json(COVERED), _json("VERIFIED"), _json("VERIFIED"),
    ])
    r = _post(gw, instruction="verify the deploy")
    assert r.status_code == 200
    data = r.json()
    assert data["subtasks"] == ["verify the deploy"]
    assert data["checklist"] == []
    assert data["verified"] is True
    line = json.loads(open(data["receipt"]["path"], encoding="utf-8")
                      .read().splitlines()[0])
    assert line["facts"]["planner_failed"] is True


def test_verify_council_rides_two_different_flashes(gw, script, monkeypatch):
    """Reviewer diversity (task_0010): on the constellation flashes the two
    council calls ride DIFFERENT cheap models - GLM and DeepSeek - on the
    same provider binding; a primary outside the pair keeps one hop."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "primary_model",
                       "zai-org/glm-5.3-flash")
    script.script(PRIMARY, _happy_steps(SINGLE_PLAN))
    r = _post(gw, instruction="verify the deploy")
    assert r.status_code == 200
    prim = _prim(script)
    # reviewer 1 rides the primary's own flash, reviewer 2 the OTHER flash
    assert prim[2]["json"]["model"] == "zai-org/glm-5.3-flash"
    assert prim[3]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
    assert r.json()["verified"] is True
    # a primary outside the flash pair: both reviewers keep the helm hop
    monkeypatch.setattr(proxy_gateway.SETTINGS, "primary_model", "primary")
    script.script(PRIMARY, _happy_steps(SINGLE_PLAN))
    r2 = _post(gw, instruction="verify the deploy again")
    prim2 = _prim(script)
    assert prim2[6]["json"]["model"] == "primary"
    assert prim2[7]["json"]["model"] == "primary"
    assert r2.json()["verified"] is True


def test_verify_receipt_tamper_evidence(gw, script):
    """Two verifications chain (distinct seals, line numbers); mutating a
    fact breaks that line's seal; forging a seal breaks the chain there."""
    script.script(PRIMARY, _happy_steps(SINGLE_PLAN))
    r1 = _post(gw, instruction="verify the deploy")
    script.script(PRIMARY, _happy_steps(SINGLE_PLAN))
    r2 = _post(gw, instruction="verify the deploy")
    assert r1.json()["receipt"]["seal"] != r2.json()["receipt"]["seal"]
    assert r2.json()["receipt"]["line"] == 2
    path = r1.json()["receipt"]["path"]
    ok, lines = proxy_gateway._verify_receipt_chain_valid(path)
    assert ok and lines == 2
    original = list(open(path, encoding="utf-8").read().splitlines())
    # tamper 1: rewrite a fact of line 1 -> its own seal no longer matches
    raw = list(original)
    rec = json.loads(raw[0])
    rec["facts"]["instruction_sha256"] = "0" * 64
    raw[0] = json.dumps(rec)
    open(path, "w", encoding="utf-8").write("\n".join(raw) + "\n")
    ok, bad = proxy_gateway._verify_receipt_chain_valid(path)
    assert not ok and bad == 1
    # tamper 2 (fresh copy): forge line 2's seal -> that line breaks
    raw = list(original)
    rec = json.loads(raw[1])
    rec["seal"] = "f" * 64
    raw[1] = json.dumps(rec)
    open(path, "w", encoding="utf-8").write("\n".join(raw) + "\n")
    ok, bad = proxy_gateway._verify_receipt_chain_valid(path)
    assert not ok and bad == 2


def test_verify_receipt_failure_never_kills_the_verdict(gw, script, tmp_path):
    """The receipts dir unwritable: the verdict still returns (seal None,
    line 0) and verify_receipt_failed_total counts the loss."""
    (tmp_path / "gw_receipts").write_text("a file where the dir goes",
                                           encoding="utf-8")
    script.script(PRIMARY, _happy_steps(SINGLE_PLAN))
    r = _post(gw, instruction="verify the deploy")
    assert r.status_code == 200
    data = r.json()
    assert data["verified"] is True
    assert data["receipt"]["seal"] is None
    assert data["receipt"]["line"] == 0
    assert proxy_gateway._METRICS["verify_receipt_failed_total"] == 1
    assert proxy_gateway._METRICS["verify_verified_total"] == 1
