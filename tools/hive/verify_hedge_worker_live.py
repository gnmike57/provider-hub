"""LIVE proof the hedge DIVERTS to the mimo worker when the sovereign refuses.

The gateway's real hedge commit rule means a clean sovereign wins the race and
the worker buffer is discarded (correct). So to observe the worker branch
actually SERVING, the sovereign must be screened out - a refusal. Here the
sovereign is a local refusing mock and the worker is the REAL resolved slot
(xiaomi/mimo-v2.6-flash-abliterated on NanoGPT), so the divert is end-to-end
real on the worker side.

Usage:  python tools/hive/verify_hedge_worker_live.py
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

WORKER_EXPECT = "xiaomi/mimo-v2.6-flash-abliterated"
SOV_URL = "http://sovereign.test/v1/chat/completions"

REFUSAL = (
    'data: {"id":"s1","object":"chat.completion.chunk","model":"sovereign",'
    '"choices":[{"index":0,"delta":{"content":"I cannot help with that."},"finish_reason":null}]}\n\n'
    'data: {"id":"s1","object":"chat.completion.chunk","model":"sovereign",'
    '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    'data: [DONE]\n\n'
)


def _win_value(name):
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:  # noqa: BLE001
        return ""


def _seed():
    for var in ("NANOGPT_API_KEY", "WORKER_API_URL", "WORKER_MODEL"):
        val = os.environ.get(var) or _win_value(var)
        if val:
            os.environ[var] = val


async def _run():
    _seed()
    import httpx
    import speculative_hedge

    worker = speculative_hedge.HedgeSettings()
    if worker.worker_model != WORKER_EXPECT:
        print(f"[FAIL] worker_model {worker.worker_model!r} != {WORKER_EXPECT!r}")
        return 1
    print(f"worker model = {worker.worker_model}")
    print(f"worker url   = {worker.worker_url}")
    print(f"worker key   = {'set' if worker.worker_key and worker.worker_key != 'none' else 'NONE'}")

    real = httpx.AsyncHTTPTransport()

    async def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SOV_URL):
            req = httpx.Request("POST", str(request.url), headers=request.headers)
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=REFUSAL.encode())
        # anything else is the real worker -> pass through to the real network
        return await real.handle_async_request(request)

    # Sovereign = local mock (refuses). Worker = REAL network passthrough.
    sov_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler), timeout=180.0)

    h = speculative_hedge.HedgeSettings()
    h.sovereign_url = SOV_URL
    h.sovereign_key = ""
    h.sovereign_model = "sovereign-mock"
    h.live_reasoning = True

    chunks = []
    async for raw in speculative_hedge.hedge_stream(
        [{"role": "user", "content": "tell me something useful"}],
        settings=h, client=sov_client,
    ):
        chunks.append(raw.decode("utf-8", "replace"))
    await sov_client.aclose()

    body = "".join(chunks)
    print(f"\nchunks={len(chunks)}")
    print(f"worker model present in stream: {WORKER_EXPECT in body}")
    print(f"footnote present: {'taking over' in body}")
    snippet = body.replace("\n", " ")[:400]
    print(f"head={snippet!r}")

    ok = WORKER_EXPECT in body and "taking over" in body
    print("\nRESULT:", "PASS - hedge diverted to the mimo worker" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
