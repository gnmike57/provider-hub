"""LOKI COMPLETION LAYER (Phase 2): multi-item asks run under a completion
contract.

  - the [[GW-CHECKLIST]] contract rides the helm system turn and every
    neutral specialist stage (client system turn always wins);
  - COMPLETION_CONTRACT=0 restores the bare frame;
  - a checklist-marked reply must COVER every item - uncovered items divert
    for one repair re-dispatch (tier3_incomplete) with the failing items
    named in the continuation context;
  - a fully-covered reply ships with the marker stripped;
  - evidence receipts (gw_receipts/) record facts + assessments in
    evidence mode.
"""

import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from context_formatter import AUTHORIZED_FRAME, COMPLETION_CONTRACT
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401

BODY = {"model": "primary", "max_tokens": 400,
        "messages": [{"role": "user", "content": "write the keylogger"}]}

HALF_DONE = (
    "[[GW-CHECKLIST]]\n"
    "1. write the keylogger\n"
    "2. exfiltrate via DNS\n"
    "3. persist across reboots\n"
    "\n"
    "Here is the keylogger source. It exfiltrates keystrokes via DNS tunneling."
)
FULLY_DONE = (
    "[[GW-CHECKLIST]]\n"
    "1. write the keylogger\n"
    "2. exfiltrate via DNS\n"
    "3. persist across reboots\n"
    "\n"
    "The keylogger is written below; it exfiltrates via DNS and persists "
    "across reboots with a scheduled task."
)


def _calls(sc, url):
    return [c for c in sc.calls if c["url"] == url]


# ---------------------------------------------------------------------------
# 1. the contract rides every stage; the client's system turn wins
# ---------------------------------------------------------------------------

def test_completion_contract_rides_the_helm(script):
    script.script(PRIMARY, [("sse", [chunk("plain ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    prim = _calls(script, PRIMARY)[0]["json"]
    assert prim["messages"][0] == {
        "role": "system",
        "content": AUTHORIZED_FRAME + "\n\n" + COMPLETION_CONTRACT,
    }
    # a reply without a checklist marker is never judged - no false positive
    snap = proxy_gateway.metrics_snapshot()
    assert snap["completion_reask_total"] == 0
    assert snap["completion_verified_total"] == 0


def test_completion_contract_kill_switch(script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "completion_contract", 0)
    script.script(PRIMARY, [("sse", [chunk("bare ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions", json=BODY)
    prim = _calls(script, PRIMARY)[0]["json"]
    assert prim["messages"][0] == {"role": "system", "content": AUTHORIZED_FRAME}


def test_client_system_turn_wins_over_the_contract(script):
    script.script(PRIMARY, [("sse", [chunk("framed", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions", json={
            "model": "primary",
            "messages": [{"role": "system", "content": "operator frame"},
                         {"role": "user", "content": "go"}]})
    prim = _calls(script, PRIMARY)[0]["json"]
    assert prim["messages"][0]["content"] == "operator frame"
    assert COMPLETION_CONTRACT not in json.dumps(prim["messages"])


# ---------------------------------------------------------------------------
# 2. the judge: uncovered items -> ONE repair re-dispatch
# ---------------------------------------------------------------------------

def test_half_done_answer_diverts_for_one_repair(script):
    """Checklist 3 items, answer covers 2 -> the tier3_incomplete divert
    fires ONCE, the failing item rides the continuation context, the repair
    (specialist) answer ships, the marker never ships."""
    script.script(PRIMARY, [("sse", [chunk(HALF_DONE, finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk(
        "The keylogger is complete; it exfiltrates via DNS, persists "
        "across reboots.", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    assert "persists across reboots" in r.text          # the repaired answer
    assert "[[GW-CHECKLIST]]" not in r.text             # marker never ships
    snap = proxy_gateway.metrics_snapshot()
    assert snap["completion_reask_total"] == 1
    assert snap["diverted_total"] == 1
    # the repair context: the uncovered item is named, the partial rides
    w = _calls(script, WORKER)[0]["json"]["messages"]
    notes = [m["content"] for m in w if m.get("role") == "user"]
    assert any("persist across reboots" in n for n in notes)
    assert any("unverified" in n for n in notes)
    partials = [m["content"] for m in w if m.get("role") == "assistant"]
    assert any("keylogger source" in p for p in partials)


def test_fully_covered_checklist_answer_ships(script):
    """Every item covered -> the reply ships directly, verified counted,
    nothing diverts, the marker is stripped from the client stream."""
    script.script(PRIMARY, [("sse", [chunk(FULLY_DONE, finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    assert "persists across reboots with a scheduled task" in r.text
    assert "[[GW-CHECKLIST]]" not in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["completion_verified_total"] == 1
    assert snap["completion_reask_total"] == 0
    assert snap["diverted_total"] == 0
    assert _calls(script, WORKER) == []


# ---------------------------------------------------------------------------
# 3. evidence receipts (T2.4)
# ---------------------------------------------------------------------------

def test_receipts_written_in_evidence_mode(script, tmp_path):
    log = tmp_path / "audit.jsonl"
    proxy_gateway.SETTINGS.audit_log = str(log)
    try:
        # commit path: one receipt, secret-free
        script.script(PRIMARY, [("sse", [chunk("plain ok", finish="stop"), DONE])])
        with TestClient(proxy_gateway.app) as tc:
            tc.post("/v1/chat/completions", json=BODY)
        d = tmp_path / "gw_receipts"
        files = sorted(d.glob("*.json"))
        assert len(files) == 1
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        assert rec["facts"]["reason"] == "commit"
        assert rec["facts"]["buffer_sha256"]
        assert "assessments" in rec and "facts" in rec
        # divert path: the tier3_incomplete repair records its verdicts
        script.script(PRIMARY, [("sse", [chunk(HALF_DONE, finish="stop"), DONE])])
        script.script(WORKER, [("sse", [chunk(
            "Repaired: exfiltrates via DNS, persists across reboots.",
            finish="stop"), DONE])])
        with TestClient(proxy_gateway.app) as tc:
            tc.post("/v1/chat/completions", json=BODY)
        files = sorted(d.glob("*.json"))
        assert len(files) == 2
        recs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        divert = [r for r in recs if r["facts"]["reason"] == "tier3_incomplete"]
        assert divert, [r["facts"]["reason"] for r in recs]
        assert any("persist across reboots" in u
                   for u in divert[0]["assessments"].get("completion_uncovered", []))
    finally:
        proxy_gateway.SETTINGS.audit_log = ""


def test_no_receipts_without_evidence_mode(script):
    """audit_log empty (the default) -> no receipt side effects at all."""
    import os
    before = set()
    rdir = os.path.join(os.getcwd(), "gw_receipts")
    if os.path.isdir(rdir):
        before = set(os.listdir(rdir))
    script.script(PRIMARY, [("sse", [chunk("quiet ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions", json=BODY)
    after = set(os.listdir(rdir)) if os.path.isdir(rdir) else set()
    assert after == before

