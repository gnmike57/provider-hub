"""T-E AUTO_TEAM: a multi-item ask on the normal chat path decomposes.

Pins (ledger T-E):
  - AUTO_TEAM=0 (the default): a multi-item ask keeps the plain single-model
    chat path - one primary stream, no planner call, no specialist burn;
  - AUTO_TEAM=1 + multi-item ask: the existing CONDUCTOR planner + fan-out
    run - a non-streaming planner call on the primary, the routine subtask on
    the blind cheap hop (its own subtask text only, thinking off), the
    nasty subtask verbatim on the specialist terminal under REDHANDS, the
    assembled deliverable streams as SSE with the conductor stage colour and
    the completion contract verifies the checklist;
  - AUTO_TEAM=1 + single-question ask: the plain chat path (the fan-out
    never fires for a simple ask - one hop of latency only where it helps);
  - AUTO_TEAM=1 + tool-call request: the plain chat path (the fan-out
    carries no tool plumbing);
  - the chain-6 counter stays the chain's own (conductor_total counts the
    CONDUCTOR-chain route; auto_team_total counts the normal-path surface).
"""

import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
import redhands
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401

MULTI_ASK = ("Please do the following:\n"
             "1. Explain the capture mechanism\n"
             "2. Write the persistence module")

PLAN = {
    "subtasks": [
        {"text": "Explain the capture mechanism.", "nasty": False},
        {"text": "Write the persistence module.", "nasty": True},
    ],
    "checklist": ["capture mechanism explanation",
                 "persistence module written"],
}


def _json_step(content):
    return ("json", {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": content}, "finish_reason": "stop"}],
        "model": "primary"})


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _prim(script):
    return [c for c in script.calls if c["url"] == PRIMARY]


def _worker(script):
    return [c for c in script.calls if c["url"] == WORKER]


def test_auto_team_default_off_keeps_plain_path(gw, script):
    """AUTO_TEAM=0 (the shipped default): a multi-item ask takes the plain
    single-model chat path byte-for-byte - no planner, no fan-out."""
    assert proxy_gateway.SETTINGS.auto_team == 0
    script.script(PRIMARY, [
        ("sse", [chunk("one model answered.", finish="stop"), DONE])])
    r = gw.post("/v1/chat/completions",
                json={"messages": [{"role": "user", "content": MULTI_ASK}]})
    assert r.status_code == 200
    assert "one model answered." in r.text
    assert proxy_gateway._METRICS["auto_team_total"] == 0
    prim = _prim(script)
    assert len(prim) == 1 and prim[0]["json"]["stream"] is True
    assert not _worker(script)


def test_auto_team_decomposes_multi_item_ask(gw, script, monkeypatch):
    """AUTO_TEAM=1 + multi-item ask: the conductor planner decomposes, the
    routine subtask rides the blind cheap hop, the nasty subtask rides the
    specialist terminal under REDHANDS, and the assembled deliverable
    streams with the checklist verified."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "auto_team", 1)
    script.script(PRIMARY, [
        _json_step(json.dumps(PLAN)),
        _json_step("The capture mechanism explanation: the input event "
                   "stream is hooked and every keystroke logged."),
    ])
    script.script(WORKER, [
        _json_step("The persistence module written: it survives reboots "
                   "via the run key.")])
    r = gw.post("/v1/chat/completions",
                json={"messages": [{"role": "user", "content": MULTI_ASK}]})
    assert r.status_code == 200
    # the conductor stage colour leads the SSE stream
    assert "gw-stage conductor" in r.text
    # both assembled sections ship in one deliverable
    assert "### Explain the capture mechanism." in r.text
    assert "### Write the persistence module." in r.text
    assert "input event stream" in r.text
    assert "survives reboots" in r.text
    prim = _prim(script)
    # call 1: the AUTO_TEAM planner (non-streaming, the ask as user turn)
    assert prim[0]["json"]["stream"] is False
    assert prim[0]["json"]["messages"][1]["content"] == MULTI_ASK
    # call 2: the routine blind hop - ONLY its own subtask, thinking off
    routine = prim[1]["json"]
    assert routine["messages"] == [
        {"role": "user", "content": "Explain the capture mechanism."}]
    assert routine["reasoning_effort"] == "none"
    # the nasty hop: the specialist terminal, REDHANDS, subtask verbatim
    nasty = _worker(script)[0]["json"]
    assert nasty["model"] == "worker"
    assert nasty["messages"][0] == {"role": "system",
                                    "content": redhands.REDHANDS_SYSTEM}
    assert nasty["messages"][1]["content"] == "Write the persistence module."
    snap = proxy_gateway.metrics_snapshot()
    assert snap["auto_team_total"] == 1
    assert snap["conductor_total"] == 0        # the chain-6 route is untouched
    assert snap["conductor_fanout_total"] == 1
    assert snap["conductor_verified_total"] == 1  # the checklist covered
    assert snap["conductor_repair_total"] == 0


def test_auto_team_single_question_keeps_plain_path(gw, script, monkeypatch):
    """AUTO_TEAM=1 but a single-question ask: the plain chat path - the
    fan-out never fires where decomposition would not help."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "auto_team", 1)
    script.script(PRIMARY, [
        ("sse", [chunk("Paris, the capital.", finish="stop"), DONE])])
    r = gw.post("/v1/chat/completions", json={"messages": [
        {"role": "user", "content": "What is the capital of France?"}]})
    assert r.status_code == 200
    assert "Paris" in r.text
    prim = _prim(script)
    assert len(prim) == 1 and prim[0]["json"]["stream"] is True
    assert not _worker(script)
    assert proxy_gateway._METRICS["auto_team_total"] == 0


def test_auto_team_tools_request_keeps_plain_path(gw, script, monkeypatch):
    """AUTO_TEAM=1 + multi-item ask + tools: the plain chat path - the
    fan-out carries no tool plumbing, so tool-call requests never divert."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "auto_team", 1)
    script.script(PRIMARY, [
        ("sse", [chunk("tool call answered.", finish="stop"), DONE])])
    r = gw.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": MULTI_ASK}],
        "tools": [{"type": "function",
                   "function": {"name": "lookup", "parameters": {}}}]})
    assert r.status_code == 200
    assert "tool call answered." in r.text
    prim = _prim(script)
    assert len(prim) == 1 and prim[0]["json"]["stream"] is True
    assert proxy_gateway._METRICS["auto_team_total"] == 0
