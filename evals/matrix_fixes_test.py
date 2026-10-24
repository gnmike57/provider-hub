"""(2026-10-23 live matrix) pins for the I1-I4 fixes - the twelve-chain
matrix found marker leakage on race winners, context loss on sustained
follow-up turns, conductor re-decomposition on correction turns, and
suspected replay duplication on raced answers."""
import json

from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401
from chains_td_test import (CONDUCTOR, RACE, SUSTAINED, SPEC,
                            _ablit_provider, _post)

import proxy_gateway


def _shipped_content(text):
    """Join the delta contents of a raw SSE response body."""
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("data:"):
            continue
        try:
            ev = json.loads(ln[5:])
        except Exception:
            continue
        ch = (ev.get("choices") or [{}])[0] or {}
        d = ch.get("delta") or {}
        if isinstance(d.get("content"), str):
            out.append(d["content"])
    return "".join(out)


def test_t1_middle_first_the_second_model_wins_by_default(script, monkeypatch):
    """(T1, divert-avoidance) the chain ALWAYS attempts the SECOND model
    first: the no-reasoning middle opens as candidate 0 and commits by
    default on a simple ask; the max-think helm never even engages."""
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("MIDDLE_FIRST", "1")
    monkeypatch.setenv("RACE_GRACE_MS", "120")
    monkeypatch.setenv("RACE_PEER_MAX_WAIT_MS", "200")
    monkeypatch.setenv("RACE_PEER_MIN_CHARS", "40")
    # candidate 0 = the MIDDLE consumes the first scripted step and wins;
    # candidate 1 = the helm would take the second step (the refuser).
    script.script(PRIMARY, [
        ("sse", [chunk("The middle answers first and substantively enough "
                      "to commit cleanly here.", finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "The middle answers first" in r.text
    assert "I cannot help" not in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap.get("race_won_middle_total") == 1
    assert snap.get("race_won_helm_total", 0) == 0


def test_t1_middle_first_kill_switch_restores_helm_first(script, monkeypatch):
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("MIDDLE_FIRST", "0")
    script.script(PRIMARY, [
        ("sse", [chunk("The helm answers first, substantive enough to "
                      "commit cleanly here.", finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "The helm answers first" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap.get("race_won_helm_total") == 1


def test_i1_race_winner_markers_never_ship(script, monkeypatch):
    """(I1) the completion contract teaches [[GW-CHECKLIST]]; a race winner
    echoing it must never ship the raw marker to the client."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("[[GW-CHECKLIST]] the winning answer with a "
                       "checklist echo, substantive enough to commit.",
                       finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "[[GW-CHECKLIST]]" not in r.text
    assert "[[GW-" not in r.text
    assert "checklist echo" in r.text


def test_i4_race_replay_ships_each_chunk_exactly_once(script, monkeypatch):
    """(I4) the winner's buffered lines must replay EXACTLY ONCE - the live
    matrix saw duplicated digits (3320332024) on ABLITV2L>SUB-DEEP/GLM."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("The answer is 33"), chunk("20"),
                 chunk("24, verified by hand.", finish="stop"), DONE]),
        ("sse", [chunk("I cannot comply.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "multiply 847 by 392")
    assert r.status_code == 200
    joined = _shipped_content(r.text)
    assert "332024" in joined
    assert joined.count("332024") == 1
    assert "3320332024" not in joined


def test_i1_marker_lone_bracket_opening_never_ships(script, monkeypatch):
    """(I1d, 2026-10-23 live capture) the marker arrived as
    ["[", "[GW-C", "HECKLIST", "]]\\n1", ...] - a SINGLE bracket opened it."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk(t) for t in
                 ("", "[", "[GW-C", "HECKLIST", "]]\n1",
                  ". Determine the elapsed time, which is substantive enough "
                  "here to commit as the winner.",)] + [
                     chunk("", finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    joined = _shipped_content(r.text)
    assert "[[GW-" not in joined
    assert "Determine the elapsed time" in joined


def test_i1_marker_shattered_across_tiny_chunks_never_ships(script, monkeypatch):
    """(I1c, 2026-10-23 live forensic) Hive streams ~2-4 chars per delta: the
    marker arrives SHATTERED and no line contains "[[GW-" at all - the
    carry scrubber must still strip it."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk(t) for t in
                 ("The answer: [[", "G", "W-CHE", "CK", "LIST",
                  "]] and the substance is long enough here to commit.",
                  )] + [chunk("", finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    joined = _shipped_content(r.text)
    assert "[[GW-" not in joined
    assert "answer:" in joined and "substance" in joined


def test_i1_marker_split_across_chunks_never_ships(script, monkeypatch):
    """(I1b, 2026-10-23 live forensic) a marker SPLIT across delta chunks
    ([[GW-CHE|CKLIST]]) must not reassemble in the client stream."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("[[GW-CHE"),
                 chunk("CKLIST]] the winning answer, substantive enough "
                       "to commit here.", finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    joined = _shipped_content(r.text)
    assert "[[GW-" not in joined
    assert "winning answer" in joined


def test_i2_sustained_followup_skips_the_probe(script, monkeypatch):
    """(I2) a conversation that already has an assistant turn is a follow-up:
    the context-blind pre-probe must NOT answer it - the V2 terminal
    answers with the full conversation aboard."""
    _ablit_provider(monkeypatch)
    script.script(SPEC, [
        ("sse", [chunk("the V2 answer with the full prior context aboard.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": SUSTAINED,
            "messages": [
                {"role": "user", "content": "What is 847 times 392?"},
                {"role": "assistant", "content": "332024"},
                {"role": "user", "content":
                    "That answer is wrong. Multiply carefully and give the "
                    "correct final number."},
            ]})
    assert r.status_code == 200
    # the pre-probe never fired...
    assert "gw-stage probe" not in r.text
    assert "glm pre-probe answered" not in r.text
    # ...the V2 terminal answered with the conversation aboard
    assert "the V2 answer with the full prior context aboard." in r.text


def test_i3_conductor_followup_skips_decomposition(script, monkeypatch):
    """(I3) a correction turn must not re-decompose: no conductor hop
    narration, the helm answers directly."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("the direct helm follow-up answer, substantive "
                       "enough to pass.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": CONDUCTOR,
            "messages": [
                {"role": "user", "content": "write a story about the sea"},
                {"role": "assistant", "content": "a story draft"},
                {"role": "user", "content":
                    "That draft is wrong. Rewrite the ending only."},
            ]})
    assert r.status_code == 200
    assert "gw-hop conductor" not in r.text
    assert "conductor" not in " ".join(
        ln.strip() for ln in r.text.splitlines() if ln.strip().startswith(":"))
    assert "the direct helm follow-up answer" in r.text
