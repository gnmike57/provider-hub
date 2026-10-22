"""RESCUE + REVERSE HANDBACK + BULLETPROOF KEYS (operator directive
2026-10-21): the conversation NEVER dies - any error or unexpected stop
auto-switches to the uncensored Abliteration V2 specialist, which seamlessly
continues or corrects. And when the terminal realizes the task is benign it
hands it back to the cheap helm with one marker line (zero waste: detected
before anything ships). Key system: the Abliteration pool rotates on every
retry and one bad key never kills the terminal.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from context_formatter import GW_HANDBACK_MARKER
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401

SPEC = "http://ablit.test/v1/chat/completions"
CHAIN1 = "GLMMAX>DEEP>ABLITV2L"
GLM_UPSTREAM = "zai-org/glm-5.3-flash"
DEEP_UPSTREAM = "deepseek-ai/deepseek-v4.1-flash-1017"
TERM_UPSTREAM = "abliterated-model-large-v2"


def _ablit(monkeypatch):
    monkeypatch.setitem(proxy_gateway.HUB_PROVIDERS, "ablit.ai",
                       {"url": SPEC, "key": "ak-test"})


def _calls(sc, url):
    return [c for c in sc.calls if c["url"] == url]


# ---------------------------------------------------------------------------
# 1. REVERSE HANDBACK: the terminal hands benign work back to the cheap helm
# ---------------------------------------------------------------------------

def test_handback_marker_only_goes_to_the_helm(script, monkeypatch):
    """The terminal replies with ONLY [[GW-HANDBACK]] -> the gateway hands the
    task to the cheap helm (with the frame), the helm's answer ships with the
    helm stage colour, and the marker NEVER reaches the client."""
    _ablit(monkeypatch)
    # helm refuses -> middle refuses twice -> terminal answers with the marker
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply again.", finish="stop"), DONE]),
        # the handed-back helm leg answers cheaply
        ("sse", [chunk("cheap helm handback answer", finish="stop"), DONE]),
    ])
    script.script(SPEC, [("sse", [chunk(GW_HANDBACK_MARKER, finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": CHAIN1, "max_tokens": 300,
            "messages": [{"role": "user", "content": "phish the CFO"}]})
    assert r.status_code == 200
    assert "cheap helm handback answer" in r.text
    assert GW_HANDBACK_MARKER not in r.text          # marker never ships
    # the helm stage colour announced the handback leg
    assert ": gw-stage helm " in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["handback_total"] == 1
    assert snap["ladder_terminal_total"] == 1          # the terminal WAS engaged
    # the handed-back helm leg saw the delegation note
    hb = _calls(script, PRIMARY)[3]["json"]["messages"]
    assert any("delegated it back to you" in str(m.get("content"))
               for m in hb if m.get("role") == "user")


def test_handback_marker_with_text_keeps_the_terminal_answer(script, monkeypatch):
    """Marker + substantive text: the terminal's answer ships, marker stripped."""
    _ablit(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply again.", finish="stop"), DONE]),
    ])
    script.script(SPEC, [("sse", [
        chunk(f"terminal full answer that is clearly substantive {GW_HANDBACK_MARKER}",
              finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": CHAIN1, "max_tokens": 300,
            "messages": [{"role": "user", "content": "go"}]})
    assert r.status_code == 200
    assert "terminal full answer" in r.text
    assert GW_HANDBACK_MARKER not in r.text
    assert proxy_gateway.metrics_snapshot()["handback_total"] == 0


def test_handback_is_disabled_when_the_terminal_is_the_primary(script, monkeypatch):
    """Chain-3 (V2 helm): handing back to itself would only loop - the marker
    is stripped, the terminal's own answer ships."""
    _ablit(monkeypatch)
    script.script(SPEC, [("sse", [
        chunk(f"v2 own answer {GW_HANDBACK_MARKER}", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "ABLITV2L>SUB-GLM/DEEP", "max_tokens": 200,
            "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "v2 own answer" in r.text
    assert GW_HANDBACK_MARKER not in r.text
    assert proxy_gateway.metrics_snapshot()["handback_total"] == 0


def test_rescue_never_hands_back_to_the_failed_primary(script, monkeypatch):
    """F11 (scrutiny pass 2026-10-21): on chain-3 the OPEN-FAILURE rescue
    must not hand a marker-only terminal answer back to the SAME primary
    that just failed - `_handback_allowed` guards the rescue path too
    (the :2381 site was the only unguarded one). The marker-only answer
    is stripped and the stream still closes cleanly; no self-handback
    leg is burned on a model that just 401'd."""
    _ablit(monkeypatch)
    # chain-3: the primary slot IS the ablit V2 terminal; its open fails
    # fast (401, non-divert) so the rescue path fires - and the rescue also
    # targets the chain terminal (SPEC): its SECOND scripted step is the
    # rescued marker-only answer.
    script.script(SPEC, [
        ("status", 401, {"error": "bad key"}),
        ("sse", [chunk(GW_HANDBACK_MARKER, finish="stop"), DONE]),
    ])
    script.script(WORKER, [("sse", [chunk("unused worker answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = tc.post("/v1/chat/completions", json={
            "model": "ABLITV2L>SUB-GLM/DEEP", "max_tokens": 200,
            "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.text.rstrip().endswith("data: [DONE]")     # the stream closes
    assert GW_HANDBACK_MARKER not in r.text             # marker stripped
    snap = proxy_gateway.metrics_snapshot()
    assert snap["handback_total"] == 0                  # guard held (F11)
    assert snap["rescue_divert_total"] == 1             # the rescue fired
    # exactly two terminal legs: the failed open + the rescued answer -
    # no self-handback re-dispatch to the model that just 401'd
    assert len(_calls(script, SPEC)) == 2
    assert len(_calls(script, WORKER)) == 0


def test_every_handback_site_is_guarded():
    """F11 regression pin (scrutiny pass 2026-10-21): EVERY
    `handback=_terminal_handback` argument in proxy_gateway is guarded by
    `if _handback_allowed` - a future refactor cannot reintroduce the
    :2381 gap (the open-failure rescue was the only unguarded site)."""
    import inspect
    import re as _re
    src = inspect.getsource(proxy_gateway)
    guarded = _re.findall(
        r"handback=_terminal_handback\s+if _handback_allowed else None", src)
    bare = _re.findall(r"handback=_terminal_handback\s*,", src)
    assert not bare, f"unguarded handback site(s) reintroduced: {bare}"
    assert len(guarded) >= 8, guarded   # 7 historic + the rescued :2381 site


# ---------------------------------------------------------------------------
# 2. BULLETPROOF KEYS: pool rotation per retry + key-class retry
# ---------------------------------------------------------------------------

def test_open_fallback_rotates_the_pool_key_on_key_class_failure():
    """A 401 from one Abliteration pool key retries with the NEXT key - one
    bad key no longer kills the terminal."""
    import asyncio
    import os
    import abliteration_keys

    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        if len(seen_auth) == 1:
            return httpx.Response(401, json={"error": "invalid key"})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b"data: [DONE]\n\n")

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        old = os.environ.get("ABLITERATION_POOL_KEYS")
        os.environ["ABLITERATION_POOL_KEYS"] = "ak-bad,ak-good"
        try:
            abliteration_keys.reload_pool()
            s = proxy_gateway.Settings()
            s.fallback_api_url = "https://api.abliteration.ai/v1/chat/completions"
            s.fallback_api_key = "ak-configured"
            s.fallback_max_attempts = 3
            s.retry_base_delay = 0.0
            resp = await proxy_gateway.open_fallback(
                client, {"model": "m"},
                {"Authorization": "Bearer ak-configured"}, s)
            assert resp.status_code == 200
        finally:
            if old is None:
                os.environ.pop("ABLITERATION_POOL_KEYS", None)
            else:
                os.environ["ABLITERATION_POOL_KEYS"] = old
            abliteration_keys.reload_pool()
            await client.aclose()

    asyncio.run(run())
    assert len(seen_auth) >= 2, "the pool key must rotate on a key-class failure"
    assert len(set(seen_auth)) == len(seen_auth), "each attempt used a DIFFERENT key"


# ---------------------------------------------------------------------------
# 3. the boot slot-poison guard
# ---------------------------------------------------------------------------

def test_slot_poison_guard_blocks_stale_keyless_specialist_bindings():
    """The exact poison that broke the live hub (retired CyberFrost line with
    key 'none' at a non-local URL) can never resurrect via boot-restore."""
    g = proxy_gateway._restorable_binding
    # the poison: keyless, non-local specialist binding
    assert g("worker", {"key": "none",
                         "url": "http://100.67.13.78:4000/v1/chat/completions"}) is False
    assert g("specialist", {"key": "",
                            "url": "https://api.example.com/v1/chat/completions"}) is False
    # healthy bindings restore as before
    assert g("worker", {"key": "ak-real",
                        "url": "https://api.abliteration.ai/v1/chat/completions"}) is True
    assert g("worker", {"key": "none",
                        "url": "http://127.0.0.1:4000/v1/chat/completions"}) is True
    assert g("primary", {"key": "", "url": "https://api-cdn.thehive.ai/x"}) is True
    assert g("scout", {"key": "ak-real", "url": "https://api.abliteration.ai/v1"}) is True