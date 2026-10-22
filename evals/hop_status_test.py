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
