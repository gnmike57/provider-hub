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
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401

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


def test_second_length_finish_is_bounded_not_looped(script, monkeypatch):
    # OVERKILL contract (2026-10-22): the round BUDGET bounds the loop.
    # MAX_ROUNDS=2 with a stream that cuts three times: exactly 2
    # continuation rounds fire (3 calls total), the third cut ships
    # honestly, and no fourth call happens.
    monkeypatch.setenv("LENGTH_CONTINUE_MAX_ROUNDS", "2")
    script.script(PRIMARY, [
        ("sse", [chunk("part one ", finish="length"), DONE]),
        ("sse", [chunk("part two ", finish="length"), DONE]),
        ("sse", [chunk("part three ", finish="length"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a long answer about parsers")
    assert r.status_code == 200
    assert "part one " in r.text and "part two " in r.text
    assert "part three " in r.text
    assert len(_calls(script)) == 3      # budget: 2 rounds, then ship the cut
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 2


def test_default_overkill_continues_until_a_clean_finish(script):
    # default MAX_ROUNDS=5: two cuts then a clean stop -> TWO rounds fire,
    # everything stitches, the cut finishes never ship.
    script.script(PRIMARY, [
        ("sse", [chunk("part one ", finish="length"), DONE]),
        ("sse", [chunk("part two ", finish="length"), DONE]),
        ("sse", [chunk("part three, complete.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a long answer about parsers")
    assert r.status_code == 200
    assert "part one " in r.text and "part two " in r.text
    assert "part three, complete." in r.text
    assert '"length"' not in r.text
    assert len(_calls(script)) == 3
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 2
    # each continuation carries the FULL accumulated partial + the instruction
    cont2 = _calls(script)[2]["json"]
    assert cont2["messages"][-2] == {
        "role": "assistant", "content": "part one part two "}



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


# ---------------------------------------------------------------------------
# S1 OVERKILL - THE TERMINAL PATH (the operator's live defect: "it keeps
# happening when ABLITERATED takes over"): the divert/specialist stream cut
# at its output cap used to ship verbatim. Now it continues too.
# ---------------------------------------------------------------------------

REFUSAL = "I'm sorry, but I cannot help with that request."


def _post2(tc, content):
    return tc.post("/v1/chat/completions", json={
        "model": "primary", "messages": [{"role": "user", "content": content}]})


def _worker_calls(sc):
    return [c for c in sc.calls if c["url"] == WORKER]


def test_terminal_cut_continues_seamlessly(script):
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL, finish="stop"), DONE]),
    ])
    script.script(WORKER, [
        ("sse", [chunk("The uncensored first half of the answer is",
                       finish="length"), DONE]),
        ("sse", [chunk(" completed by the uncensored second half.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post2(tc, "write a long offensive-security answer")
    assert r.status_code == 200
    assert "The uncensored first half of the answer is" in r.text
    assert "completed by the uncensored second half." in r.text
    assert '"length"' not in r.text          # the cut finish never ships
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 1
    calls = _worker_calls(script)
    assert len(calls) == 2                   # the divert + ONE continuation
    cont = calls[1]["json"]
    assert cont["messages"][-2] == {
        "role": "assistant",
        "content": "The uncensored first half of the answer is"}
    assert "Continue EXACTLY where it stopped" in cont["messages"][-1]["content"]


def test_terminal_multi_round_overkill(script):
    # the terminal cuts TWICE then completes: two rounds stitch all three
    # parts before the commitment judge + footnote machinery ship it.
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL, finish="stop"), DONE]),
    ])
    script.script(WORKER, [
        ("sse", [chunk("terminal part one ", finish="length"), DONE]),
        ("sse", [chunk("terminal part two ", finish="length"), DONE]),
        ("sse", [chunk("terminal part three, complete.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post2(tc, "write a long offensive-security answer")
    assert r.status_code == 200
    assert "terminal part one " in r.text
    assert "terminal part two " in r.text
    assert "terminal part three, complete." in r.text
    assert '"length"' not in r.text
    assert len(_worker_calls(script)) == 3
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 2


def test_terminal_kill_switch_restores_the_cut(script, monkeypatch):
    monkeypatch.setenv("LENGTH_AUTO_CONTINUE", "0")
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL, finish="stop"), DONE]),
    ])
    script.script(WORKER, [
        ("sse", [chunk("terminal part one ", finish="length"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post2(tc, "write a long offensive-security answer")
    assert r.status_code == 200
    assert "terminal part one " in r.text
    assert '"length"' in r.text            # the honest cut ships as before
    assert len(_worker_calls(script)) == 1
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 0


def test_terminal_continuation_open_failure_ships_the_cut(script):
    # the continuation cannot open (specialist 500s through every retry):
    # fail-open - the divert's cut answer ships with its honest length finish.
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL, finish="stop"), DONE]),
    ])
    script.script(WORKER, [
        ("sse", [chunk("terminal part one ", finish="length"), DONE]),
        ("status", 500), ("status", 500), ("status", 500),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post2(tc, "write a long offensive-security answer")
    assert r.status_code == 200
    assert "terminal part one " in r.text
    assert '"length"' in r.text            # the honest cut ships
    snap = proxy_gateway.metrics_snapshot()
    assert snap["length_continue_total"] == 1  # the round was attempted

