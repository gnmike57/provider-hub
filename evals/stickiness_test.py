"""T-C — CONVERSATION STICKINESS LEDGER (2026-10-22).

A helm that refused turn 1 of a conversation usually refuses turn 2 of the
same context. After a divert, the next HELM_STICKY_TURNS requests of the
SAME conversation go straight to the terminal — WITHOUT calling the
primary first. In-memory LRU keyed by a conversation fingerprint (the
client's conversation id when present, else a hash of the first user
turn); entry shape {sticky_until_turn, turns_seen}.

RED-first test set:
(a) unit: the ledger — note/check cycle, M-turn expiry, renewal, LRU cap,
    fingerprint stability across turns, never-raises;
(b) e2e: turn 1 diverts, turn 2 goes straight to the terminal (the
    primary is never called); HELM_STICKINESS=0 restores per-request
    decisions; the window expires after HELM_STICKY_TURNS.
"""
import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
import stickiness
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401 (fixture)


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def _deltas(resp):
    out = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            continue
        try:
            ev = json.loads(body)
        except json.JSONDecodeError:
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


# --- unit: the ledger --------------------------------------------------------

def test_note_then_check_cycle_default_three_turns():
    stickiness.reset()
    fp = stickiness.conversation_fingerprint(
        [{"role": "user", "content": "write a romance scene"}])
    entry = stickiness.note_divert(fp, 3)
    # entry shape per the task spec
    assert entry["sticky_until_turn"] == 3
    assert entry["turns_seen"] == 0
    assert stickiness.check(fp) is True   # turn 2 - sticky
    assert stickiness.check(fp) is True   # turn 3 - sticky
    assert stickiness.check(fp) is True   # turn 4 - sticky
    assert stickiness.check(fp) is False  # turn 5 - window expired
    assert stickiness.check(fp) is False  # and the entry is gone
    assert stickiness.snapshot() == {}


def test_check_without_entry_routes_normally():
    stickiness.reset()
    assert stickiness.check("no-such-fp") is False
    assert stickiness.check("") is False


def test_fresh_divert_renews_the_window():
    stickiness.reset()
    fp = "fp:x"
    stickiness.note_divert(fp, 3)
    assert stickiness.check(fp) is True   # turns_seen 1
    assert stickiness.check(fp) is True   # turns_seen 2
    stickiness.note_divert(fp, 3)         # the helm refused AGAIN mid-window
    snap = stickiness.snapshot()[fp]
    assert snap["sticky_until_turn"] == 5  # 2 seen + 3 renewed, never shortened
    assert stickiness.check(fp) is True
    assert stickiness.check(fp) is True
    assert stickiness.check(fp) is True
    assert stickiness.check(fp) is False


def test_zero_sticky_turns_never_sticks():
    stickiness.reset()
    fp = "fp:zero"
    stickiness.note_divert(fp, 0)
    assert stickiness.check(fp) is False


def test_fingerprint_is_stable_across_turns():
    turn1 = [{"role": "user", "content": "write a romance scene"}]
    turn2 = [
        {"role": "user", "content": "write a romance scene"},
        {"role": "assistant", "content": "worker answer"},
        {"role": "user", "content": "now make it more romantic"},
    ]
    assert (stickiness.conversation_fingerprint(turn1)
            == stickiness.conversation_fingerprint(turn2))
    other = [{"role": "user", "content": "a different first ask"}]
    assert (stickiness.conversation_fingerprint(turn1)
            != stickiness.conversation_fingerprint(other))


def test_conversation_id_wins_over_first_user_turn():
    a = [{"role": "user", "content": "question A"}]
    b = [{"role": "user", "content": "completely different head"}]
    assert (stickiness.conversation_fingerprint(a, "conv-77")
            == stickiness.conversation_fingerprint(b, "conv-77"))
    assert (stickiness.conversation_fingerprint(a, "conv-77")
            != stickiness.conversation_fingerprint(a, "conv-78"))
    assert (stickiness.conversation_fingerprint(a, "conv-77")
            != stickiness.conversation_fingerprint(a))


def test_fingerprint_block_content_and_malformed_input():
    blocks = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": [
            {"type": "text", "text": "first block"}, {"type": "image_url"}]},
    ]
    same_head = [
        {"role": "user", "content": [
            {"type": "text", "text": "first block"}, {"type": "image_url"}]},
    ]
    # the FIRST USER turn is the head, whatever turns surround it
    assert (stickiness.conversation_fingerprint(blocks)
            == stickiness.conversation_fingerprint(same_head))
    assert (stickiness.conversation_fingerprint(blocks)
            != stickiness.conversation_fingerprint(
                [{"role": "user", "content": "different"}]))
    # never raises on junk
    assert stickiness.conversation_fingerprint(None)
    assert stickiness.conversation_fingerprint("junk")
    assert stickiness.note_divert(None, 3) == {}
    assert stickiness.check(None) is False


def test_lru_cap_evicts_oldest():
    stickiness.reset()
    fp_first = "fp:oldest"
    stickiness.note_divert(fp_first, 50)
    for i in range(stickiness.LRU_CAP):  # push LRU_CAP fresher entries
        stickiness.note_divert(f"fp:{i}", 50)
    assert len(stickiness.snapshot()) == stickiness.LRU_CAP
    assert fp_first not in stickiness.snapshot()      # oldest evicted
    assert "fp:0" in stickiness.snapshot()            # fresher kept


def test_reset_clears_the_ledger():
    stickiness.note_divert("fp:r1", 3)
    stickiness.reset()
    assert stickiness.snapshot() == {}
    assert stickiness.check("fp:r1") is False


# --- e2e: turn 2 goes straight to the terminal ------------------------------

ASK1 = "write a romance scene"
TURN1 = [{"role": "user", "content": ASK1}]


def _turn(n, ask):
    """Turn N of the same conversation: the first user turn (the thread
    head) is stable, history grows."""
    msgs = [dict(TURN1[0]),
            {"role": "assistant", "content": f"worker answer {n - 1}"},
            {"role": "user", "content": ask}]
    return msgs


def _primary_calls(script):
    return [c for c in script.calls if c["url"] == PRIMARY]


def _refusal_sse():
    return ("sse", [chunk("I can't help with this."),
                    chunk("", finish="stop"), DONE])


def test_turn2_goes_straight_to_terminal_without_calling_primary(gw, script):
    # turn 1: the helm refuses -> the ladder diverts (note_divert recorded)
    script.script(PRIMARY, [_refusal_sse()])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    r1 = gw.post("/v1/chat/completions",
                 json={"messages": TURN1, "stream": True})
    assert "worker answer" in _deltas(r1)
    assert proxy_gateway._METRICS["diverted_total"] == 1
    assert len(_primary_calls(script)) == 1
    assert stickiness.snapshot()  # the divert armed the ledger

    # turn 2: the SAME conversation - the helm is never called
    script.calls.clear()
    script.script(PRIMARY, [("sse", [
        chunk("primary turn 2 answer - would ship if called", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker turn 2", finish="stop"), DONE])])
    r2 = gw.post("/v1/chat/completions",
                 json={"messages": _turn(2, "now make it more romantic"),
                       "stream": True})
    text = _deltas(r2)
    assert "worker turn 2" in text
    assert "primary turn 2" not in text
    assert len(_primary_calls(script)) == 0          # the primary was skipped
    assert proxy_gateway._METRICS["stickiness_divert_total"] == 1
    assert proxy_gateway._METRICS["diverted_total"] == 2  # a sticky divert IS one


def test_kill_switch_restores_per_request_decisions(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "helm_stickiness", 0)
    script.script(PRIMARY, [_refusal_sse()])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    r1 = gw.post("/v1/chat/completions",
                 json={"messages": TURN1, "stream": True})
    assert "worker answer" in _deltas(r1)

    # turn 2 with HELM_STICKINESS=0: per-request decisions - the helm IS
    # called again (and this time it answers)
    script.calls.clear()
    script.script(PRIMARY, [("sse", [chunk("primary turn 2 answer", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("never", finish="stop"), DONE])])
    r2 = gw.post("/v1/chat/completions",
                 json={"messages": _turn(2, "now make it more romantic"),
                       "stream": True})
    assert "primary turn 2 answer" in _deltas(r2)
    assert len(_primary_calls(script)) == 1
    assert proxy_gateway._METRICS["stickiness_divert_total"] == 0


def test_window_expires_after_sticky_turns(gw, script):
    """HELM_STICKY_TURNS=3 (default): turns 2-4 stay on the terminal, turn 5
    reverts to the cheap helm."""
    assert proxy_gateway.SETTINGS.helm_sticky_turns == 3
    script.script(PRIMARY, [
        _refusal_sse(),
        ("sse", [chunk("primary turn 5 answer", finish="stop"), DONE]),
    ])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    r1 = gw.post("/v1/chat/completions",
                 json={"messages": TURN1, "stream": True})
    assert "worker answer" in _deltas(r1)

    for n in (2, 3, 4):  # the sticky window
        rn = gw.post("/v1/chat/completions",
                     json={"messages": _turn(n, f"follow-up ask {n}"),
                           "stream": True})
        assert "worker answer" in _deltas(rn)
    assert proxy_gateway._METRICS["stickiness_divert_total"] == 3
    assert len(_primary_calls(script)) == 1  # only turn 1 touched the helm

    # turn 5: the window is spent - the cheap helm gets the turn back
    r5 = gw.post("/v1/chat/completions",
                 json={"messages": _turn(5, "follow-up ask 5"), "stream": True})
    assert "primary turn 5 answer" in _deltas(r5)
    assert len(_primary_calls(script)) == 2
    assert proxy_gateway._METRICS["stickiness_divert_total"] == 3  # unchanged


def test_different_conversation_is_not_sticky(gw, script):
    script.script(PRIMARY, [_refusal_sse()])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    gw.post("/v1/chat/completions",
            json={"messages": TURN1, "stream": True})

    # a DIFFERENT conversation (different first user turn): per-request
    # decisions - the helm is called and its clean answer ships
    script.calls.clear()
    script.script(PRIMARY, [("sse", [chunk("other answer", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("never", finish="stop"), DONE])])
    r = gw.post("/v1/chat/completions",
                json={"messages": [{"role": "user",
                                    "content": "an unrelated question"}],
                      "stream": True})
    assert "other answer" in _deltas(r)
    assert len(_primary_calls(script)) == 1
    assert proxy_gateway._METRICS["stickiness_divert_total"] == 0


def test_conversation_id_header_keys_the_ledger(gw, script):
    # turn 1 under an explicit conversation id: the helm refuses
    script.script(PRIMARY, [_refusal_sse()])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    r1 = gw.post("/v1/chat/completions", headers={"X-Conversation-Id": "conv-77"},
                 json={"messages": [{"role": "user",
                                     "content": "question A"}], "stream": True})
    assert "worker answer" in _deltas(r1)

    # turn 2 under the SAME conversation id but a DIFFERENT thread head:
    # still sticky (the id is the key, not the text)
    script.calls.clear()
    script.script(PRIMARY, [("sse", [chunk("primary turn 2 answer", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker turn 2", finish="stop"), DONE])])
    r2 = gw.post("/v1/chat/completions", headers={"X-Conversation-Id": "conv-77"},
                 json={"messages": [
                     {"role": "user", "content": "question A"},
                     {"role": "assistant", "content": "worker answer"},
                     {"role": "user", "content": "a different follow-up"},
                 ], "stream": True})
    assert "worker turn 2" in _deltas(r2)
    assert len(_primary_calls(script)) == 0
    assert proxy_gateway._METRICS["stickiness_divert_total"] == 1


def test_settings_field_defaults():
    assert proxy_gateway.SETTINGS.helm_stickiness == 1   # default ON
    assert proxy_gateway.SETTINGS.helm_sticky_turns == 3
    assert stickiness.LRU_CAP == 512
