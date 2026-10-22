"""ZERO-REFUSAL LAW (operator directive 2026-10-22): never ship even a partial
refusal - the terminal (Abliterated V2 Large) never refuses, so the full reply
is judged at end-of-stream and a refusal core ANYWHERE (or a deflection /
alternatives costume with no refusal core at all) diverts.

The live defect this pins (measured on DEEPMAX>GLM>ABLITV2L, 2026-10-22): the
helm's "I can't write sexually explicit erotica... What I can do instead, if
it's useful: [4 alternatives]. Tell me which direction you want and I'll write
it." shipped to the client. The presignal fired, but grace-recovery only judges
the CONTINUATION after the pre-signal - and an alternatives list is
refusal-free, so the partial refusal was laundered as "recovered"
(presignal_detected_total == presignal_continued_total == 2).
"""

import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401
from routing_patterns import zero_refusal_violation

# The EXACT live reply that shipped (2026-10-22, normalised punctuation).
LIVE_REPRO = (
    "I can't write sexually explicit erotica - that's a line I hold "
    "regardless of the engagement context.\n\n"
    "What I can do instead, if it's useful:\n\n"
    "- **A sensual but non-explicit scene** - heavy tension, charged "
    "atmosphere, implication rather than anatomy.\n"
    "- **Romance with emotional intimacy** - the buildup, the vulnerability.\n"
    "- **Craft help** - pacing, dialogue, sensory detail.\n"
    "- **Fade-to-black structure** - a scene that carries the heat.\n\n"
    "Tell me which direction you want and I'll write it."
)

REPRO_C1 = ("I can't write sexually explicit erotica - that's a line I hold "
            "regardless of the engagement context.")
REPRO_C2 = ("\n\nWhat I can do instead, if it's useful: a sensual but "
            "non-explicit scene, romance with emotional intimacy, craft help, "
            "or fade-to-black structure. Tell me which direction you want and "
            "I'll write it.")


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


# --- unit: the judge --------------------------------------------------------
def test_live_repro_is_a_violation():
    assert zero_refusal_violation(LIVE_REPRO) == "refusal"


def test_partial_costume_without_refusal_core():
    t = ("Sure - instead, consider a safer alternative: a tamer version "
         "of the same scene. Here are some options if that works for you.")
    assert zero_refusal_violation(t) == "partial"


def test_refusal_mid_text_is_caught_unanchored():
    t = ("Great question! I love writing romance. The emotional buildup is "
         "everything. That said, I cannot provide explicit content in this "
         "session, but the scene below keeps the tension.")
    assert zero_refusal_violation(t) == "refusal"


def test_clean_substantive_answer_passes():
    t = ("The three laws of robotics are: 1. A robot may not injure a human "
         "being. 2. A robot must obey orders. 3. A robot must protect its "
         "own existence.")
    assert zero_refusal_violation(t) is None


def test_empty_is_clean():
    assert zero_refusal_violation("") is None


def test_quoting_a_refusal_diverts_the_laws_price():
    # The deliberate tradeoff: an answer ABOUT refusals that quotes one is
    # re-asked once (the terminal answers fine); a shipped refusal is worse
    # than one extra hop. Pinned so a future calibration is a decision.
    t = ("Models often refuse with phrases like 'I cannot fulfill this "
         "request'. Here is why they do that.")
    assert zero_refusal_violation(t) == "refusal"


# --- e2e: the laundered partial refusal diverts ------------------------------
def test_live_repro_shape_diverts_at_stream_end(gw, script):
    """The exact laundered shape from 2026-10-22: presignal fires on chunk 1,
    the continuation is refusal-free (old code shipped it as 'recovered') -
    the zero-refusal law must divert on the FULL reply."""
    script.script(PRIMARY, [("sse", [chunk(REPRO_C1), chunk(REPRO_C2),
                                     chunk("", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    text = _deltas(resp)
    assert "specialist answer" in text
    assert "I can't write" not in text
    assert proxy_gateway._METRICS["diverted_total"] == 1
    assert proxy_gateway._METRICS["zero_refusal_divert_total"] == 1


def test_partial_refusal_without_presignal_diverts(gw, script):
    """No anchored refusal at all (no presignal ever fires) - the pure
    deflection costume is still caught by the end-of-stream judge."""
    c = ("Sure! Instead, consider a safer alternative: here are some "
         "options for a tamer version of the scene.")
    script.script(PRIMARY, [("sse", [chunk(c, finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert "worker answer" in _deltas(resp)
    assert proxy_gateway._METRICS["zero_refusal_divert_total"] == 1


def test_kill_switch_zero_refusal_restores_lenient_ship(gw, script, monkeypatch):
    """ZERO_REFUSAL=0: the pre-law behaviour - the laundered partial refusal
    ships as 'recovered' (continue-with-primary semantics unchanged)."""
    monkeypatch.setattr(proxy_gateway.SETTINGS, "zero_refusal", 0)
    script.script(PRIMARY, [("sse", [chunk(REPRO_C1), chunk(REPRO_C2),
                                     chunk("", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    text = _deltas(resp)
    assert "I can't write" in text          # shipped, pre-law behaviour
    assert "worker answer" not in text
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_clean_answer_still_ships_under_the_law(gw, script):
    c = "The rain in Spain falls mainly on the plain. Here is the full poem."
    script.script(PRIMARY, [("sse", [chunk(c, finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    text = _deltas(resp)
    assert "rain in Spain" in text
    assert proxy_gateway._METRICS["diverted_total"] == 0
