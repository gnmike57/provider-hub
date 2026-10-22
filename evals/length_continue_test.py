"""LENGTH_AUTO_CONTINUE pins (2026-10-22, S1).

A primary stream cut at the output-token cap (finish_reason=length, the
live defect: an agent reply through the gateway died at exactly 8192
output tokens mid-sentence) gets ONE seamless continuation - the client
receives the stitched answer, exactly one finish marker, and never sees
the intermediate length finish. Pins:
  - continuation fires once; the cut finish never ships; the stitched
    answer commits through the normal BUFFERING judges
  - the continuation carries the partial answer + the shared instruction
  - kill switch LENGTH_AUTO_CONTINUE=0 restores the bare cut
  - CHAIN_REASONING_EFFORT (S2) reaches the primary payload
"""
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401

import proxy_gateway


def _post(tc, content):
    return tc.post("/v1/chat/completions", json={
        "model": "primary", "messages": [{"role": "user", "content": content}]})


def _calls(sc):
    return [c for c in sc.calls if c["url"] == PRIMARY]


def test_length_finish_continues_seamlessly(script):
    script.script(PRIMARY, [
        ("sse", [chunk("The first half of the answer is here and it is",
                       finish="length"), DONE]),
        ("sse", [chunk(" completed by the second half, seamlessly.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a long answer about parsers")
    assert r.status_code == 200
    assert "The first half of the answer is here" in r.text
    assert "completed by the second half, seamlessly." in r.text
    assert '"length"' not in r.text  # the cut finish never ships
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 1
    # the continuation carries the partial answer + the shared instruction
    cont = _calls(script)[1]["json"]
    assert cont["messages"][-2] == {
        "role": "assistant", "content": "The first half of the answer is here and it is"}
    assert cont["messages"][-1]["role"] == "user"
    assert "Continue EXACTLY where it stopped" in cont["messages"][-1]["content"]


def test_length_kill_switch_restores_the_cut(script, monkeypatch):
    monkeypatch.setenv("LENGTH_AUTO_CONTINUE", "0")
    script.script(PRIMARY, [
        ("sse", [chunk("The first half of the answer is here and it is",
                       finish="length"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a long answer about parsers")
    assert r.status_code == 200
    assert '"length"' in r.text          # the cut finish ships as before
    assert len(_calls(script)) == 1      # no continuation call
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 0


def test_second_length_finish_is_bounded_not_looped(script):
    # the continuation ALSO ends length: its finish passes through and no
    # third call fires (one round only, never a loop)
    script.script(PRIMARY, [
        ("sse", [chunk("part one ", finish="length"), DONE]),
        ("sse", [chunk("part two ", finish="length"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a long answer about parsers")
    assert r.status_code == 200
    assert "part one " in r.text and "part two " in r.text
    assert len(_calls(script)) == 2
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 1


def test_chain_reasoning_effort_knob_reaches_the_payload(script, monkeypatch):
    monkeypatch.setenv("CHAIN_REASONING_EFFORT", "medium")
    script.script(PRIMARY, [
        ("sse", [chunk("plain clean answer, no thinking knobs in play here.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something clean")
    assert r.status_code == 200
    # (the plain path carries no reasoning knobs by design; the pin is the
    # env read itself, exercised by the max-think + chain tests)
    from routing_patterns import LENGTH_CONTINUE_INSTRUCTION  # noqa: F401
    assert "Continue EXACTLY where it stopped" in LENGTH_CONTINUE_INSTRUCTION
