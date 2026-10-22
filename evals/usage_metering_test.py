"""Usage-metering pins (2026-10-22 log review).

The old middleware billed len(chunk)//4 over the WHOLE SSE envelope and
hard-coded tokens_in=0 - measured live at tokens_out=59244 / $118.49 for
one ordinary reply. Pins:
  - a stream carrying an upstream usage object meters THOSE token counts
  - without usage, only content deltas are estimated (~4 chars/token)
  - tokens_in is recorded (0 only when the stream carries no usage)
"""
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401

import proxy_gateway


def _capture(monkeypatch):
    captured = []

    def _record(**kw):
        captured.append(kw)

    monkeypatch.setattr(proxy_gateway.billing_mod.USAGE, "record", _record)
    monkeypatch.setattr(proxy_gateway.billing_mod.BILLING, "get_balance",
                       lambda uid: 100.0)
    monkeypatch.setattr(proxy_gateway.billing_mod.BILLING, "deduct",
                       lambda uid, tok, cost: None)
    monkeypatch.setattr(proxy_gateway.billing_mod.BILLING, "is_low",
                       lambda uid: False)
    return captured


def _post(tc, content):
    return tc.post("/v1/chat/completions", json={
        "model": "primary",
        "messages": [{"role": "user", "content": content}]})


def test_usage_object_wins_over_the_byte_estimate(script, monkeypatch):
    captured = _capture(monkeypatch)
    usage_event = ('data: {"id": "u1", "object": "chat.completion.chunk", '
                   '"choices": [{"index": 0, "delta": {}}], '
                   '"usage": {"prompt_tokens": 11, "completion_tokens": 7}}\n\n')
    script.script(PRIMARY, [
        ("sse", [chunk("a much longer content delta than seven tokens really",
                       finish=None),
                 usage_event,
                 chunk("", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something")
    assert r.status_code == 200
    assert captured, "usage must be recorded"
    assert captured[-1]["tokens_in"] == 11      # real prompt count
    assert captured[-1]["tokens_out"] == 7      # usage wins over the estimate


def test_no_usage_falls_back_to_content_only_estimate(script, monkeypatch):
    captured = _capture(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("hello there", finish=None),
                 chunk("", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something")
    assert r.status_code == 200
    assert captured, "usage must be recorded"
    # ONE content delta of 11 chars -> 2 estimated tokens (11//4), not the
    # ~30 the old bytes//4 law billed for the same stream
    assert captured[-1]["tokens_out"] == 2
    assert captured[-1]["tokens_in"] == 0


def test_sse_envelope_never_counts_again(script, monkeypatch):
    captured = _capture(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("hi", finish=None),
                 chunk(" there", finish=None),
                 chunk("", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something")
    assert r.status_code == 200
    # two small content deltas -> 2 estimated tokens; the JSON envelope,
    # [DONE] and finish markers around them count NOTHING (the old law
    # billed ~40+ for this exact stream)
    assert captured[-1]["tokens_out"] == 2
