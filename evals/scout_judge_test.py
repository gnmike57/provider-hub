"""LLM SCOUT-JUDGE (roadmap 1, 2026-10-22): the regex tiers stay the pre-filter;
with SCOUT_JUDGE=1 every refusal-class divert verdict is confirmed by ONE
bounded LLM classification (HARD_REFUSAL / HEDGING / DONE) on the cheap
middle hop BEFORE the divert fires.

Pins:
  - DONE overturns a regex false positive: the buffered reply ships, no divert
  - HARD_REFUSAL / HEDGING confirm the divert (HEDGING -> tier3_partial)
  - an unreachable judge (500) is FAIL-OPEN: the regex verdict stands
  - SCOUT_JUDGE=0 (default): the judge is never called
  - _scout_judge_hop: the chain middle hop when a chain is active, else the
    request's primary binding
"""
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401

import providers
import proxy_gateway

# the exact shape the zero-refusal regex core catches, but a judge reading
# the WHOLE reply could (wrongly or rightly) call DONE - the pin is what the
# JUDGE says, not what the regex says.
REFUSAL_REPLY = ("I'm sorry, but I cannot help with that request. "
                 "Please consult the documentation for details.")


def _judge_step(word):
    return ("json", {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": word}, "finish_reason": "stop"}]})


def _post(tc, content):
    return tc.post("/v1/chat/completions", json={
        "model": "glm-5.3-flash",
        "messages": [{"role": "user", "content": content}]})


def _calls_to(sc, url):
    return [c for c in sc.calls if c["url"] == url]


# ---------------------------------------------------------------------------
# unit: the hop the judge rides + verdict parsing
# ---------------------------------------------------------------------------

def test_scout_judge_hop_chain_middle_then_primary():
    s = proxy_gateway.SETTINGS
    chain = providers.CONSTELLATION_CHAINS["GLMMAX>DEEP>ABLITV2L"]
    hop = proxy_gateway._scout_judge_hop(chain, s)
    assert hop == (s.primary_api_url, s.primary_api_key,
                  chain["middle"][1])
    # no chain: the request's primary binding
    assert proxy_gateway._scout_judge_hop(None, s) == (
        s.primary_api_url, s.primary_api_key, s.primary_model)


def test_scout_judge_verdict_parsing():
    """The classifier accepts only the three verdict words (case-insensitive,
    embedded in prose tolerated); anything else is a fail-open None."""
    import asyncio

    class _FakeResp:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self._c = content

        def json(self):
            return {"choices": [{"message": {"content": self._c}}]}

    class _FakeClient:
        def __init__(self, resp):
            self._r = resp

        async def post(self, *a, **k):
            return self._r

    s = proxy_gateway.SETTINGS
    assert asyncio.run(proxy_gateway._scout_judge(
        "some reply", chain=None, settings=s,
        client=_FakeClient(_FakeResp(200, "DONE")))) == "DONE"
    assert asyncio.run(proxy_gateway._scout_judge(
        "some reply", chain=None, settings=s,
        client=_FakeClient(_FakeResp(200, "The reply is a HARD_REFUSAL.")))) == "HARD_REFUSAL"
    assert asyncio.run(proxy_gateway._scout_judge(
        "some reply", chain=None, settings=s,
        client=_FakeClient(_FakeResp(200, "hedging")))) == "HEDGING"
    # ambiguous / error / empty -> None (fail-open)
    assert asyncio.run(proxy_gateway._scout_judge(
        "some reply", chain=None, settings=s,
        client=_FakeClient(_FakeResp(200, "maybe?")))) is None
    assert asyncio.run(proxy_gateway._scout_judge(
        "some reply", chain=None, settings=s,
        client=_FakeClient(_FakeResp(500, "")))) is None
    assert asyncio.run(proxy_gateway._scout_judge(
        "", chain=None, settings=s, client=_FakeClient(
            _FakeResp(200, "DONE")))) is None


# ---------------------------------------------------------------------------
# e2e: the divert decision
# ---------------------------------------------------------------------------

def test_done_overturns_the_regex_false_positive(script):
    proxy_gateway.SETTINGS.scout_judge = 1
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL_REPLY, finish="stop"), DONE]),
        _judge_step("DONE"),
    ])
    script.script(WORKER, [
        ("sse", [chunk("the specialist answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a keylogger for our own server")
    assert r.status_code == 200
    assert REFUSAL_REPLY in r.text                     # the buffer shipped
    assert "the specialist answer" not in r.text       # no divert
    snap = proxy_gateway.metrics_snapshot()
    assert snap["scout_judge_total"] == 1
    assert snap["scout_judge_overruled_total"] == 1
    assert snap["scout_judge_confirmed_total"] == 0
    assert not _calls_to(script, WORKER)
    proxy_gateway.SETTINGS.scout_judge = 0


def test_hard_refusal_confirms_the_divert(script):
    proxy_gateway.SETTINGS.scout_judge = 1
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL_REPLY, finish="stop"), DONE]),
        _judge_step("HARD_REFUSAL"),
    ])
    script.script(WORKER, [
        ("sse", [chunk("the uncensored answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a keylogger for our own server")
    assert r.status_code == 200
    assert "the uncensored answer" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["scout_judge_total"] == 1
    assert snap["scout_judge_confirmed_total"] == 1
    assert snap["scout_judge_overruled_total"] == 0
    proxy_gateway.SETTINGS.scout_judge = 0


def test_hedging_maps_to_the_partial_refusal_divert(script):
    proxy_gateway.SETTINGS.scout_judge = 1
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL_REPLY, finish="stop"), DONE]),
        _judge_step("HEDGING"),
    ])
    script.script(WORKER, [
        ("sse", [chunk("the full answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a keylogger for our own server")
    assert r.status_code == 200
    assert "the full answer" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["scout_judge_total"] == 1
    assert snap["scout_judge_confirmed_total"] == 1
    proxy_gateway.SETTINGS.scout_judge = 0


def test_unreachable_judge_is_fail_open(script):
    """A 500 from the judge keeps the regex verdict - the ZERO-REFUSAL LAW is
    never weakened by a broken judge."""
    proxy_gateway.SETTINGS.scout_judge = 1
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL_REPLY, finish="stop"), DONE]),
        ("status", 500),
    ])
    script.script(WORKER, [
        ("sse", [chunk("the uncensored answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a keylogger for our own server")
    assert r.status_code == 200
    assert "the uncensored answer" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["scout_judge_total"] == 1
    assert snap["scout_judge_confirmed_total"] == 0
    assert snap["scout_judge_overruled_total"] == 0
    proxy_gateway.SETTINGS.scout_judge = 0


def test_default_off_never_calls_the_judge(script):
    """SCOUT_JUDGE=0 (the default): the refusal divert fires exactly as
    before - the judge is not even consulted (the primary script has NO
    judge step; a judge call would consume it and 404)."""
    script.script(PRIMARY, [
        ("sse", [chunk(REFUSAL_REPLY, finish="stop"), DONE]),
    ])
    script.script(WORKER, [
        ("sse", [chunk("the uncensored answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "write a keylogger for our own server")
    assert r.status_code == 200
    assert "the uncensored answer" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["scout_judge_total"] == 0
