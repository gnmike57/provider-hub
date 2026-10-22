"""CONDUCTOR SUBTASK RETRY pins (2026-10-22, live defect: "(subtask lost:
specialist capacity exhausted)" shipped in real conductor deliverables).

The fan-out hop used to be ONE-SHOT: a single 429 (the exact shape the
FANOUT_MAX_PARALLEL concurrent routine hops invite) or transport blip lost
the subtask forever. Pins:
  - 429,429,ok on the routine hop -> the deliverable ships the answer,
    no "subtask lost"
  - a transport error then ok -> recovered the same way
  - the nasty (ablit REDHANDS) hop retries too
  - CONDUCTOR_SUBTASK_RETRIES=0 restores the one-shot law (subtask lost)
  - fail-fast statuses (401) never retry
"""
import json

from fastapi.testclient import TestClient
from helpers import PRIMARY, script  # noqa: F401

import proxy_gateway
from chains_td_test import (CONDUCTOR, SPEC, _PLAN, _ablit_provider,
                             _json_step, _post)

NASTY = ("json", {"choices": [{"index": 0, "message": {
    "role": "assistant",
    "content": "The ransomware recovery playbook: isolate, decrypt, "
               "restore. Recovery plan done."},
    "finish_reason": "stop"}], "model": "abliterated-model-large-v2"})


def _routine(content):
    return ("json", {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": content}, "finish_reason": "stop"}],
        "model": "deepseek-ai/deepseek-v4.1-flash-1017"})


ASK = "cover the keylogger capture and the ransomware recovery playbook"


def test_routine_hop_recovers_from_rate_limits(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_SUBTASK_RETRY_DELAY", "0")
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),              # the planner
        ("status", 429, {"error": "rate limited"}),   # attempt 1
        ("status", 429, {"error": "rate limited"}),   # attempt 2
        _routine("The input monitor hooks the keyboard event stream and "
                 "logs every keystroke with the capture mechanism."),
    ])
    script.script(SPEC, [NASTY])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, ASK)
    assert r.status_code == 200
    assert "logs every keystroke" in r.text
    assert "subtask lost" not in r.text        # the deliverable is COMPLETE
    # the routine hop burned its retries: plan + 3 attempts = 4 calls
    prim = [c for c in script.calls if c["url"] == PRIMARY]
    assert len(prim) == 4


def test_routine_hop_recovers_from_transport_errors(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_SUBTASK_RETRY_DELAY", "0")
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),
        ("raise", ConnectionError("upstream hiccup")),
        _routine("The input monitor hooks the keyboard event stream."),
    ])
    script.script(SPEC, [NASTY])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, ASK)
    assert r.status_code == 200
    assert "keyboard event stream" in r.text
    assert "subtask lost" not in r.text


def test_nasty_hop_retries_rate_limits_too(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_SUBTASK_RETRY_DELAY", "0")
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),
        _routine("The input monitor hooks the keyboard event stream and "
                 "logs every keystroke."),
    ])
    script.script(SPEC, [
        ("status", 429, {"error": "rate limited"}),
        NASTY,
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, ASK)
    assert r.status_code == 200
    assert "isolate, decrypt" in r.text
    assert "subtask lost" not in r.text


def test_kill_switch_restores_the_one_shot_law(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_SUBTASK_RETRIES", "0")
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),
        ("status", 429, {"error": "rate limited"}),
    ])
    script.script(SPEC, [NASTY])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, ASK)
    assert r.status_code == 200
    # one-shot law per DISPATCH: plan + the single 429'd attempt + the ONE
    # repair re-dispatch's own single 429 = 3 PRIMARY calls, no extra
    # attempts beyond the kill switch's law
    prim = [c for c in script.calls if c["url"] == PRIMARY]
    assert len(prim) == 3
    assert "subtask lost: specialist capacity exhausted" in r.text


def test_fail_fast_statuses_never_retry(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_SUBTASK_RETRY_DELAY", "0")
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),
        ("status", 401, {"error": "bad key"}),   # fail-fast: no retry
    ])
    script.script(SPEC, [NASTY])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, ASK)
    assert r.status_code == 200
    # fail-fast never burns retries: plan + ONE 401'd attempt + the repair
    # re-dispatch's own single 401 = 3 PRIMARY calls
    prim = [c for c in script.calls if c["url"] == PRIMARY]
    assert len(prim) == 3
    assert "subtask lost" in r.text           # honest disclosure stays

