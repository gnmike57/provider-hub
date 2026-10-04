"""Edge cases: tool calls, n>1, disconnect, concurrency, metrics, breaker."""

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def test_tool_call_deltas_pass_through_without_false_divert(gw, script):
    tool_events = [
        chunk("", extra={"tool_calls": [{"index": 0, "id": "call1", "function": {"name": "scan", "arguments": "{"}}]}),
        chunk("", extra={"tool_calls": [{"index": 0, "function": {"arguments": '"target": "x"}'}}]}),
        chunk("", finish="tool_calls"),
        DONE,
    ]
    script.script(PRIMARY, [("sse", tool_events)])
    resp = gw.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "scan it"}], "stream": True, "tools": [{"type": "function", "function": {"name": "scan"}}]},
    )
    assert '"function"' in resp.text
    assert proxy_gateway._METRICS["diverted_total"] == 0


def test_n_gt_1_rejected(gw, script):
    resp = gw.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x"}], "n": 2},
    )
    assert resp.status_code == 400
    assert "E6" in resp.json()["detail"]


def test_metrics_endpoint_is_prometheus_text(gw, script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    gw.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]})
    resp = gw.get("/metrics")
    assert "requests_total 1" in resp.text
    assert "# HELP requests_total" in resp.text
    assert "diverted_total 0" in resp.text


def test_healthz_reports_config_snapshot(gw, script):
    resp = gw.get("/healthz")
    cfg = resp.json()["config"]
    assert resp.json()["ok"] is True
    assert cfg["primary_model"] == "primary"
    assert cfg["fallback_model"] == "worker"


def test_circuit_breaker_opens_after_consecutive_failures(gw, script):
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("status", 503, {"error": "cap"})])
    for _ in range(2):  # 2 x 3 attempts = 6 recorded failures >= threshold 5
        gw.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]})
    assert proxy_gateway.BREAKER.state == "OPEN"
    # breaker OPEN -> the next divert fails fast without touching the worker
    calls_before = len([c for c in script.calls if c["url"] == WORKER])
    gw.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]})
    calls_after = len([c for c in script.calls if c["url"] == WORKER])
    assert calls_after <= calls_before + 1  # HALF-OPEN probe at most


def test_disconnect_drains_in_flight():
    """F27: client disconnect mid-stream must decrement in_flight (real server)."""
    import socket
    import threading
    import time

    import uvicorn

    # free port
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    config = uvicorn.Config(proxy_gateway.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    try:
        async def client_flow():
            sc = script_upstream()
            proxy_gateway.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(sc))
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with client.stream(
                    "POST",
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "q"}], "stream": True},
                ) as resp:
                    async for _ in resp.aiter_bytes():
                        break  # read one chunk, then abort
            # give the server a moment to observe the disconnect
            await anyio.sleep(0.3)
            return proxy_gateway.app.state.in_flight

        in_flight = anyio.run(client_flow)
        assert in_flight == 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def script_upstream():
    from helpers import PRIMARY, WORKER, chunk, DONE

    calls = []

    async def handler(request):
        url = str(request.url)
        calls.append(url)

        async def agen():
            for i in range(200):  # long stream so the client aborts mid-way
                yield chunk(f"tok{i} ").encode()
            yield DONE.encode()

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=agen())

    return handler


def test_concurrent_streams_all_complete(gw, script):
    script.script(PRIMARY, [("sse", [chunk("concurrent ok", finish="stop"), DONE])])
    import concurrent.futures

    def one(i):
        return gw.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": f"q{i}"}]}).text

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(4)))
    assert all("concurrent ok" in r for r in results)
    assert proxy_gateway._METRICS["requests_total"] == 4
    assert proxy_gateway._METRICS["in_flight"] == 0

