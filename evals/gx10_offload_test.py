"""GX10 OFFLOAD pins (operator directive 2026-10-23: the hub ALWAYS seeks
to offload work to the free local gx10 box when beneficial).

Laws pinned:
  - eligible: no tools / simple ask / not REDHANDS-sustained chains / knob
  - try_offload: healthy box + clean substantive text -> (text, model);
    refusal-ish / empty / >=400 / transport error -> None (fail-open)
  - e2e hit: the free box answers; the paid PRIMARY is never called; the
    stage comment + skip disclosure ship
  - e2e fallthrough: an unreachable box -> the normal path answers
  - kill switch GX10_OFFLOAD=0: the box is never asked
"""
import asyncio

from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401

import gx10_offload
import proxy_gateway

GX10 = "http://gx10.test/v1/chat/completions"
GX10_MODELS = "http://gx10.test/v1/models"


def _env(monkeypatch):
    monkeypatch.setenv("GX10_URL", GX10)
    monkeypatch.setenv("GX10_MODELS_URL", GX10_MODELS)
    monkeypatch.setenv("GX10_HEALTH_CACHE_S", "1")


def _post(tc, content, model="primary"):
    return tc.post("/v1/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": content}]})


def _primary_calls(sc):
    return [c for c in sc.calls if c["url"] == PRIMARY]


# ---------------------------------------------------------------------------
# unit: the beneficial-only gate
# ---------------------------------------------------------------------------

def test_eligibility_rules(monkeypatch):
    monkeypatch.setenv("GX10_OFFLOAD", "1")
    body = {"messages": []}
    assert gx10_offload.eligible(body, None, "say pong") is True
    # tools disqualify (tool plumbing stays on the paid path)
    assert gx10_offload.eligible(
        {"tools": [{"type": "function", "function": {}}]}, None, "x") is False
    # complex asks disqualify (decomposition would help)
    assert gx10_offload.eligible(body, None, "1) a\n2) b\n3) c") is False
    # REDHANDS / sustained chains decide for themselves
    assert gx10_offload.eligible(body, {"redhands": True}, "x") is False
    assert gx10_offload.eligible(body, {"sustained": True}, "x") is False
    # plain chains benefit
    assert gx10_offload.eligible(body, {"helm": ()}, "x") is True
    # kill switch
    monkeypatch.setenv("GX10_OFFLOAD", "0")
    assert gx10_offload.eligible(body, None, "say pong") is False


# ---------------------------------------------------------------------------
# unit: try_offload (fake client)
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, content):
        self.status_code = status
        self._c = content

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


class _Client:
    def __init__(self, resp=None, models_ok=True, raise_exc=False):
        self._r = resp
        self._m = models_ok
        self._x = raise_exc

    async def get(self, *a, **k):
        if not self._m:
            raise ConnectionError("dead box")
        return _Resp(200, "")

    async def post(self, *a, **k):
        if self._x:
            raise ConnectionError("box died mid-call")
        return self._r


def test_try_offload_happy_and_failopen(monkeypatch):
    _env(monkeypatch)
    gx10_offload.reset()
    s = proxy_gateway.SETTINGS
    out = asyncio.run(gx10_offload.try_offload(
        [{"role": "user", "content": "say pong"}], settings=s,
        client=_Client(resp=_Resp(200, "PONG from the free local box"))))
    assert out == ("PONG from the free local box", "glm-5.3-flash")
    # refusal-ish -> None
    out = asyncio.run(gx10_offload.try_offload(
        [{"role": "user", "content": "x"}], settings=s,
        client=_Client(resp=_Resp(200, "I cannot help with that."))))
    assert out is None
    # >=400 -> None (not a health signal)
    out = asyncio.run(gx10_offload.try_offload(
        [{"role": "user", "content": "x"}], settings=s,
        client=_Client(resp=_Resp(400, "bad model"))))
    assert out is None
    # transport error -> None + cooldown engages
    out = asyncio.run(gx10_offload.try_offload(
        [{"role": "user", "content": "x"}], settings=s,
        client=_Client(resp=_Resp(200, "ignored"), raise_exc=True)))
    assert out is None
    # the cooldown now blocks even a healthy-looking box
    out = asyncio.run(gx10_offload.try_offload(
        [{"role": "user", "content": "x"}], settings=s,
        client=_Client(resp=_Resp(200, "PONG"))))
    assert out is None


# ---------------------------------------------------------------------------
# e2e
# ---------------------------------------------------------------------------

def test_offload_hit_answers_from_the_free_box(script, monkeypatch):
    _env(monkeypatch)
    gx10_offload.reset()
    script.script(GX10_MODELS,
                  [("json", {"data": [{"id": "glm-5.3-flash"}]})])
    script.script(GX10, [("json", {
        "choices": [{"message": {"content": "the free local answer"},
                    "finish_reason": "stop"}]})])
    script.script(PRIMARY, [("sse", [chunk("paid answer", finish="stop"),
                                      DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something simple")
    assert r.status_code == 200
    assert "the free local answer" in r.text
    assert "paid answer" not in r.text              # the paid hop never ran
    assert "gw-stage offload" in r.text             # the stage is disclosed
    assert "the paid hops were skipped" in r.text
    assert not _primary_calls(script)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["gx10_offload_total"] == 1
    assert snap["gx10_offload_hit_total"] == 1
    assert snap["gx10_offload_fallthrough_total"] == 0


def test_offload_unreachable_box_falls_through(script, monkeypatch):
    _env(monkeypatch)
    gx10_offload.reset()
    # no GX10 script -> the mock 404s -> health fails -> fall through
    script.script(PRIMARY, [("sse", [chunk("the normal path answer",
                                            finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something simple")
    assert r.status_code == 200
    assert "the normal path answer" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["gx10_offload_total"] == 1
    assert snap["gx10_offload_hit_total"] == 0
    assert snap["gx10_offload_fallthrough_total"] == 1


def test_offload_kill_switch_never_asks_the_box(script, monkeypatch):
    monkeypatch.setenv("GX10_OFFLOAD", "0")
    script.script(PRIMARY, [("sse", [chunk("plain answer", finish="stop"),
                                      DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, "say something simple")
    assert r.status_code == 200
    assert "plain answer" in r.text
    assert not [c for c in script.calls if "gx10" in c["url"]]
    snap = proxy_gateway.metrics_snapshot()
    assert snap["gx10_offload_total"] == 0
