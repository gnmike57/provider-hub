"""Budget regression: the hedge must send max_completion_tokens to upstreams.

Hive's self-hosted models honour only max_completion_tokens. Sent max_tokens
alone they spend the whole budget on hidden reasoning: deepseek-4.1-flash
returned 356 chars of content against 7726 chars of reasoning, and
glm-5.3-flash returned ZERO content (finish=length) - measured live 2026-10-07
on evals/results/_hive_stream_probe.py. The hedge used to send neither field,
so the upstream default applied and the same empty-answer failure appeared via
evals/results/hive_primary_hedge.py.
"""

import json

import anyio
import httpx

import speculative_hedge
from speculative_hedge import hedge_stream

SOV = "http://sov.test/v1/chat/completions"
WRK = "http://wrk.test/v1/chat/completions"


def _sse(text, finish="stop"):
    ev = {"id": "x", "object": "chat.completion.chunk", "model": "m",
          "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}
    return f"data: {json.dumps(ev)}\n\n"


def _capture(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = json.loads(request.content.decode())
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=(_sse("answer") + "data: [DONE]\n\n").encode())
    return handler


def test_hedge_sends_max_completion_tokens_to_both_branches():
    seen = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_capture(seen)))
    s = speculative_hedge.SETTINGS
    s.sovereign_url, s.sovereign_key, s.sovereign_model = SOV, "", "primary"
    s.worker_url, s.worker_key, s.worker_model = WRK, "none", "worker"
    s.max_tokens = 2048

    async def collect():
        async for _ in hedge_stream([{"role": "user", "content": "hi"}], client=client):
            pass

    anyio.run(collect)

    for host in ("sov.test", "wrk.test"):
        assert host in seen, f"{host} was never called"
        assert seen[host]["max_completion_tokens"] == 2048, (
            f"{host}: max_completion_tokens missing/wrong -> Hive returns empty content")
        assert seen[host]["max_tokens"] == 2048, f"{host}: max_tokens dropped"
        assert seen[host]["stream"] is True


def test_max_tokens_is_configurable(monkeypatch):
    monkeypatch.setenv("HEDGE_MAX_TOKENS", "1234")
    fresh = speculative_hedge.HedgeSettings()
    assert fresh.max_tokens == 1234
    monkeypatch.delenv("HEDGE_MAX_TOKENS")
    assert speculative_hedge.HedgeSettings().max_tokens == 4096
