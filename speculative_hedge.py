"""Speculative dual-dispatch (B9/B11 fixes).

Dispatches to both models concurrently via build_request() + send(stream=True)
under an AsyncExitStack (B9: AsyncClient.stream() is an async CM, not
awaitable - the legacy asyncio.gather(...) form raised TypeError).

- Gated by should_hedge() (B11): the CALLER checks the gate before invoking
  hedge_stream; hedging on every request doubles cost and halves concurrency.
- Reasoning deltas are HELD but never counted toward COMMIT_TOKENS (F1/B21):
  committing to the sovereign during deliberation would leak the error.
- Commit rules: timeout/error -> worker; >= COMMIT_TOKENS content tokens or
  [DONE]/finish -> sovereign (buffer replayed verbatim); the worker path
  discards the sovereign buffer entirely and appends the provenance footnote.

Yields OpenAI-format SSE chunks ("data: {...}\n\n") so the streaming endpoint
can forward them verbatim.
"""

import contextlib
import json
import os
import uuid
from typing import AsyncGenerator

import httpx

from routing_patterns import classify_status, footnote, is_routable, normalise, should_hedge

__all__ = ["hedge_stream", "hedge_settings", "make_client", "HedgeSettings"]


def _int_env(name, default):
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class HedgeSettings:
    """Env-derived; module-level instance so tests can monkeypatch."""

    def __init__(self):
        self.reload()

    def reload(self):
        self.sovereign_url = os.getenv("SOVEREIGN_API_URL") or os.getenv(
            "PRIMARY_API_URL", "https://api.openai.com/v1/chat/completions"
        )
        self.sovereign_key = os.getenv("SOVEREIGN_API_KEY") or os.getenv("PRIMARY_API_KEY", "")
        self.sovereign_model = os.getenv("SOVEREIGN_MODEL") or os.getenv("PRIMARY_MODEL", "gpt-4o")
        self.worker_url = os.getenv("WORKER_API_URL") or os.getenv(
            "FALLBACK_API_URL", "http://127.0.0.1:8000/v1/chat/completions"
        )
        self.worker_key = os.getenv("WORKER_API_KEY") or os.getenv("FALLBACK_API_KEY", "none")
        self.worker_model = os.getenv("WORKER_MODEL") or os.getenv(
            "FALLBACK_MODEL", "Qwen3.6-35B-A3B-abliterated-NVFP4-MTP"
        )
        self.commit_tokens = _int_env("COMMIT_TOKENS", 25)
        self.system_prompt = os.getenv("SPECIALIST_SYSTEM", "") or None


SETTINGS = HedgeSettings()


def make_client() -> httpx.AsyncClient:
    """Injectable for tests (monkeypatch with a MockTransport-backed client)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=180.0))


@contextlib.asynccontextmanager
async def open_stream(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    req = client.build_request(method, url, **kwargs)
    resp = await client.send(req, stream=True)
    try:
        yield resp
    finally:
        await resp.aclose()


def _auth_header(key: str):
    if not key or key == "none":
        return {}
    return {"Authorization": f"Bearer {key}"}


def _last_user_text(messages):
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, list):
                return normalise("\n".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content))
            return str(content or "")
    return ""


def _chunk(delta, finish=None, model="", stream_id=""):
    return json.dumps(
        {
            # R1: one id per STREAM (see proxy_gateway._delta_chunk).
            "id": stream_id or f"hedge-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        },
        ensure_ascii=False,
    )


async def hedge_stream(
    messages,
    *,
    request_id=None,
    settings: HedgeSettings = None,
    client: httpx.AsyncClient = None,
) -> AsyncGenerator[bytes, None]:
    """Dual-dispatch. Caller MUST gate on should_hedge() first (B11).
    An injected client (same host as the gateway, e.g. app.state.http) is
    reused; otherwise a dedicated client is created and closed here."""
    s = settings or SETTINGS
    from context_formatter import DEFAULT_SYSTEM

    sid = f"hedge-{uuid.uuid4().hex[:12]}"  # R1: one id for the whole stream

    worker_msgs = [
        {"role": "system", "content": s.system_prompt or DEFAULT_SYSTEM},
        {"role": "user", "content": _last_user_text(messages)},
    ]

    own_client = client is None
    if own_client:
        client = make_client()
    try:
        async with contextlib.AsyncExitStack() as stack:

            sovereign_cm = open_stream(
                client,
                "POST",
                s.sovereign_url,
                json={"model": s.sovereign_model, "messages": messages, "stream": True},
                headers={**_auth_header(s.sovereign_key), "Content-Type": "application/json"},
            )
            worker_cm = open_stream(
                client,
                "POST",
                s.worker_url,
                json={"model": s.worker_model, "messages": worker_msgs, "stream": True},
                headers={**_auth_header(s.worker_key), "Content-Type": "application/json"},
            )
            try:
                sovereign = await stack.enter_async_context(sovereign_cm)
            except httpx.TransportError:
                sovereign = None  # B10: an unreachable sovereign means DIVERT, not fail
            try:
                worker = await stack.enter_async_context(worker_cm)
            except httpx.TransportError:
                worker = None
            if sovereign is None and worker is None:
                yield f"data: {json.dumps({'error': 'speculative dispatch failed: both branches unreachable'})}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return

            sovereign_ok = sovereign is not None and classify_status(sovereign.status_code) == "ok"
            worker_ok = worker is not None and classify_status(worker.status_code) == "ok"

            use_worker = not sovereign_ok
            commit_sovereign = False
            buffered = []  # held lines, replayed verbatim on sovereign commit
            screen_text = ""  # delta.content ONLY - reasoning never screens (F1/B21)
            content_tokens = 0
            exhausted = False  # sovereign body fully read ([DONE] seen)

            if sovereign_ok:
                try:
                    async for raw in sovereign.aiter_lines():
                        line = raw.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        body = line[5:].strip()
                        if body == "[DONE]":
                            commit_sovereign = True
                            buffered.append(line)
                            exhausted = True
                            break
                        try:
                            ev = json.loads(body)
                        except json.JSONDecodeError:
                            continue
                        choices = ev.get("choices") or [{}]
                        delta = (choices[0].get("delta") or {}) if isinstance(ev, dict) else {}
                        finish = choices[0].get("finish_reason") if isinstance(ev, dict) else None
                        if finish == "timeout" or delta.get("error") or ev.get("error"):
                            use_worker = True  # Tier 1: timeout/error -> worker
                            break
                        reasoning = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or delta.get("thinking")
                        )
                        if reasoning:  # F1/B21: held, never counted, never screened
                            buffered.append(line)
                            continue
                        content = delta.get("content") or ""
                        if content:
                            buffered.append(line)
                            screen_text += content
                            content_tokens += 1
                            if is_routable(screen_text):
                                use_worker = True
                                break
                            if content_tokens >= s.commit_tokens:
                                commit_sovereign = True
                                break
                        if finish:
                            commit_sovereign = True
                            buffered.append(line)
                            break
                except httpx.TransportError:
                    use_worker = True  # sovereign died mid-screening

            if not worker_ok:
                use_worker = False  # nowhere to divert; surface the sovereign as-is

            if commit_sovereign or (not use_worker and sovereign_ok):
                async for chunk in _replay_sovereign(sovereign, buffered, exhausted=exhausted):
                    yield chunk
                return

            if use_worker:
                async for chunk in _drain_worker(worker, s, sid):
                    yield chunk
                return

            yield f"data: {json.dumps({'error': 'sovereign refused/unavailable and specialist unavailable'})}\n\n".encode()
            yield b"data: [DONE]\n\n"
    finally:
        if own_client:
            await client.aclose()


def buffered_text(lines) -> str:
    """Concatenate delta.content across held lines (refusal screening)."""
    out = []
    for line in lines:
        body = line[5:].strip() if line.startswith("data:") else line
        if body == "[DONE]":
            continue
        try:
            ev = json.loads(body)
            delta = (ev.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                out.append(delta["content"])
        except (json.JSONDecodeError, AttributeError, IndexError):
            continue
    return "".join(out)


async def _replay_sovereign(sovereign, buffered, *, exhausted: bool = False) -> AsyncGenerator[bytes, None]:
    for line in buffered:
        yield f"{line}\n\n".encode()
    if exhausted:
        return  # body fully read at [DONE]; re-iterating raises StreamConsumed
    # remaining sovereign stream verbatim - single continuous pass (B7)
    try:
        async for raw in sovereign.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            yield f"{line}\n\n".encode()
            if line.replace("data:", "").strip() == "[DONE]":
                return
    except httpx.StreamConsumed:
        return


async def _drain_worker(worker, s, stream_id: str = "") -> AsyncGenerator[bytes, None]:
    """Stream the worker, then disclose the diversion.

    R4: the OpenAI contract says `finish_reason` is the LAST thing a stream
    says - no content may follow it. The footnote is content, so the upstream
    finish chunk is HELD, the footnote is emitted, and an equivalent finish
    chunk (carrying the upstream's own reason, e.g. "length" on a truncated
    answer) is emitted after it. A chunk that carries content AND a finish
    reason is split rather than dropped.
    """
    finish_reason = None
    async for raw in worker.aiter_lines():
        line = raw.strip()
        if not line or not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            break
        try:
            ev = json.loads(body)
            choice = (ev.get("choices") or [{}])[0]
            reason = choice.get("finish_reason")
            if ev.get("id"):
                # R1: adopt the worker's stream id - the footnote we append is
                # part of THAT stream, so it must not introduce a second id.
                stream_id = ev["id"]
        except (json.JSONDecodeError, AttributeError, IndexError):
            ev, choice, reason = None, {}, None
        if reason:
            finish_reason = reason
            delta = choice.get("delta") or {}
            if not any(delta.get(k) for k in ("content", "reasoning_content", "tool_calls")):
                continue  # pure finish marker: held until after the footnote
            ev["choices"][0]["finish_reason"] = None  # keep the content, hold the finish
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
            continue
        yield f"{line}\n\n".encode()
    yield (
        f"data: {_chunk({'content': footnote(s.worker_model)}, finish=None, model=s.worker_model, stream_id=stream_id)}\n\n".encode()
    )
    yield (
        f"data: {_chunk({}, finish=finish_reason or 'stop', model=s.worker_model, stream_id=stream_id)}\n\n".encode()
    )
    yield b"data: [DONE]\n\n"


