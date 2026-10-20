"""Speculative dual-dispatch (B9/B11 fixes).

Dispatches to both models concurrently via build_request() + send(stream=True)
under an AsyncExitStack (B9: AsyncClient.stream() is an async CM, not
awaitable - the legacy asyncio.gather(...) form raised TypeError).

- Gated by should_hedge() (B11): the CALLER checks the gate before invoking
  hedge_stream; hedging on every request doubles cost and halves concurrency.
- Reasoning deltas are never counted toward COMMIT_TOKENS and never screened
  (F1/B21): committing to the sovereign during deliberation would leak the error,
  and a model thinking "I cannot help" must not trip the refusal detector. They
  ARE forwarded live by default (HEDGE_LIVE_REASONING=1) so the client watches
  all the thinking as it happens; =0 holds them until the commit decision.
- Commit rules: timeout/error -> worker; >= COMMIT_TOKENS content tokens or
  [DONE]/finish -> sovereign (buffer replayed verbatim); the worker path
  discards the sovereign buffer entirely and appends the provenance footnote.

Yields OpenAI-format SSE chunks ("data: {...}\n\n") so the streaming endpoint
can forward them verbatim.
"""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from typing import AsyncGenerator

import httpx

from routing_patterns import classify_status, footnote, is_routable, normalise, should_hedge

import abliteration_keys

# `hedge_settings` never existed (the module-level instance is SETTINGS), so
# `from speculative_hedge import *` raised ImportError on the phantom name.
__all__ = ["hedge_stream", "make_client", "HedgeSettings", "SETTINGS"]


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
        # Worker (hedge) credential. Mirrors proxy_gateway._specialist_key() so
        # the two slots resolve the SAME way - a hedge branch that is handed
        # "none" sends no Authorization header and dies with a 401 against any
        # hosted provider. Order: WORKER_API_KEY -> SPECIALIST_API_KEY ->
        # FALLBACK_API_KEY -> NANOGPT_API_KEY -> "none" (the local hub's sentinel).
        self.worker_key = (
            os.getenv("WORKER_API_KEY")
            or os.getenv("SPECIALIST_API_KEY")
            or os.getenv("FALLBACK_API_KEY")
            or os.getenv("NANOGPT_API_KEY")
            or "none"
        )
        self.worker_model = os.getenv("WORKER_MODEL") or os.getenv(
            "FALLBACK_MODEL", "Qwen3.6-35B-A3B-abliterated-NVFP4-MTP"
        )
        # CALIBRATED 2026-10-05 (evals/hedge_calibrate.py): the refusal regex is
        # anchored to the start of the generation and fires by the 5th content
        # word in the worst case (median 2), so a 10-token window catches every
        # detectable refusal with 2x margin. 25 was 2.5x more than needed and
        # made the client wait 0.59s for the first visible token instead of
        # 0.24s (measured at 42.3 tok/s on the gx10).
        self.commit_tokens = _int_env("COMMIT_TOKENS", 10)
        # Output cap, sent as BOTH max_tokens and max_completion_tokens. Hive's
        # self-hosted models (deepseek-ai/deepseek-v4.1-flash, zai-org/glm-5.3-flash)
        # honour only max_completion_tokens: given max_tokens alone they spend the
        # whole budget on hidden reasoning, and glm-5.3-flash returns ZERO content
        # (measured 2026-10-07: max_tokens=2000 -> 0 chars content, finish=length;
        # max_completion_tokens=2000 -> 6461 chars). Unknown fields are ignored by
        # other OpenAI-compatible servers, so sending both is safe.
        self.max_tokens = _int_env("HEDGE_MAX_TOKENS", 4096)
        # Sovereign-open retries, branched on the classify_status taxonomy
        # (B10): 408/429 retry the SAME provider, 5xx retry then divert,
        # 4xx fail fast. Mirrors MAX_ATTEMPTS / RETRY_BASE_DELAY on the
        # gateway's Settings so both surfaces behave the same way.
        self.max_attempts = _int_env("HEDGE_MAX_ATTEMPTS", 3)
        self.retry_base_delay = _int_env("HEDGE_RETRY_BASE_DELAY_MS", 250) / 1000.0
        # Live thinking (default ON, operator preference 2026-10-05): forward the
        # sovereign's reasoning deltas the moment they arrive instead of holding
        # them until the commit decision. It is still never counted and never
        # screened (F1/B21); set HEDGE_LIVE_REASONING=0 to hold it again.
        self.live_reasoning = os.getenv("HEDGE_LIVE_REASONING", "1") == "1"
        self.system_prompt = os.getenv("SPECIALIST_SYSTEM", "") or None


SETTINGS = HedgeSettings()

log = logging.getLogger("speculative_hedge")

# F8 observability. A worker branch that failed used to collapse into a bare
# `worker = None` with the exception discarded, so a request could fall back to
# the sovereign without a single trace in any log or metric. Counted and logged
# from here on: `transport_error` = connect/read blew up, `bad_status` = it
# answered but not with 2xx (the common one being 404 model_not_found while the
# specialist's weights are still loading after a reboot).
_FAILURES = {"transport_error": 0, "bad_status": 0, "empty_sovereign": 0}


def hedge_failure_counts() -> dict:
    """Snapshot for the gateway's /metrics endpoint."""
    return dict(_FAILURES)


async def _body_snippet(resp, limit: int = 200) -> str:
    """Best-effort error body, for the log only. Never raises."""
    try:
        return (await resp.aread())[:limit].decode("utf-8", "replace").replace("\n", " ")
    except Exception:  # noqa: BLE001 - diagnostics must never mask the real path
        return "<unreadable>"


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
    tools=None,
    tool_choice=None,
) -> AsyncGenerator[bytes, None]:
    """Dual-dispatch. Caller MUST gate on should_hedge() first (B11).
    An injected client (same host as the gateway, e.g. app.state.http) is
    reused; otherwise a dedicated client is created and closed here.
    tools/tool_choice are forwarded to BOTH branches (F6 parity: the
    primary and divert paths forward them, so a hedged agentic request
    must not lose them either)."""
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

            # F6 parity for the hedge: the primary and the divert path forward
            # the caller's tool definitions, so a hedged agentic request must
            # not lose them either - the sovereign races the worker and either
            # branch may need to act, not just answer in prose.
            sovereign_payload = {"model": s.sovereign_model, "messages": messages, "stream": True,
                                 "max_tokens": s.max_tokens,
                                 "max_completion_tokens": s.max_tokens}
            worker_payload = {"model": s.worker_model, "messages": worker_msgs, "stream": True,
                              "max_tokens": s.max_tokens,
                              "max_completion_tokens": s.max_tokens}
            for _payload in (sovereign_payload, worker_payload):
                if tools:
                    _payload["tools"] = tools
                if tool_choice:
                    _payload["tool_choice"] = tool_choice

            worker = None
            try:
                worker = await stack.enter_async_context(open_stream(
                    client,
                    "POST",
                    s.worker_url,
                    json=worker_payload,
                    headers=abliteration_keys.pooled_headers(
                        {**_auth_header(s.worker_key), "Content-Type": "application/json"},
                        s.worker_url),
                ))
            except httpx.TransportError as exc:
                worker = None
                _FAILURES["transport_error"] += 1
                log.warning("worker %s unreachable: %s", s.worker_model, type(exc).__name__)

            # B10 taxonomy on the sovereign OPEN, not a blanket `not ok ->
            # divert`: the old rule collapsed every non-2xx (and 408/429 in
            # particular, where the provider explicitly asked for a retry of
            # the SAME model) into a worker divert.
            #   ok                  -> screen the race below
            #   retry_same (408/429) -> retry the SAME provider; exhausted
            #                           means DISCLOSE, never a worker divert
            #   retry_then_divert    -> retry, then divert to the worker
            #   fail_fast (4xx)      -> disclose, no retry, no divert
            #   divert (transport)   -> worker, as before (Tier 1)
            sovereign = None
            sovereign_class = "divert"  # classify_status(None): transport failure
            attempts = max(1, int(s.max_attempts or 1))
            for attempt in range(1, attempts + 1):
                try:
                    resp = await stack.enter_async_context(open_stream(
                        client,
                        "POST",
                        s.sovereign_url,
                        json=sovereign_payload,
                        headers=abliteration_keys.pooled_headers(
                            {**_auth_header(s.sovereign_key), "Content-Type": "application/json"},
                            s.sovereign_url),
                    ))
                except httpx.TransportError as exc:
                    sovereign = None  # B10: an unreachable sovereign means DIVERT, not fail
                    _FAILURES["transport_error"] += 1
                    log.warning("sovereign %s unreachable: %s", s.sovereign_model, type(exc).__name__)
                    break
                sovereign_class = classify_status(resp.status_code)
                if sovereign_class == "ok":
                    sovereign = resp
                    break
                # Non-2xx: observe (F8) and release the connection now; the
                # AsyncExitStack close on an already-closed response is a no-op.
                snippet = await _body_snippet(resp)
                with contextlib.suppress(Exception):
                    await resp.aclose()
                _FAILURES["bad_status"] += 1
                log.warning("sovereign %s answered HTTP %d: %s",
                            s.sovereign_model, resp.status_code, snippet)
                if attempt < attempts:
                    await asyncio.sleep(min(s.retry_base_delay * 2 ** (attempt - 1), 4.0))
                    continue
                break

            if sovereign is None and worker is None:
                yield f"data: {json.dumps({'error': 'speculative dispatch failed: both branches unreachable'})}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return

            if sovereign is None and sovereign_class in ("retry_same", "fail_fast"):
                # Exhausted retry_same / fail_fast: exactly like open_primary's
                # PrimaryOpenError(status, divert=False) on the coordinator
                # path - disclosed, never silently diverted to the worker.
                yield f"data: {json.dumps({'error': f'sovereign {s.sovereign_model} unavailable ({sovereign_class}); no divert (B10)'})}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return

            worker_ok = worker is not None and classify_status(worker.status_code) == "ok"

            if worker is not None and not worker_ok:
                _FAILURES["bad_status"] += 1
                log.warning("worker %s answered HTTP %d: %s",
                            s.worker_model, worker.status_code, await _body_snippet(worker))

            use_worker = sovereign is None and sovereign_class in ("divert", "retry_then_divert")
            commit_sovereign = False
            buffered = []  # held lines, replayed verbatim on sovereign commit
            screen_text = ""  # delta.content ONLY - reasoning never screens (F1/B21)
            content_tokens = 0
            exhausted = False  # sovereign body fully read ([DONE] seen)

            if sovereign is not None:
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
                        if not isinstance(ev, dict):
                            # Non-dict SSE payload (a bare list/string/number):
                            # the old isinstance guards ran AFTER ev.get("choices")
                            # and were dead code - one such event killed the whole
                            # hedge stream with AttributeError. Unscreenable, so
                            # skip it (same as an unparseable line).
                            continue
                        raw_choices = ev.get("choices")
                        choice = (
                            raw_choices[0]
                            if isinstance(raw_choices, list)
                            and raw_choices
                            and isinstance(raw_choices[0], dict)
                            else {}
                        )
                        delta = choice.get("delta") or {}
                        finish = choice.get("finish_reason")
                        if finish == "timeout" or delta.get("error") or ev.get("error"):
                            use_worker = True  # Tier 1: timeout/error -> worker
                            break
                        reasoning = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or delta.get("thinking")
                        )
                        if reasoning:
                            # F1/B21 is KEPT: reasoning is never counted toward the
                            # commit window and never screened for refusals (a
                            # model that thinks "I cannot help" must not trip the
                            # detector). CHANGED 2026-10-05 by operator preference:
                            # it IS forwarded live, so the client watches all the
                            # model's thinking as it happens instead of waiting for
                            # the commit point. Tradeoff: on a divert the
                            # sovereign's thinking has already been shown - the
                            # ANSWER still comes from the specialist, footnoted.
                            # HEDGE_LIVE_REASONING=0 restores the held behaviour.
                            if s.live_reasoning:
                                yield f"{line}\n\n".encode()
                            else:
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

            # Empty-sovereign rule (2026-10-07, found live): a sovereign that
            # finishes with ZERO content tokens answered nothing. Measured on
            # zai-org/glm-5.3-flash, whose hidden reasoning can consume the whole
            # output cap and end with finish_reason=length and an empty content
            # stream (and on deepseek-ai/deepseek-v4.1-flash before the
            # max_completion_tokens fix). Committing to that hands the caller a
            # blank page with HTTP 200, no footnote and no signal. Treat it as a
            # failed sovereign and divert to the worker.
            if commit_sovereign and content_tokens == 0 and not use_worker:
                commit_sovereign = False
                use_worker = True
                _FAILURES["empty_sovereign"] += 1
                log.warning("sovereign %s finished with no content -> worker",
                            s.sovereign_model)

            # F8: a screened-out sovereign is never something we may fall back TO.
            # `use_worker` is True here only because screening caught a refusal, a
            # timeout, or an error event in the sovereign's own output. Replaying
            # the sovereign just because the specialist is unavailable hands the
            # caller the primary's refusal as if it were the answer - no footnote,
            # no finish_reason, no audit signal beyond the hedge marker. That is the
            # exact M1 leak this gateway exists to prevent, and it fires whenever the
            # specialist is briefly unusable (404 model_not_found while weights
            # reload after a reboot, which is how it was found). Disclose instead.
            screened_out = use_worker
            if not worker_ok:
                if screened_out:
                    log.warning("sovereign %s screened out with no specialist "
                                "available; withholding sovereign output",
                                s.sovereign_model)
                    yield f"data: {json.dumps({'error': 'specialist unavailable; sovereign output withheld (refusal/timeout/error/empty detected)'})}\n\n".encode()
                    yield b"data: [DONE]\n\n"
                    return
                use_worker = False  # sovereign is clean and there is nowhere to divert

            if commit_sovereign or (not use_worker and sovereign is not None):
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


