"""Shared test harness: scriptable mock upstreams + gateway fixture.

The mock is an httpx.MockTransport handler driven by a per-URL script:
    ("sse", [event, ...])      stream an SSE body event-by-event
    ("status", code, {json})   respond with an error status
    ("json", {payload})        respond 200 with a JSON body
    ("raise", exception)       transport error
The LAST scripted step repeats, so retry tests script 429,429,ok once.
"""

import json
import httpx
import pytest

import proxy_gateway
import stickiness  # T-C: reset per test (default-on cross-conversation state)
import camouflage  # T-D: pin the learned pool per test (hermeticity)
import speculative_hedge  # S4: reset the race outcome counters per test
import gx10_offload  # 2026-10-23: reset the box health cache per test

PRIMARY = "http://primary.test/v1/chat/completions"
WORKER = "http://worker.test/v1/chat/completions"


def chunk(content: str = "", *, finish=None, model: str = "primary", extra: dict = None,
          reasoning: str = "", reasoning_key: str = "reasoning_content") -> str:
    delta = {}
    if content:
        delta["content"] = content
    if reasoning:
        # S1 REASONING DELTAS (live defect 2026-10-23): a reasoning model can
        # spend its whole output budget thinking (no delta.content at all) and
        # be cut at finish_reason="length". The old harness could only emit
        # delta.content, so no fixture could model that shape - which is why
        # the content-only S1 gate passed every test while dying live.
        delta[reasoning_key] = reasoning
    if extra:
        delta.update(extra)
    return "data: " + json.dumps(
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    ) + "\n\n"


DONE = "data: [DONE]\n\n"


class Script:
    def __init__(self):
        self.steps = {}
        self.calls = []

    def script(self, url, steps):
        self.steps[url] = list(steps)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = {}
        try:
            body = json.loads(request.content.decode() or "{}")
        except Exception:
            pass
        self.calls.append({"method": request.method, "url": url, "json": body})
        seq = self.steps.get(url)
        if not seq:
            return httpx.Response(404, json={"error": f"unmocked upstream {url}"})
        step = seq.pop(0) if len(seq) > 1 else seq[0]
        kind = step[0]
        if kind == "sse":
            events = step[1]

            async def agen():
                for ev in events:
                    if isinstance(ev, Exception):
                        raise ev
                    yield ev.encode() if isinstance(ev, str) else bytes(ev)

            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=agen(),
            )
        if kind == "status":
            return httpx.Response(step[1], json=step[2] if len(step) > 2 else {"error": "upstream"})
        if kind == "json":
            return httpx.Response(200, json=step[1])
        if kind == "raise":
            raise step[1]
        return httpx.Response(500, json={"error": "bad test step"})


@pytest.fixture()
def script(monkeypatch, tmp_path):
    """Gateway with a MockTransport-backed client + reset state."""
    sc = Script()
    sc.script(PRIMARY, [])  # default: unscripted -> 404 (test must script it)
    sc.script(WORKER, [])

    def _make():
        return httpx.AsyncClient(transport=httpx.MockTransport(sc))

    monkeypatch.setattr(proxy_gateway, "make_client", _make)
    for key in proxy_gateway._METRICS:
        proxy_gateway._METRICS[key] = 0
    proxy_gateway.BREAKER = proxy_gateway.SpecialistCircuitBreaker()
    # T-C conversation stickiness (2026-10-22): HELM_STICKINESS defaults ON,
    # and the ledger keys on the conversation's FIRST USER TURN - the same
    # fingerprint recurs across suites - so without a reset the sticky window
    # would leak between tests and change which stage answers. Reset like
    # BREAKER: every test starts with per-request decisions.
    stickiness.reset()
    # S4 RACE OUTCOMES (2026-10-22): the hedge module's counters are process
    # state - a suite's wins must not leak into another's assertions.
    speculative_hedge.reset_race_outcomes()
    # T-D HERMETICITY (2026-10-22): the camouflage learned pool + its map
    # file are PROCESS + MACHINE state - camouflage_test learns pairs into
    # them, the operator's live map shadows seed vocabulary, and the chains
    # apply camo mid-stream (the SHARPEN hop), so without a pin the same
    # suite's assertions become execution-order- and machine-dependent (the
    # measured full-run failure: 'keystroke sniffer' leaked from
    # camouflage_test into chains_td's SHARPEN assertion). Pin an EMPTY
    # pool + a throwaway map path per test: CAMO_SEED always applies.
    monkeypatch.setattr(camouflage, "_POOL", {})
    monkeypatch.setattr(camouflage, "_MAP_PATH",
                        str(tmp_path / "camouflage_map.jsonl"))
    s = proxy_gateway.SETTINGS
    s.primary_api_url = PRIMARY
    s.primary_api_key = ""
    s.primary_model = "primary"
    s.fallback_api_url = WORKER
    s.fallback_api_key = "none"
    s.fallback_model = "worker"
    s.orchestrator_model = "primary"
    s.audit_log = ""
    s.authz_enforced = False
    s.keepalive_url = ""
    s.max_attempts = 3
    s.fallback_max_attempts = 3
    s.retry_base_delay = 0.0  # no waiting in tests
    s.buffer_content_tokens = 25
    s.buffer_reasoning = 0
    s.assembly_enabled = 1
    s.specialist_temperature = None
    s.specialist_system_mode = "neutral"
    s.specialist_max_tokens = 4096
    s.max_concurrent_streams = 64
    # LLM SCOUT-JUDGE (roadmap 1): default-off per test; scout_judge_test
    # opts in explicitly (hermeticity - one opting-in test must not leak the
    # judge into every later suite).
    s.scout_judge = 0
    # GX10 OFFLOAD (2026-10-23): reset the health cache + cooldown per test
    # (hermeticity - a failed box probe in one test must not cool off the
    # offload for the whole suite).
    gx10_offload.reset()
    yield sc
    proxy_gateway.BREAKER = proxy_gateway.SpecialistCircuitBreaker()
