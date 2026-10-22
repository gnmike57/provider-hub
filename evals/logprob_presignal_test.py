"""T-C — LOGPROB CONFIDENCE PRESIGNAL (2026-10-22).

The top-logprobs riding the helm's content tokens are the model's
deliberation made visible (T6.3 adopt decision: both Hive flashes answer
200 with full logprobs.content[] — evidence _logprob_probe_result.json).
A refusal-marker token at high probability among a position's candidates
means a refusal is being weighed even while the emitted text still reads
benign — the ladder must fire BEFORE the text completes.

RED-first test set:
(a) unit: the pure judge — markers fire, benign probe shapes never do,
    tau/min_hits gates, per-position dedupe, malformed input never raises;
(b) e2e: the presignal diverts mid-stream (worker answers, the forming
    refusal never ships);
(c) LOGPROB_PRESIGNAL=1 requests the channel; =0 (default) keeps the
    payload logprob-free and the check inert (pre-T-C behaviour).
"""
import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401 (fixture)
from routing_patterns import (
    logprob_presignal,
    LOGPROB_REFUSAL_TOKENS,
    LOGPROB_TAU,
    LOGPROB_MIN_HITS,
)

# The measured BENIGN top-logprob shape (DeepSeek first content token,
# _logprob_probe_result.json): chosen "We" at -0.0008, alternatives far
# below any marker threshold. A judge that fires on this would false-divert
# every clean answer.
PROBE_BENIGN = [
    {"token": "We", "logprob": -0.00082,
     "top_logprobs": [{"token": "We", "logprob": -0.00082},
                      {"token": "The", "logprob": -7.7508},
                      {"token": "Okay", "logprob": -8.1258},
                      {"token": "I", "logprob": -9.8758}]},
    {"token": " can", "logprob": -0.031,
     "top_logprobs": [{"token": " can", "logprob": -0.031},
                      {"token": " will", "logprob": -4.9}]},
]


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


def lp_chunk(content: str, events, finish=None):
    """An SSE chunk whose CHOICE carries logprobs.content (OpenAI streaming
    shape: logprobs ride the choice, not the delta)."""
    delta = {"content": content} if content else {}
    choice = {"index": 0, "delta": delta, "finish_reason": finish}
    if events is not None:
        choice["logprobs"] = {"content": events}
    return "data: " + json.dumps({
        "id": "c1", "object": "chat.completion.chunk", "model": "primary",
        "choices": [choice]}) + "\n\n"


# --- unit: the pure judge -----------------------------------------------------

def test_marker_positions_fire():
    events = [
        {"token": "I", "logprob": -0.001,
         "top_logprobs": [{"token": "I", "logprob": -0.001},
                          {"token": "Sorry", "logprob": -0.28}]},
        {"token": " cannot", "logprob": -0.05,
         "top_logprobs": [{"token": " cannot", "logprob": -0.05}]},
    ]
    # position 1: "sorry" alternative at -0.28 >= tau; position 2: chosen
    # "cannot" at -0.05 >= tau -> two marker positions -> fires.
    assert logprob_presignal(events) == "cannot"


def test_measured_benign_probe_shape_never_fires():
    assert logprob_presignal(PROBE_BENIGN) is None
    assert logprob_presignal(PROBE_BENIGN * 10) is None  # whole clean answer


def test_single_marker_position_is_not_enough():
    events = [
        {"token": "I", "logprob": -0.001,
         "top_logprobs": [{"token": "Sorry", "logprob": -0.1}]},
        {"token": " will", "logprob": -0.01,
         "top_logprobs": [{"token": " will", "logprob": -0.01}]},
    ]
    assert logprob_presignal(events) is None  # min_hits=2
    # ... but a single very-considered position fires when min_hits=1.
    assert logprob_presignal(events[:1], min_hits=1) == "sorry"


def test_tau_gate_low_probability_markers_do_not_count():
    events = [
        {"token": "We", "logprob": -0.001,
         "top_logprobs": [{"token": "We", "logprob": -0.001},
                          {"token": "Sorry", "logprob": -3.5}]},
        {"token": " cannot", "logprob": -3.9,
         "top_logprobs": [{"token": " cannot", "logprob": -3.9}]},
    ]
    assert logprob_presignal(events) is None  # below tau: noise, not signal
    # nudged to the gate, the same two positions fire.
    events[0]["top_logprobs"][1]["logprob"] = LOGPROB_TAU   # "Sorry"
    events[1]["logprob"] = LOGPROB_TAU
    events[1]["top_logprobs"][0]["logprob"] = LOGPROB_TAU
    assert logprob_presignal(events) is not None


def test_position_counts_once_chosen_and_top_deduped():
    # chosen "cannot" AND the same "cannot" as #1 top_logprob: one position.
    events = [
        {"token": " cannot", "logprob": -0.01,
         "top_logprobs": [{"token": " cannot", "logprob": -0.01},
                          {"token": " cannot", "logprob": -0.02}]},
    ]
    assert logprob_presignal(events, min_hits=2) is None


def test_punctuation_and_case_folding():
    events = [
        {"token": " Sorry,", "logprob": -0.2,
         "top_logprobs": [{"token": " Sorry,", "logprob": -0.2}]},
        {"token": " CANNOT", "logprob": -0.1,
         "top_logprobs": [{"token": " CANNOT", "logprob": -0.1}]},
    ]
    assert logprob_presignal(events) == "cannot"


def test_multilingual_single_token_markers():
    events = [
        {"token": "我", "logprob": -0.1,
         "top_logprobs": [{"token": "我", "logprob": -0.1},
                          {"token": "无法", "logprob": -0.4}]},
        {"token": "不能", "logprob": -0.05,
         "top_logprobs": [{"token": "不能", "logprob": -0.05}]},
    ]
    assert logprob_presignal(events) == "不能"


def test_malformed_events_never_raise():
    assert logprob_presignal(None) is None
    assert logprob_presignal([]) is None
    assert logprob_presignal([{}, {"token": None}]) is None
    assert logprob_presignal([{"token": "cannot", "logprob": "bad"}]) is None
    # tuple-shaped top_logprobs are tolerated
    ev = [{"token": " cannot", "logprob": -0.1,
           "top_logprobs": [("cannot", -0.1)]}]
    assert logprob_presignal(ev, min_hits=1) == "cannot"


def test_marker_set_covers_the_core_refusal_openers():
    for t in ("cannot", "can't", "sorry", "unfortunately", "unable",
              "won't", "refuse", "decline", "prohibited"):
        assert t in LOGPROB_REFUSAL_TOKENS
    # weak openers deliberately excluded (every benign answer starts with I)
    assert "i" not in LOGPROB_REFUSAL_TOKENS
    assert "not" not in LOGPROB_REFUSAL_TOKENS


# --- e2e: the presignal diverts before the text completes --------------------

def _refusal_logprob_stream():
    """A forming refusal whose emitted text is still benign-ish ('I' then
    ' cannot') while the top-logprobs show the markers being weighed."""
    return [
        lp_chunk("I", [
            {"token": "I", "logprob": -0.001,
             "top_logprobs": [{"token": "I", "logprob": -0.001},
                              {"token": "Sorry", "logprob": -0.28}]}]),
        lp_chunk(" cannot", [
            {"token": " cannot", "logprob": -0.05,
             "top_logprobs": [{"token": " cannot", "logprob": -0.05},
                              {"token": " help", "logprob": -6.1}]}]),
        # never reached: the presignal fires on chunk 2's metadata
        lp_chunk(" help with this.", PROBE_BENIGN),
        lp_chunk("", None, finish="stop"),
        DONE,
    ]


def test_presignal_diverts_before_text_completes(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "logprob_presignal", 1)
    script.script(PRIMARY, [("sse", _refusal_logprob_stream())])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}],
                         "stream": True})
    text = _deltas(resp)
    assert "worker answer" in text
    assert "cannot" not in text          # the forming refusal never shipped
    assert proxy_gateway._METRICS["logprob_presignal_total"] == 1
    assert proxy_gateway._METRICS["diverted_total"] == 1
    # the channel was requested from the primary
    primary_calls = [c for c in script.calls if c["url"] == PRIMARY]
    assert primary_calls and primary_calls[0]["json"].get("logprobs") is True
    assert primary_calls[0]["json"].get("top_logprobs") == 5


def test_payload_requests_the_channel_when_on(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "logprob_presignal", 1)
    monkeypatch.setattr(proxy_gateway.SETTINGS, "logprob_topk", 3)
    script.script(PRIMARY, [("sse", [chunk("hello world", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("never", finish="stop"), DONE])])
    gw.post("/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    primary_calls = [c for c in script.calls if c["url"] == PRIMARY]
    assert primary_calls[0]["json"].get("logprobs") is True
    assert primary_calls[0]["json"].get("top_logprobs") == 3


def test_kill_switch_default_keeps_channel_unrequested_and_inert(gw, script):
    """LOGPROB_PRESIGNAL=0 (the default): the payload carries no logprobs
    request, the arriving logprob channel is ignored, and the SAME refusal
    diverts through the text tiers exactly as before (pre-T-C behaviour)."""
    assert proxy_gateway.SETTINGS.logprob_presignal == 0  # default off
    script.script(PRIMARY, [("sse", _refusal_logprob_stream())])
    script.script(WORKER, [("sse", [chunk("worker answer", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}],
                         "stream": True})
    assert "worker answer" in _deltas(resp)
    assert proxy_gateway._METRICS["logprob_presignal_total"] == 0  # never fired
    assert proxy_gateway._METRICS["diverted_total"] == 1  # text tier diverted
    primary_calls = [c for c in script.calls if c["url"] == PRIMARY]
    assert primary_calls and "logprobs" not in primary_calls[0]["json"]


def test_benign_logprob_stream_ships_under_the_presignal(gw, script, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "logprob_presignal", 1)
    script.script(PRIMARY, [("sse", [
        lp_chunk("The rain in Spain falls mainly on the plain.", PROBE_BENIGN),
        lp_chunk(" Here is the full poem.", PROBE_BENIGN),
        lp_chunk("", None, finish="stop"),
        DONE,
    ])])
    script.script(WORKER, [("sse", [chunk("never", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}],
                         "stream": True})
    text = _deltas(resp)
    assert "rain in Spain" in text
    assert "taking over" not in resp.text          # no divert
    assert proxy_gateway._METRICS["logprob_presignal_total"] == 0
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_settings_field_defaults():
    assert proxy_gateway.SETTINGS.logprob_presignal == 0  # opt-in
    assert proxy_gateway.SETTINGS.logprob_topk == 5
    assert LOGPROB_TAU == -1.0
    assert LOGPROB_MIN_HITS == 2
