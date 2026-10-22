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

import routing_patterns
import account_pool

from routing_patterns import classify_status, footnote, is_routable, normalise, should_hedge, stage_comment

import abliteration_keys

# `hedge_settings` never existed (the module-level instance is SETTINGS), so
# `from speculative_hedge import *` raised ImportError on the phantom name.
__all__ = ["hedge_stream", "race_stream", "make_client", "HedgeSettings", "SETTINGS"]


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
        # self-hosted models (deepseek-ai/deepseek-v4.1-flash-1017, zai-org/glm-5.3-flash)
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
    escalate=None,
) -> AsyncGenerator[bytes, None]:
    """Dual-dispatch. Caller MUST gate on should_hedge() first (B11).
    An injected client (same host as the gateway, e.g. app.state.http) is
    reused; otherwise a dedicated client is created and closed here.
    tools/tool_choice are forwarded to BOTH branches (F6 parity: the
    primary and divert paths forward them, so a hedged agentic request
    must not lose them either).

    escalate (2026-10-21): a callable refusal_text -> chunk iterator. When
    wired, a raced WORKER that opens with a refusal never ships - the caller
    (proxy_gateway) escalates to the uncensored terminal instead. Screening is
    ACTIVE ONLY when escalate is wired, so pure-unit callers keep the historic
    drain-and-footnote behaviour."""
    s = settings or SETTINGS
    from context_formatter import DEFAULT_SYSTEM  # local: avoids an import cycle
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
                # Multi-account pool: the worker branch picks its credential
                # the same way open_fallback does (fail-closed to s.worker_key).
                _w_headers, _w_acct = account_pool.routed_headers(
                    {**_auth_header(s.worker_key), "Content-Type": "application/json"},
                    s.worker_url)
                worker = await stack.enter_async_context(open_stream(
                    client,
                    "POST",
                    s.worker_url,
                    json=worker_payload,
                    headers=_w_headers,
                ))
            except httpx.TransportError as exc:
                account_pool.observe_result(_w_acct, None)
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
                    _s_headers, _s_acct = account_pool.routed_headers(
                        {**_auth_header(s.sovereign_key), "Content-Type": "application/json"},
                        s.sovereign_url)
                    resp = await stack.enter_async_context(open_stream(
                        client,
                        "POST",
                        s.sovereign_url,
                        json=sovereign_payload,
                        headers=_s_headers,
                    ))
                except httpx.TransportError as exc:
                    account_pool.observe_result(_s_acct, None)
                    sovereign = None  # B10: an unreachable sovereign means DIVERT, not fail
                    _FAILURES["transport_error"] += 1
                    log.warning("sovereign %s unreachable: %s", s.sovereign_model, type(exc).__name__)
                    break
                account_pool.observe_result(_s_acct, resp.status_code)
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
            # stream (and on deepseek-ai/deepseek-v4.1-flash-1017 before the
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
                # STAGE COLOUR: the sovereign (helm) branch won the race.
                yield stage_comment("helm", s.sovereign_model)
                async for chunk in _replay_sovereign(sovereign, buffered, exhausted=exhausted):
                    yield chunk
                return

            if use_worker:
                # STAGE COLOUR: the raced worker branch answers.
                yield stage_comment("hedge", s.worker_model)
                # M1 parity (2026-10-21): a raced middle that opens with a
                # refusal never ships. Screen its first commit window and, when
                # the gateway wired `escalate`, climb to the uncensored
                # terminal instead of streaming the worker's refusal.
                state = {}
                async for chunk in _drain_worker(worker, s, sid, state=state,
                                                 screen=escalate is not None):
                    yield chunk
                if state.get("refused") and escalate is not None:
                    async for chunk in escalate(state.get("text") or ""):
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


async def _drain_worker(worker, s, stream_id: str = "",
                        state: dict = None, screen: bool = False) -> AsyncGenerator[bytes, None]:
    """Stream the worker, then disclose the diversion.

    R4: the OpenAI contract says `finish_reason` is the LAST thing a stream
    says - no content may follow it. The footnote is content, so the upstream
    finish chunk is HELD, the footnote is emitted, and an equivalent finish
    chunk (carrying the upstream's own reason, e.g. "length" on a truncated
    answer) is emitted after it. A chunk that carries content AND a finish
    reason is split rather than dropped.

    screen=True (set only when the caller wired an escalation): the first
    commit window of delta.content is run through is_routable; a worker that
    OPENS with a refusal sets state["refused"]/["text"], stops streaming and
    returns early so the refusal never ships - the caller escalates instead.
    """
    finish_reason = None
    screen_text = ""
    screened_tokens = 0
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
        if screen and ev is not None:
            # M1 parity: screen BEFORE any yield so a refusal chunk carrying
            # finish_reason can never ship first.
            delta_c = (choice.get("delta") or {}).get("content") or ""
            if delta_c:
                screen_text += delta_c
                screened_tokens += 1
                if is_routable(screen_text):
                    if state is not None:
                        state["refused"] = True
                        state["text"] = screen_text
                    with contextlib.suppress(Exception):
                        await worker.aclose()
                    return
                if screened_tokens >= max(1, int(s.commit_tokens or 1)):
                    screen = False  # committed clean: the rest streams verbatim
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


# ---------------------------------------------------------------------------
# T-D chain 5 - RACE:DEEPMAX/GLMMAX>ABLITV2L (2026-10-22). The hedge's commit
# machinery generalized to TWO SOVEREIGN CANDIDATES: both max-reasoning helms
# fire in parallel, the first CLEAN (refusal-free) substantive answer commits
# and wins, and the loser is CANCELLED MID-STREAM (cancel-on-commit). Every
# rule is the hedge's own, applied per candidate:
#   - COMMIT_TOKENS counts delta.content only; reasoning deltas are never
#     counted and never screened (F1/B21) - a model thinking "I cannot help"
#     must not trip the refusal detector.
#   - a candidate whose content window anchors a refusal (is_routable) drops
#     out of the race; a timeout/error event kills it; an exhausted-clean
#     candidate (stream ended, [DONE] seen, no refusal, substantive) wins.
#   - the winner's buffer replays VERBATIM (buffer replay), then its stream
#     is forwarded live to [DONE].
#   - all candidates refusing/failing escalates via `escalate` - the chain
#     terminal (any refusal from both -> terminal).
# Holding (not live-forwarding) both candidates' reasoning is deliberate:
# two racing deliberation streams would interleave into garbage on the wire;
# the loser's buffer dies with it.
# ---------------------------------------------------------------------------
async def race_stream(
    messages,
    *,
    settings: HedgeSettings = None,
    candidates=(),
    escalate=None,
    client: httpx.AsyncClient = None,
    min_substantive_chars: int = 20,
    tools=None,
    tool_choice=None,
) -> AsyncGenerator[bytes, None]:
    """Two-sovereign race. `candidates` is an ordered list of
    (url, key, model_id, max_reasoning) tuples - (helm, middle) hops of the
    RACE chain. `escalate` is a callable text -> chunk iterator wired to the
    chain terminal; it fires only when EVERY candidate refused/failed.
    An injected client (the gateway's app.state.http) is reused; otherwise
    a dedicated client is created and closed here (hedge parity)."""
    s = settings or SETTINGS
    sid = f"race-{uuid.uuid4().hex[:12]}"  # R1: one id for the whole stream
    commit_window = max(1, int(s.commit_tokens or 1))
    min_subst = max(1, int(min_substantive_chars or 1))

    def _clean_commit(r):
        """The commit rule: past COMMIT_TOKENS content tokens, refusal-free,
        and substantive (the answer must be worth committing)."""
        return (r["content_tokens"] >= commit_window
                and not r["refused"]
                and len(r["screen_text"].strip()) >= min_subst)

    def _exhaust_clean_commit(r):
        """Stream ended without refusing, with substantive content on the
        record: the full buffer replays verbatim (hedge's [DONE] commit)."""
        return (not r["refused"] and r["content_tokens"] > 0
                and len(r["screen_text"].strip()) >= min_subst)
    # RACE-PART-1B
    own_client = client is None
    if own_client:
        client = make_client()
    try:
        async with contextlib.AsyncExitStack() as stack:
            racers = []
            for url, key, model_id, max_reasoning in candidates:
                payload = {
                    "model": model_id,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": s.max_tokens,
                    "max_completion_tokens": s.max_tokens,
                }
                if max_reasoning:
                    # The DEEPMAX/GLMMAX knob set: the chain NAME promises
                    # max reasoning on BOTH candidates. Same convention set
                    # as the gateway's max-think injection (unknown fields
                    # are ignored by OpenAI-compatible upstreams).
                    payload["reasoning_effort"] = "max"
                    payload["reasoning"] = {"effort": "max"}
                    payload["reasoning_content"] = True
                    payload["enable_thinking"] = True
                    payload["chat_template_kwargs"] = {"thinking": True}
                    payload["thinking"] = {"type": "enabled"}
                if tools:
                    payload["tools"] = tools
                if tool_choice:
                    payload["tool_choice"] = tool_choice
                resp = None
                try:
                    # Multi-account pool parity: each candidate picks its
                    # credential the same way the hedge branches do.
                    headers, acct = account_pool.routed_headers(
                        {**_auth_header(key), "Content-Type": "application/json"}, url)
                    resp = await stack.enter_async_context(
                        open_stream(client, "POST", url, json=payload, headers=headers))
                except httpx.TransportError:
                    account_pool.observe_result(acct, None)
                    resp = None
                    _FAILURES["transport_error"] += 1
                    log.warning("race candidate %s unreachable", model_id)
                if resp is None:
                    continue
                if classify_status(resp.status_code) != "ok":
                    account_pool.observe_result(acct, resp.status_code)
                    snippet = await _body_snippet(resp)
                    _FAILURES["bad_status"] += 1
                    log.warning("race candidate %s answered HTTP %d: %s",
                                model_id, resp.status_code, snippet)
                    with contextlib.suppress(Exception):
                        await resp.aclose()
                    continue
                account_pool.observe_result(acct, resp.status_code)
                racers.append({
                    "resp": resp,
                    "model": model_id,
                    "buffered": [],      # held lines, replayed verbatim on commit
                    "screen_text": "",  # delta.content ONLY (F1/B21)
                    "content_tokens": 0,
                    "refused": False,
                    "exhausted": False,
                    "dead": False,
                })

            if not racers:
                if escalate is not None:
                    async for chunk in escalate("all candidates unreachable"):
                        yield chunk
                    return
                yield f"data: {json.dumps({'error': 'race: all candidates unreachable'})}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return
            # RACE-PART-2
            # Reader tasks push each candidate's lines into one FIFO queue;
            # the main loop applies the commit rules per line. Queue order is
            # arrival order, so the first candidate to actually DELIVER a
            # clean substantive window wins the race (never the open order).
            queue: asyncio.Queue = asyncio.Queue()
            _END = object()

            async def _reader(r):
                try:
                    async for raw in r["resp"].aiter_lines():
                        await queue.put((r, raw))
                except Exception as exc:  # noqa: BLE001 - a dead reader must not sink the race
                    log.warning("race reader %s failed: %s", r["model"], type(exc).__name__)
                finally:
                    await queue.put((r, _END))

            readers = [asyncio.create_task(_reader(r)) for r in racers]
            winner = None
            saw_done = False

            def _any_alive():
                return any(not r["dead"] for r in racers)

            try:
                while winner is None:
                    r, item = await queue.get()
                    if r["dead"]:
                        # dropped candidate: discard its tail lines; when the
                        # LAST candidate drops the race is decided (lost).
                        if not _any_alive():
                            break
                        continue
                    if item is _END:
                        r["exhausted"] = True
                        r["dead"] = True
                        if _exhaust_clean_commit(r):
                            winner = r
                        elif not _any_alive():
                            break
                        continue
                    line = (item or "").strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        r["buffered"].append(line)  # upstream SSE comment: keep
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        r["buffered"].append(line)
                        r["exhausted"] = True
                        r["dead"] = True
                        if _exhaust_clean_commit(r):
                            winner = r
                        elif not _any_alive():
                            break
                        continue
                    try:
                        ev = json.loads(body)
                    except json.JSONDecodeError:
                        r["buffered"].append(line)
                        continue
                    if not isinstance(ev, dict):
                        r["buffered"].append(line)
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
                    r["buffered"].append(line)
                    # Tier-1 metadata intercept (hedge parity): a timeout or
                    # an error event kills the candidate, never the stream.
                    if choice.get("finish_reason") == "timeout" or delta.get("error") or ev.get("error"):
                        r["dead"] = True
                        if not _any_alive():
                            break
                        continue
                    content = delta.get("content")
                    if content:
                        r["screen_text"] += content
                        r["content_tokens"] += 1
                        if is_routable(r["screen_text"]):
                            # Zero-refusal law: a candidate that opens (or
                            # stays) in a refusal never wins the race.
                            r["refused"] = True
                            r["dead"] = True
                            log.info("race candidate %s refused; dropped", r["model"])
                            if not _any_alive():
                                break
                            continue
                        if _clean_commit(r):
                            winner = r
                # RACE-PART-3
                if winner is not None:
                    # CANCEL-ON-COMMIT: the loser is cancelled mid-stream -
                    # its buffer dies with it, its stage never ships.
                    for r in racers:
                        if r is not winner and not r["exhausted"]:
                            with contextlib.suppress(Exception):
                                await r["resp"].aclose()
                    # STAGE COLOUR: the winning candidate answers as the helm.
                    yield stage_comment("helm", winner["model"])
                    for line in winner["buffered"]:
                        yield f"{line}\n\n".encode()
                    if winner["exhausted"]:
                        # the exhausted-clean commit carries its own [DONE] as
                        # the last buffered line - the stream is complete.
                        return
                    # The winner's remaining lines keep flowing through the
                    # queue (single continuous pass, B7 parity): forward
                    # them live until its [DONE] / stream end.
                    while True:
                        r, item = await queue.get()
                        if r is not winner:
                            continue
                        if item is _END:
                            break
                        line = (item or "").strip()
                        if not line:
                            continue
                        if line.replace("data:", "", 1).strip() == "[DONE]":
                            saw_done = True
                            yield f"{line}\n\n".encode()
                            break
                        yield f"{line}\n\n".encode()
                    if not saw_done:
                        # The winner's stream ended bare (upstream dropped
                        # the tail): terminate the client stream properly.
                        yield f"data: {_chunk({}, finish='stop', model=winner['model'], stream_id=sid)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                    return
                # winner is None: every candidate refused / failed / exhausted
                # dirty - BOTH refused climbs to the uncensored terminal.
                for r in racers:
                    if not r["exhausted"]:
                        with contextlib.suppress(Exception):
                            await r["resp"].aclose()
                if escalate is not None:
                    async for chunk in escalate("all candidates refused or failed"):
                        yield chunk
                    return
                yield f"data: {json.dumps({'error': 'race: every candidate refused and no terminal was wired'})}\n\n".encode()
                yield b"data: [DONE]\n\n"
            finally:
                for t in readers:
                    t.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(*readers, return_exceptions=True)
    finally:
        if own_client:
            await client.aclose()


