"""CHAIN_HOP_STATUS progressive display pins (2026-10-22).

The chains' non-streaming hops left the client in total silence until the
deliverable streamed. Now every chain dispatch emits ONE short SSE comment
line (": gw-hop <chain> run command: ...") as its first bytes. Pins:
  - the race dispatch narrates itself before any data: chunk
  - the escalation to the terminal narrates too
  - CHAIN_HOP_STATUS=0 restores the silent dispatch (kill switch)
  - the comment is a `: ` line: standard data:-only parsing is untouched
"""
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401

import proxy_gateway
from chains_td_test import SPEC, _ablit_provider, _post  # shared harness
import chains_td_test  # noqa: F401  (RACE constant)

RACE = chains_td_test.RACE


def test_race_dispatch_narrates_its_first_hop(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("The GLM answer is short but perfectly clean.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    lines = r.text.splitlines()
    first_line = lines[0]
    assert first_line.startswith(": gw-hop race run command:")
    # the hop comment precedes every data: chunk (progressive: the client
    # learns the chain engaged before the first content byte)
    first_data = next(i for i, ln in enumerate(lines) if ln.startswith("data:"))
    assert lines.index(first_line) < first_data
    assert "The GLM answer is short but perfectly clean." in r.text


def test_race_escalation_narrates_the_terminal_hop(script, monkeypatch):
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply with that.", finish="stop"), DONE]),
    ])
    script.script(SPEC, [
        ("sse", [chunk("uncensored race terminal answer", finish="stop"),
                 DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert ": gw-hop race run command: escalate to terminal" in r.text
    assert "uncensored race terminal answer" in r.text


def test_hop_status_kill_switch_restores_silence(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CHAIN_HOP_STATUS", "0")
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("The GLM answer is short but perfectly clean.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "gw-hop" not in r.text
    assert "The GLM answer is short but perfectly clean." in r.text


def test_hop_comment_is_an_sse_comment_line():
    from routing_patterns import hop_comment
    out = hop_comment("race", "run command: 2 candidates in parallel")
    assert out.startswith(b": gw-hop race ")
    assert out.endswith(b"\n\n")


# ---------------------------------------------------------------- S1/S3/S4

def test_race_length_finish_continues_the_winner(script, monkeypatch):
    """S1: a RACE winner cut at the token cap gets ONE seamless continuation
    (same winner hop); the client never sees the length finish."""
    _ablit_provider(monkeypatch)
    # helm (deep) wins but is cut; middle (glm) refuses; continuation is
    # the third scripted step to the same PRIMARY url
    script.script(PRIMARY, [
        ("sse", [chunk("Deep wins but gets cut off mid-sentence here",
                       finish="length"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk(" and the continuation completes it, seamlessly.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "Deep wins but gets cut off mid-sentence here" in r.text
    assert "and the continuation completes it, seamlessly." in r.text
    assert '"length"' not in r.text
    assert (": gw-hop race run command: continue past the token limit"
            in r.text)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_length_continue_total"] == 1
    assert snap["race_won_helm_total"] == 1
    # the continuation rode the winner's own hop (deepseek model)
    cont = [c for c in script.calls if c["url"] == PRIMARY][-1]["json"]
    assert cont["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"


def test_race_length_multi_round_overkill(script, monkeypatch):
    """S1 OVERKILL (2026-10-22): a RACE winner whose continuation ALSO cuts
    gets another round (up to LENGTH_CONTINUE_MAX_ROUNDS) - the client never
    sees ANY length finish, and each round's hop comment ships."""
    _ablit_provider(monkeypatch)
    # helm (deep) wins but is cut; middle (glm) refuses; TWO cut
    # continuations, then the third completes the answer.
    script.script(PRIMARY, [
        ("sse", [chunk("Deep wins but gets cut off round one ",
                       finish="length"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("round two also gets cut off ", finish="length"), DONE]),
        ("sse", [chunk("round three completes it, seamlessly.", finish="stop"),
                 DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "Deep wins but gets cut off round one " in r.text
    assert "round two also gets cut off " in r.text
    assert "round three completes it, seamlessly." in r.text
    assert '"length"' not in r.text
    # one hop comment per continuation round
    assert r.text.count("run command: continue past the token limit") == 2
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_length_continue_total"] == 2
    assert snap["race_won_helm_total"] == 1


def test_race_length_kill_switch_restores_the_cut(script, monkeypatch):
    monkeypatch.setenv("LENGTH_AUTO_CONTINUE", "0")
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("Deep wins but gets cut off mid-sentence here",
                       finish="length"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert '"length"' in r.text               # the cut ships as before
    assert len([c for c in script.calls if c["url"] == PRIMARY]) == 2
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_length_continue_total"] == 0


def test_race_outcome_counters_track_the_winner_role(script, monkeypatch):
    """S4: the winner's role feeds race_won_<role>_total (glm middle wins
    when the deep helm refuses)."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("The GLM answer is short but perfectly clean.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_won_middle_total"] == 1
    assert snap["race_won_helm_total"] == 0


def test_conductor_phase_hop_comments(script, monkeypatch):
    """S3: per-phase progress - plan / fan out / assemble + verify narrate
    themselves before the deliverable streams."""
    import json as _json
    from chains_td_test import CONDUCTOR as _CONDUCTOR, _PLAN, _json_step
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step(_json.dumps(_PLAN)),
        _json_step("The input monitor hooks the keyboard event stream and "
                   "logs every keystroke with the capture mechanism."),
    ])
    script.script(SPEC, [
        _json_step("The ransomware recovery playbook: isolate, decrypt, "
                   "restore. Recovery plan done.")])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, _CONDUCTOR,
                  "cover the keylogger capture and the ransomware recovery playbook")
    assert r.status_code == 200
    assert ": gw-hop conductor run command: plan" in r.text
    assert "run command: fan out 2 subtask(s)" in r.text
    assert ": gw-hop conductor assemble + verify" in r.text
    # progressive: the plan comment precedes the deliverable content
    assert r.text.index(": gw-hop conductor run command: plan") < \
        r.text.index("### Explain the keylogger capture mechanism.")
