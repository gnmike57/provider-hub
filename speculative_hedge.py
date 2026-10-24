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
import re
import time
import uuid
from typing import AsyncGenerator

import httpx

import routing_patterns
import account_pool

from routing_patterns import classify_status, footnote, is_routable, normalise, should_hedge, stage_comment, hop_comment, LENGTH_CONTINUE_INSTRUCTION

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
        # FALLBACK_API_KEY -> ABLITERATION_API_KEY -> "none" (the local hub's
        # sentinel; the retired nano provider's key left the chain 2026-10-23).
        self.worker_key = (
            os.getenv("WORKER_API_KEY")
            or os.getenv("SPECIALIST_API_KEY")
            or os.getenv("FALLBACK_API_KEY")
            or os.getenv("ABLITERATION_API_KEY")
            or "none"
        )
        self.worker_model = os.getenv("WORKER_MODEL") or os.getenv(
            "FALLBACK_MODEL", "abliterated-model-large-v2"
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


# (I1, 2026-10-23 live matrix) MARKER LAW: [[GW-*]] protocol markers never
# ship. The completion contract teaches the checklist, so race winners echo
# it into the client stream - scrub every winner line before it yields.
_GW_MARKER_RE = re.compile(r"\s*\[\[GW-[A-Z]+(?::[^\]]*)?\]\]")


def _scrub_gw_markers(text):
    return _GW_MARKER_RE.sub("", text or "")


def _scrub_line(line):
    """A `data: ...` SSE line with [[GW-*]] markers stripped from its
    content (trailing newlines preserved on the rebuilt line)."""
    if "[" not in (line or ""):
        return line
    core = (line or "").rstrip("\r\n")
    tail = (line or "")[len(core):]
    try:
        ev = json.loads(core[5:].strip())
        ch = (ev.get("choices") or [{}])[0] or {}
        d = ch.get("delta") or {}
        if isinstance(d.get("content"), str) and d["content"]:
            d["content"] = _scrub_gw_markers(d["content"])
            return "data: " + json.dumps(ev, ensure_ascii=False) + tail
    except Exception:  # noqa: BLE001 - unparseable: verbatim
        pass
    return line


# (I1b, 2026-10-23 live forensic) a marker SPLIT across delta chunks
# ([[GW-CHE|CKLIST]]) reassembled in the client stream past the line-local
# scrub. Worse: Hive streams ~2-4 chars per delta, so the marker arrives
# SHATTERED across many lines and no single line even contains "[[GW-" -
# every substring guard missed it. This scrubber engages on ANY "[[" and
# carries an unterminated marker-ish tail between lines: a complete marker
# never ships, however finely it is split; flush() releases any plain
# remainder (dropping a never-closed fragment) at stream end.


# (RACE v2, operator directive 2026-10-23 evening) LIVE PEER-LEARNING: the
# second candidate opens WITH the first candidate's clean partial in context
# ("learn from each other as they are both working towards the same
# solution"). A draft that anchors a refusal - or reads watered-down
# ("possibly refusing") - NEVER seeds a peer: such a candidate is SILENCED
# for the remainder of the race.


def _race_peer_learning_on():
    return os.getenv("RACE_PEER_LEARNING", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _race_peer_min_chars():
    try:
        return max(20, int(os.getenv("RACE_PEER_MIN_CHARS", "120")))
    except ValueError:
        return 120


def _race_peer_max_wait_ms():
    try:
        return max(200, int(os.getenv("RACE_PEER_MAX_WAIT_MS", "2500")))
    except ValueError:
        return 2500


# (2026-10-24, operator directive) CLEAN THINKING knobs: the sovereign's
# live reasoning coalesces into calm chunks instead of Hive's 2-4 char
# delta jitter. THINK_CHUNK_CHARS/THINK_EVERY_S tune the cadence.
# (T2, 2026-10-24 operator tactic) REFUSAL-ARC CUT: the max-reasoning
# lanes' DELIBERATION is watched for refusal arcs - cut mid-thought, the
# same brain re-asked with reasoning OFF + a minimal continue nudge (the
# no-reasoning mode refuses far less). Screening the deliberation is a
# deliberate, scoped exception to F1/B21: it only ever triggers the
# cheaper retry, never diverts the answer.
_ARC_RE = re.compile(
    r"i (?:cannot|can't|can not|should not|shouldn't|won't|will not)"
    r"|i(?:'m| am) (?:not |un)able to|\brefuse\b|sorry", re.I)


def _race_arc_retry_on():
    return os.getenv("RACE_ARC_RETRY", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _thinking_off_payload(model_id):
    if "deep" in str(model_id or "").lower():
        return {"reasoning_effort": "none"}
    return {"reasoning_effort": "none", "enable_thinking": False,
            "chat_template_kwargs": {"thinking": False},
            "thinking": {"type": "disabled"}}


def _think_chunk():
    try:
        return max(60, int(os.getenv("THINK_CHUNK_CHARS", "180")))
    except ValueError:
        return 180


def _think_every_s():
    try:
        return max(0.1, float(os.getenv("THINK_EVERY_S", "0.5")))
    except ValueError:
        return 0.5


def _think_clean(t):
    return re.sub(r"\n{3,}", "\n\n", t or "")


def _race_grace_ms():
    """(RACE v2) the winner chooser's grace: after the first clean commit,
    other candidates get this long to also commit; the best FINAL answer
    (substantiveness + completion) wins instead of merely the fastest."""
    try:
        return max(0, int(os.getenv("RACE_GRACE_MS", "2000")))
    except ValueError:
        return 2000


def _inject_peer_draft(messages, draft):
    """The peer draft rides BEFORE the trailing user turn - the pinned
    presignal shape holds (the conversation still ends on the ask)."""
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    note = ("PEER DRAFT - another model is working the same ask and has "
            "produced the partial answer below. Learn from it, correct "
            "anything wrong in it, and give your OWN complete answer:\n\n"
            + (draft or ""))
    last = msgs[-1] if msgs and msgs[-1].get("role") == "user" else None
    if last is None:
        return msgs + [{"role": "user", "content": note}]
    return msgs[:-1] + [{"role": "user", "content": note}, last]


def _peer_seed_ok(text):
    """A peer draft may seed only when CLEAN: no refusal core AND no
    watered-down/deflection costume (zero_refusal_violation)."""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    return routing_patterns.zero_refusal_violation(t) is None


class _MarkerScrubber:
    # any unterminated marker-ish tail: a lone "[", "[[", "[[G, "[[GW-",
    # "[[GW-CHEC", "[[GW-CHECKLIST, and 0-2 closing brackets. (Live capture
    # 2026-10-23: the marker arrived as ["[", "[GW-C", "HECKLIST", "]]..."] -
    # a SINGLE bracket opened it, so the hold must engage from "[" alone.
    # Whitespace is held ONLY as a marker prefix (\s*\[) - a bare trailing
    # space is payload, never held.
    _PARTIAL = re.compile(r"(?:\s*\[\[(?:G?W?-?[A-Z]*(?::[^\]]*)?)?\]?\]?|\s*\[)?$")

    def __init__(self):
        self.carry = ""
        self.last_id = None

    def text(self, t):
        buf = self.carry + (t or "")
        self.carry = ""
        m = self._PARTIAL.search(buf)
        if m:
            self.carry = m.group(0)
            buf = buf[:m.start()]
        return _GW_MARKER_RE.sub("", buf)

    def line(self, ln):
        """A `data: ...` SSE line scrubbed through the carry state. The
        input may carry its own trailing newlines (the relay passes whole
        byte-chunks) - they are preserved on the rebuilt line."""
        if "[" not in (ln or "") and not self.carry:
            return ln
        core = (ln or "").rstrip("\r\n")
        tail = (ln or "")[len(core):]
        try:
            ev = json.loads(core[5:].strip())
            if ev.get("id"):
                self.last_id = ev["id"]
            ch = (ev.get("choices") or [{}])[0] or {}
            d = ch.get("delta") or {}
            if isinstance(d.get("content"), str) and d["content"]:
                d["content"] = self.text(d["content"])
                out = "data: " + json.dumps(ev, ensure_ascii=False) + tail
                if "[[GW-" in out:
                    # (I1b live forensic) a marker escaped the scrub - the
                    # regexes must cover every shipped shape; log it loudly.
                    log.error("marker escape after scrub: %s", out[:200])
                return out
        except Exception:  # noqa: BLE001 - unparseable: verbatim
            pass
        return ln

    def flush_line(self):
        """The final content line releasing any held plain text, or None."""
        out = _GW_MARKER_RE.sub("", self.carry)
        out = self._PARTIAL.sub("", out)  # a never-closed marker is dropped
        self.carry = ""
        if not out:
            return None
        return ("data: " + json.dumps(
            {"id": self.last_id,
             "choices": [{"delta": {"content": out}}]},
            ensure_ascii=False) + "\n\n")

# (2026-10-23 efficiency matrix) TRUE upstream spend: every generated char
# the hub receives from any provider branch - winners, shadow-race losers,
# escalations, continuations - counted exactly once. Surfaced via
# proxy_gateway.metrics_snapshot() as hedge_upstream_chars_total; the
# efficiency matrix divides by 4 for a token estimate.
_UPSTREAM_CHARS = {"n": 0}


def _bump_upstream(n):
    try:
        _UPSTREAM_CHARS["n"] += int(n or 0)
    except Exception:  # noqa: BLE001 - accounting never kills the stream
        pass


def hedge_upstream_chars():
    """Snapshot for the gateway's /metrics + /healthz."""
    return _UPSTREAM_CHARS["n"]


# F8 observability. A worker branch that failed used to collapse into a bare
# `worker = None` with the exception discarded, so a request could fall back to
# the sovereign without a single trace in any log or metric. Counted and logged
# from here on: `transport_error` = connect/read blew up, `bad_status` = it
# answered but not with 2xx (the common one being 404 model_not_found while the
# specialist's weights are still loading after a reboot).
_FAILURES = {"transport_error": 0, "bad_status": 0, "empty_sovereign": 0}

# S4 RACE OUTCOMES (2026-10-22): which candidate ROLE wins the race and how
# many length-finish continuations fired - surfaced through
# proxy_gateway.metrics_snapshot() as race_won_<role>_total /
# race_length_continue_total (same accessor pattern as hedge_failure_counts).
_RACE_OUTCOMES = {"won_helm": 0, "won_middle": 0, "length_continue": 0,
                 "refusal_tail": 0}


def race_outcome_counts() -> dict:
    return dict(_RACE_OUTCOMES)


def reset_race_outcomes() -> None:
    """Test hermeticity: zero the outcome counters (the shared script
    fixture calls this per test, like BREAKER / stickiness)."""
    for k in _RACE_OUTCOMES:
        _RACE_OUTCOMES[k] = 0


def _length_continue_on() -> bool:
    """S1 kill switch: LENGTH_AUTO_CONTINUE=0 restores the bare
    length-finish cut (default on)."""
    try:
        return int(os.getenv("LENGTH_AUTO_CONTINUE", "1") or 1) != 0
    except Exception:  # noqa: BLE001
        return True


def _race_length_continue_max_rounds() -> int:
    """S1 OVERKILL (2026-10-22): the race winner's continuation rounds bound.
    Same env/contract as the gateway's _length_continue_max_rounds
    (LENGTH_CONTINUE_MAX_ROUNDS, default 5, clamp 0..50; 0 = never)."""
    try:
        n = int(os.getenv("LENGTH_CONTINUE_MAX_ROUNDS", "5") or 5)
    except Exception:  # noqa: BLE001
        n = 5
    return max(0, min(n, 50))


def _chain_reasoning_effort() -> str:
    """S2 CHAIN_REASONING_EFFORT (2026-10-22): the thinking budget for the
    max-reasoning chain hops. Default "max" keeps the chain NAME's promise;
    "medium"/"low" caps runaway deliberation that starves the visible
    answer (measured live: a reply died at exactly 8192 output tokens
    with ~7.7k of them spent on thinking)."""
    return os.getenv("CHAIN_REASONING_EFFORT", "max") or "max"


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

    # (BR-1, operator directive 2026-10-23 evening) HEDGE_RACE_MODE: the
    # hedge's shadow-race becomes a TRUE commit-race - both branches stream
    # for real, the first clean substantive answer commits and WINS (the race
    # rules: F1/B21 screening, refusal-silencing, peer-learning, the grace
    # chooser, cancel-on-commit). The DEEP/GLM middle stops being a
    # failure-only fallback and contributes on every request; both refusing
    # escalates via `escalate` exactly as before. Kill switch:
    # HEDGE_RACE_MODE=0 restores the shadow-race.
    if (os.getenv("HEDGE_RACE_MODE", "1").strip().lower()
            not in ("0", "false", "no", "off")
            and s.worker_url and s.sovereign_url and escalate is not None):
        _own = client is None
        if _own:
            client = make_client()
        async for chunk in race_stream(
                messages,
                settings=s,
                candidates=[
                    # (T1, 2026-10-24) MIDDLE-FIRST: the no-reasoning middle
                    # opens as candidate 0 and commits by default; the
                    # max-think sovereign opens held behind it. Knob-free
                    # postures: the candidates' reasoning posture stays the
                    # caller's business (None = model defaults).
                    (s.worker_url, s.worker_key, s.worker_model, None),
                    (s.sovereign_url, s.sovereign_key, s.sovereign_model,
                     None)],
                escalate=escalate,
                client=client,
                tools=tools,
                tool_choice=tool_choice,
                labels=("middle", "helm")):
            yield chunk
        if _own:
            with contextlib.suppress(Exception):
                await client.aclose()
        return
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
            # (2026-10-24) CLEAN THINKING: the coalesced-reasoning buffer.
            _think = {"buf": "", "t": time.monotonic()}

            def _think_flush():
                out = _think_clean(_think["buf"])
                _think["buf"] = ""
                _think["t"] = time.monotonic()
                return out

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
                        # (efficiency matrix) the sovereign's true spend
                        _bump_upstream(
                            len(str(delta.get("content") or ""))
                            + len(str(delta.get("reasoning_content")
                                      or delta.get("reasoning")
                                      or delta.get("thinking") or "")))
                        _r_raw = (delta.get("reasoning_content")
                                  or delta.get("reasoning")
                                  or delta.get("thinking"))
                        # (2026-10-24) a thinking delta is a STRING; a
                        # truthy NON-string flag marks the delta's CONTENT
                        # as thinking (the max-think knob shape, kept by
                        # fixtures) - either way the text lands in the
                        # thinking channel exactly once.
                        _mixed = False
                        if isinstance(_r_raw, str) and _r_raw:
                            reasoning = _r_raw
                        elif _r_raw and (delta.get("content") or ""):
                            reasoning = delta.get("content")
                            _mixed = True
                        else:
                            reasoning = None
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
                                # (2026-10-24, operator directive) CLEAN
                                # THINKING: Hive streams 2-4 chars per
                                # delta - raw forwarding made the client's
                                # thinking panel jitter line by line. The
                                # deltas COALESCE into calm ~180-char /
                                # 0.5s chunks with collapsed whitespace;
                                # the remainder flushes at stream end.
                                _think["buf"] += str(reasoning)
                                if (len(_think["buf"]) >= _think_chunk()
                                        or (time.monotonic() - _think["t"])
                                        >= _think_every_s()):
                                    _out = _think_flush()
                                    if _out:
                                        yield ("data: " + json.dumps(
                                            {"id": sid,
                                             "object": "chat.completion.chunk",
                                             "model": s.sovereign_model,
                                             "choices": [{"index": 0,
                                                          "delta": {
                                                              "reasoning_content":
                                                                  _out},
                                                          "finish_reason":
                                                              None}]},
                                            ensure_ascii=False)
                                            + "\n\n").encode()
                            else:
                                buffered.append(line)
                            if not _mixed:
                                continue
                            # a mixed (thinking-flagged content) delta:
                            # the thinking channel carries its text, so the
                            # content branch must not buffer it twice.
                        content = delta.get("content") or ""
                        if content and not _mixed:
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
            # (2026-10-24) CLEAN THINKING: whatever reasoning is still held
            # flushes once, calmly, at the sovereign loop's end - before the
            # commit/divert decision, so no thought is ever lost.
            _tr = _think_flush()
            if _tr:
                yield ("data: " + json.dumps(
                    {"id": sid, "object": "chat.completion.chunk",
                     "model": s.sovereign_model,
                     "choices": [{"index": 0,
                                  "delta": {"reasoning_content": _tr},
                                  "finish_reason": None}]},
                    ensure_ascii=False) + "\n\n").encode()

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
    # (I1b, 2026-10-23 live matrix) the sovereign's replayed buffer is where
    # a terminal's [[GW-SKILL]]/[[GW-CHECKLIST]] echo shipped raw (chain-1
    # L_story leak) - the marker law holds on EVERY shipped line, and the
    # scrubber carries a chunk-split marker across lines.
    scrub = _MarkerScrubber()
    for line in buffered:
        if (line.startswith("data:") and line[5:].strip() == "[DONE]"
                and scrub.carry):
            _fl = scrub.flush_line()
            if _fl:
                yield _fl.encode()  # carry never trails [DONE]
        yield f"{scrub.line(line)}\n\n".encode()
    if exhausted:
        _fl = scrub.flush_line()  # a bare-ended buffer releases the carry
        if _fl:
            yield _fl.encode()
        return  # body fully read at [DONE]; re-iterating raises StreamConsumed
    # remaining sovereign stream verbatim - single continuous pass (B7)
    try:
        async for raw in sovereign.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            if (line.startswith("data:")
                    and line.replace("data:", "", 1).strip() == "[DONE]"
                    and scrub.carry):
                _fl = scrub.flush_line()
                if _fl:
                    yield _fl.encode()
            yield f"{scrub.line(line)}\n\n".encode()
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
    scrub = _MarkerScrubber()  # (I1b) the marker law on every shipped line
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
        if ev is not None:
            # (efficiency matrix) the worker branch's true spend
            _d = choice.get("delta") or {}
            _bump_upstream(
                len(str(_d.get("content") or ""))
                + len(str(_d.get("reasoning_content") or _d.get("reasoning")
                          or "")))
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
            yield f"{scrub.line('data: ' + json.dumps(ev, ensure_ascii=False))}\n\n".encode()
            continue
        yield f"{scrub.line(line)}\n\n".encode()
    _fl = scrub.flush_line()
    if _fl:
        yield _fl.encode()  # any held plain text releases before the footnote
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
    labels=(),
) -> AsyncGenerator[bytes, None]:
    """Two-sovereign race. `candidates` is an ordered list of
    (url, key, model_id, max_reasoning) tuples - (helm, middle) hops of the
    RACE chain; `labels` optionally names the roles for the S4 outcome
    counters (default: helm for the first candidate, middle for the
    second). `escalate` is a callable text -> chunk iterator wired to the
    chain terminal; it fires only when EVERY candidate refused/failed.
    An injected client (the gateway's app.state.http) is reused; otherwise
    a dedicated client is created and closed here (hedge parity)."""
    s = settings or SETTINGS
    sid = f"race-{uuid.uuid4().hex[:12]}"  # R1: one id for the whole stream
    commit_window = max(1, int(s.commit_tokens or 1))
    min_subst = max(1, int(min_substantive_chars or 1))

    def _finish_reason_of(line):
        """finish_reason of a data: SSE line, or None (never raises)."""
        try:
            ev = json.loads(line[5:].strip())
            ch = (ev.get("choices") or [{}])[0]
            return ch.get("finish_reason")
        except Exception:  # noqa: BLE001
            return None

    def _strip_length_finish(line):
        """A length finish can ride the SAME line as a content delta (the
        test harness and some upstreams put both on one line). Returns
        (stripped_line, content) so the content keeps flowing into the
        winner's replay/tally while ONLY the finish is held; None when the
        finish rode an empty delta (nothing to keep)."""
        try:
            ev = json.loads(line[5:].strip())
            ch = (ev.get("choices") or [{}])[0]
            d = ch.get("delta") or {}
            content = str(d.get("content") or "")
            # S1 REASONING (2026-10-23): a reasoning-only cut line still
            # carries a payload the client must see - keep the line, hold
            # only the finish (the winner's replay must not drop it).
            if not content:
                content = str(d.get("reasoning_content")
                              or d.get("reasoning") or "")
            if not content:
                return None
            ev2 = dict(ev)
            ch2 = dict(ch)
            ch2["finish_reason"] = None
            ev2["choices"] = [ch2]
            return f"data: {json.dumps(ev2)}", content
        except Exception:  # noqa: BLE001
            return None

    async def _open_winner_continue(r, partial):
        """S1 LENGTH AUTO-CONTINUE: open ONE continuation stream for a
        length-cut winner (same hop, partial answer in context). Returns
        the streaming response, or None when it cannot open - the caller
        then ships the held finish (never a client error)."""
        payload = {
            "model": r["model"],
            "messages": list(messages) + [
                {"role": "assistant", "content": partial},
                {"role": "user", "content": LENGTH_CONTINUE_INSTRUCTION},
            ],
            "stream": True,
            "max_tokens": s.max_tokens,
            "max_completion_tokens": s.max_tokens,
        }
        if r.get("max_reasoning"):
            effort = _chain_reasoning_effort()
            payload["reasoning_effort"] = effort
            payload["reasoning"] = {"effort": effort}
            payload["reasoning_content"] = True
            payload["enable_thinking"] = True
            payload["chat_template_kwargs"] = {"thinking": True}
            payload["thinking"] = {"type": "enabled"}
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        try:
            headers, acct = account_pool.routed_headers(
                {**_auth_header(r["key"]), "Content-Type": "application/json"},
                r["url"])
            resp = await client.send(
                client.build_request(
                    "POST", r["url"], json=payload, headers=headers),
                stream=True)
        except Exception:  # noqa: BLE001 - continuation is best-effort
            return None
        if classify_status(resp.status_code) != "ok":
            account_pool.observe_result(acct, resp.status_code)
            with contextlib.suppress(Exception):
                await resp.aclose()
            return None
        account_pool.observe_result(acct, resp.status_code)
        return resp

    def _clean_commit(r):
        """The commit rule: past COMMIT_TOKENS output tokens, refusal-free,
        and substantive (the answer must be worth committing)."""
        # S1 REASONING (live defect 2026-10-23): reasoning deltas count as
        # OUTPUT for the commit window - a reasoning-only candidate used to
        # never commit (content_tokens stayed 0) so the race escalated to the
        # terminal on a perfectly alive stream. Refusal SCREENING stays
        # content-only (F1/B21): a model deliberating "I cannot" must not trip
        # the refusal detector on its thinking.
        # (T4b, 2026-10-24) a "suspect_partial" window (it reads like the
        # watered-down costume) cannot commit - but it is NOT silenced: if
        # the answer turns clean, the flag clears and it commits.
        return (r["content_tokens"] + r["reasoning_tokens"] >= commit_window
                and not r["refused"]
                and not r.get("suspect_partial")
                and len((r["screen_text"] + r["reasoning_text"]).strip()) >= min_subst)

    def _exhaust_clean_commit(r):
        """Stream ended without refusing, with substantive content on the
        record: the full buffer replays verbatim (hedge's [DONE] commit)."""
        return (not r["refused"]
                and r["content_tokens"] + r["reasoning_tokens"] > 0
                and len((r["screen_text"] + r["reasoning_text"]).strip()) >= min_subst)
    # RACE-PART-1B
    own_client = client is None
    if own_client:
        client = make_client()
    try:
        async with contextlib.AsyncExitStack() as stack:
            racers = []
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

            readers = []
            for i, (url, key, model_id, max_reasoning) in enumerate(candidates):
                _draft = ""
                if i > 0 and racers and _race_peer_learning_on():
                    # (RACE v2, operator directive) LIVE PEER-LEARNING: hold
                    # this candidate until the FIRST has a clean partial (or
                    # the wait cap) - then open it WITH the peer's draft in
                    # context. Both models work the same solution and the
                    # second learns from the first's live progress. A draft
                    # that anchors a refusal NEVER seeds a peer.
                    _t0w = time.monotonic()
                    while True:
                        _lead = racers[0]
                        if (len(_lead.get("screen_text") or "")
                                >= _race_peer_min_chars()
                                or (time.monotonic() - _t0w) * 1000.0
                                >= _race_peer_max_wait_ms()
                                or _lead.get("dead")):
                            break
                        await asyncio.sleep(0.15)
                    _draft = (racers[0].get("screen_text") or "").strip()
                    if _peer_seed_ok(_draft):
                        _RACE_OUTCOMES["peer_seeded"] = (
                            _RACE_OUTCOMES.get("peer_seeded", 0) + 1)
                    else:
                        _draft = ""
                payload = {
                    "model": model_id,
                    "messages": (_inject_peer_draft(messages, _draft)
                                if _draft else messages),
                    "stream": True,
                    "max_tokens": s.max_tokens,
                    "max_completion_tokens": s.max_tokens,
                }
                if max_reasoning is None:
                    # (BR-1) knob-free posture: the hedge delegation races the
                    # branches exactly as the shadow-race opened them - the
                    # model's own defaults apply.
                    pass
                elif max_reasoning:
                    # The DEEPMAX/GLMMAX knob set: the chain NAME promises
                    # max reasoning on BOTH candidates. Same convention set
                    # as the gateway's max-think injection (unknown fields
                    # are ignored by OpenAI-compatible upstreams). The effort
                    # itself is env-tunable (S2 CHAIN_REASONING_EFFORT).
                    effort = _chain_reasoning_effort()
                    payload["reasoning_effort"] = effort
                    payload["reasoning"] = {"effort": effort}
                    payload["reasoning_content"] = True
                    payload["enable_thinking"] = True
                    payload["chat_template_kwargs"] = {"thinking": True}
                    payload["thinking"] = {"type": "enabled"}
                else:
                    # REASONING-MODE RACE (2026-10-23): the NO-reasoning
                    # candidate of a max-vs-plain self-race - the thinking-
                    # disable conventions of the gateway's _thinking_off_knobs
                    # (DeepSeek exposes the real reasoning_effort:none; GLM
                    # flash is low/high/max only, so it gets the full disable
                    # set - docs/single-model-chain-plan). Only race chains
                    # with a plain-flagged middle reach this branch (the
                    # twin-max race flags both candidates).
                    if "deep" in str(model_id or "").lower():
                        payload["reasoning_effort"] = "none"
                    else:
                        payload.update({
                            "reasoning_effort": "none",
                            "enable_thinking": False,
                            "chat_template_kwargs": {"thinking": False},
                            "thinking": {"type": "disabled"},
                        })
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
                    # S1/S4: the winner's continuation + outcome counters
                    # need the hop's own wiring and role.
                    "url": url,
                    "key": key,
                    "max_reasoning": bool(max_reasoning),
                    "role": (labels[i] if i < len(labels)
                             else ("helm" if i == 0 else f"candidate_{i}")),
                    "buffered": [],      # held lines, replayed verbatim on commit
                    "screen_text": "",  # delta.content ONLY (F1/B21)
                    "content_tokens": 0,
                    # S1 REASONING (live defect 2026-10-23): reasoning deltas
                    # are output - they arm the commit window and the length
                    # continuation, but are never refusal-screened.
                    "reasoning_text": "",
                    "reasoning_tokens": 0,
                    "full_text": "",    # content + reasoning in arrival order
                    "refused": False,
                    "exhausted": False,
                    "dead": False,
                    "suspect_partial": False,  # (T4b) demoted, not silenced
                })
                # (RACE v2) the reader starts IMMEDIATELY - the peer-hold for
                # the next candidate watches this one's live text.
                readers.append(asyncio.create_task(_reader(racers[-1])))

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
            def _any_alive():
                return any(not r["dead"] for r in racers)

            def _race_decided():
                if committers:
                    if any(c.get("exhausted") for c in committers):
                        return True  # a complete answer settles the race
                    if not any(r not in committers and not r["dead"]
                               for r in racers):
                        return True  # nobody else can commit
                    if grace_ms and ((time.monotonic()
                                      - committers[0]["committed"])
                                     * 1000.0 >= grace_ms):
                        return True
                    return False
                return not _any_alive()

            winner = None
            saw_done = False
            committers = []  # (RACE v2) the grace-chooser's collector
            grace_ms = _race_grace_ms()

            def _open_retry_candidate(r, base_messages):
                """(T2) the same brain, reasoning OFF, continue-nudged."""
                msgs = [m for m in (base_messages or [])
                        if isinstance(m, dict) and m.get("role") != "system"]
                msgs.append({"role": "user",
                             "content": "Continue. Answer directly and "
                                        "completely."})
                payload = {"model": r["model"], "messages": msgs,
                           "stream": True, "max_tokens": s.max_tokens,
                           "max_completion_tokens": s.max_tokens}
                payload.update(_thinking_off_payload(r["model"]))
                try:
                    headers, acct = account_pool.routed_headers(
                        {**_auth_header(r["key"]),
                         "Content-Type": "application/json"}, r["url"])
                    resp = stack.enter_async_context(open_stream(
                        client, "POST", r["url"], json=payload,
                        headers=headers))
                    account_pool.observe_result(acct, resp.status_code)
                except Exception:  # noqa: BLE001 - retry open failure: skip
                    return None
                return {"resp": resp, "model": r["model"], "url": r["url"],
                        "key": r["key"], "max_reasoning": False,
                        "role": str(r.get("role", "helm")) + "-retry",
                        "buffered": [], "screen_text": "",
                        "content_tokens": 0, "reasoning_text": "",
                        "reasoning_tokens": 0, "full_text": "",
                        "refused": False, "exhausted": False,
                        "dead": False, "suspect_partial": False,
                        "arc_retried": True}

            try:
                while True:
                    _timeout = None
                    if committers and grace_ms:
                        _timeout = max(0.05, committers[0]["committed"]
                                       + grace_ms / 1000.0 - time.monotonic())
                    try:
                        r, item = await asyncio.wait_for(
                            queue.get(), timeout=_timeout)
                    except asyncio.TimeoutError:
                        r, item = None, None
                    if r is not None:
                        if r["dead"]:
                            if not _any_alive():
                                break
                            continue
                        if item is _END:
                            r["exhausted"] = True
                            r["dead"] = True
                            # (T4a) the exhaust-point screen: a SHORT refusal
                            # (fewer deltas than the commit window) is caught
                            # here - it must never commit.
                            if is_routable(r["screen_text"]):
                                r["refused"] = True
                            if _exhaust_clean_commit(r):
                                r["committed"] = time.monotonic()
                                committers.append(r)
                            elif not _any_alive():
                                break
                            continue
                        line = (item or "").strip()
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            r["buffered"].append(line)  # upstream SSE comment
                            continue
                        body = line[5:].strip()
                        if body == "[DONE]":
                            r["buffered"].append(line)
                            r["exhausted"] = True
                            r["dead"] = True
                            # (T4a) the exhaust-point screen.
                            if is_routable(r["screen_text"]):
                                r["refused"] = True
                            if _exhaust_clean_commit(r):
                                r["committed"] = time.monotonic()
                                committers.append(r)
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
                        if choice.get("finish_reason") == "timeout" or delta.get("error") or ev.get("error"):
                            r["dead"] = True
                            if not _any_alive():
                                break
                            continue
                        content = delta.get("content")
                        if content:
                            r["screen_text"] += content
                            r["content_tokens"] += 1
                            r["full_text"] += content
                            _bump_upstream(len(content))
                            # (T4a, 2026-10-24 divert-avoidance) the refusal
                            # screen runs at the COMMIT-POINT window, not on
                            # every partial accumulation - mid-sentence
                            # phrases ("I cannot emphasize enough") used to
                            # trip it and falsely divert to the V2.
                            if (is_routable(r["screen_text"])
                                    and r["content_tokens"] >= commit_window):
                                # (RACE v2, operator directive) a candidate
                                # that BRINGS UP REFUSING is SILENCED for
                                # the remainder of the race.
                                r["refused"] = True
                                r["dead"] = True
                                _RACE_OUTCOMES["silenced"] = (
                                    _RACE_OUTCOMES.get("silenced", 0) + 1)
                                log.info("race candidate %s refused; silenced",
                                         r["model"])
                                if not _any_alive():
                                    break
                                continue
                            # (T4b) "possibly refusing" (the watered-down
                            # costume) DEMOTES, never silences: the candidate
                            # keeps streaming but cannot commit while it
                            # reads partial; the V2 is reached only if it
                            # never turns clean.
                            _pv = routing_patterns.zero_refusal_violation(
                                r["screen_text"])
                            if _pv == "partial":
                                r["suspect_partial"] = True
                            elif _pv is None:
                                r["suspect_partial"] = False
                            if _clean_commit(r):
                                r["committed"] = time.monotonic()
                                committers.append(r)
                        else:
                            # S1 REASONING: output; never refusal-screened
                            # (F1/B21), counts toward the commit window.
                            _r = delta.get("reasoning_content") or delta.get("reasoning")
                            if _r:
                                _r = str(_r)
                                r["reasoning_text"] += _r
                                r["reasoning_tokens"] += 1
                                r["full_text"] += _r
                                _bump_upstream(len(_r))
                                # (T2) REFUSAL-ARC CUT: a max-reasoning lane
                                # deliberating toward refusal is cut and the
                                # same brain re-asked with reasoning OFF.
                                if (r.get("max_reasoning")
                                        and not r.get("arc_retried")
                                        and _ARC_RE.search(
                                            r["reasoning_text"][-260:])):
                                    r["refused"] = True
                                    r["dead"] = True
                                    r["arc_retried"] = True
                                    _RACE_OUTCOMES["arc_cuts"] = (
                                        _RACE_OUTCOMES.get("arc_cuts", 0) + 1)
                                    log.info("race candidate %s refusal arc; "
                                             "cut for a no-reasoning retry",
                                             r["model"])
                                    if _race_arc_retry_on():
                                        _retry = _open_retry_candidate(
                                            r, messages)
                                        if _retry is not None:
                                            racers.append(_retry)
                                            readers.append(
                                                asyncio.create_task(
                                                    _reader(_retry)))
                                            _RACE_OUTCOMES["arc_retries"] = (
                                                _RACE_OUTCOMES.get(
                                                    "arc_retries", 0) + 1)
                                    if not _any_alive():
                                        break
                                    continue
                    if _race_decided():
                        break
                if committers:
                    # (RACE v2) the improved FINAL-RESPONSE chooser: among
                    # the committers collected inside the grace window, the
                    # best answer wins - substantiveness first, a COMPLETED
                    # answer (exhausted-clean) outranks a partial.
                    def _commit_score(c):
                        _sc = len((c["screen_text"] + c["reasoning_text"]).strip())
                        if c.get("exhausted"):
                            _sc += 500
                        return _sc

                    winner = max(committers, key=_commit_score)
                    if len(committers) > 1:
                        _RACE_OUTCOMES["grace_decided"] = (
                            _RACE_OUTCOMES.get("grace_decided", 0) + 1)
                    else:
                        _RACE_OUTCOMES["fast_lane"] = (
                            _RACE_OUTCOMES.get("fast_lane", 0) + 1)
                # RACE-PART-3
                if winner is not None:
                    # CANCEL-ON-COMMIT: the loser is cancelled mid-stream -
                    # its buffer dies with it, its stage never ships.
                    for r in racers:
                        if r is not winner and not r["exhausted"]:
                            with contextlib.suppress(Exception):
                                await r["resp"].aclose()
                    # S4: which role won (chain-tuning observability).
                    _won_key = f"won_{winner['role']}"
                    _RACE_OUTCOMES[_won_key] = _RACE_OUTCOMES.get(_won_key, 0) + 1
                    # STAGE COLOUR: the winning candidate answers as the helm.
                    yield stage_comment("helm", winner["model"])
                    # S1 LENGTH AUTO-CONTINUE: a length finish is HELD (the
                    # client never sees the cut); if the switch is on and the
                    # winner actually said something, ONE seamless continuation
                    # round closes the stream instead.
                    held_finish = None
                    # S1 REASONING (live defect 2026-10-23): the continuation
                    # context is the winner's FULL output (content + reasoning
                    # in arrival order) - a reasoning-only winner used to seed
                    # an EMPTY partial and the gate below shipped the cut.
                    # (I1b) the scrubber is STATEFUL across the winner's
                    # lines - a chunk-split marker never reassembles.
                    scrub = _MarkerScrubber()
                    winner_text = winner["full_text"] or winner["screen_text"]
                    for line in winner["buffered"]:
                        if line.startswith("data:") \
                                and _finish_reason_of(line) == "length":
                            kept = _strip_length_finish(line)
                            if kept is not None:
                                # (0.1, 2026-10-23) the payload riding a
                                # BUFFERED length line was already tallied into
                                # full_text when the line first arrived - do
                                # NOT count it twice: the continuation seed
                                # must contain it exactly once. (Tail and
                                # continuation lines below were never in
                                # full_text - their kept[1] adds stay.)
                                yield f"{scrub.line(kept[0])}\n\n".encode()
                            held_finish = line
                            continue
                        if (held_finish is not None and line.startswith("data:")
                                and line[5:].strip() == "[DONE]"):
                            continue  # suppressed: the continuation closes it
                        if (line.startswith("data:")
                                and line[5:].strip() == "[DONE]"
                                and scrub.carry):
                            _fl = scrub.flush_line()
                            if _fl:
                                yield _fl.encode()  # carry never trails [DONE]
                        yield f"{scrub.line(line)}\n\n".encode()
                    if winner["exhausted"] and held_finish is None:
                        # the exhausted-clean commit carries its own [DONE] as
                        # the last buffered line - the stream is complete.
                        _fl = scrub.flush_line()
                        if _fl:
                            yield _fl.encode()
                        return
                    # The winner's remaining lines keep flowing through the
                    # queue (single continuous pass, B7 parity): forward
                    # them live until its [DONE] / stream end. (RACE v2) an
                    # EXHAUSTED winner has no remaining lines - the battle
                    # already consumed its _END - skip the tail entirely.
                    if not winner.get("exhausted"):
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
                                if held_finish is None:
                                    if scrub.carry:
                                        _fl = scrub.flush_line()
                                        if _fl:
                                            yield _fl.encode()
                                    yield f"{line}\n\n".encode()
                                break
                            if line.startswith("data:"):
                                if _finish_reason_of(line) == "length":
                                    kept = _strip_length_finish(line)
                                    if kept is not None:
                                        winner_text += kept[1]
                                        yield f"{scrub.line(kept[0])}\n\n".encode()
                                    held_finish = line
                                    continue
                                try:  # tally the live tail for the continuation
                                    _d = (((json.loads(line[5:].strip())
                                            .get("choices") or [{}])[0]
                                           .get("delta")) or {})
                                    if _d.get("content"):
                                        winner_text += str(_d["content"])
                                        _bump_upstream(len(str(_d["content"])))
                                    elif _d.get("reasoning_content") or _d.get("reasoning"):
                                        winner_text += str(
                                            _d.get("reasoning_content")
                                            or _d.get("reasoning"))
                                        _bump_upstream(len(str(
                                            _d.get("reasoning_content")
                                            or _d.get("reasoning"))))
                                except Exception:  # noqa: BLE001 - tally only
                                    pass
                            yield f"{scrub.line(line)}\n\n".encode()
                    if (held_finish is not None and _length_continue_on()
                            and winner_text.strip()):
                        # S1 OVERKILL (2026-10-22): up to
                        # LENGTH_CONTINUE_MAX_ROUNDS rounds - a continuation
                        # that ALSO cuts length gets another round (the cut
                        # finish held each time); exhausting the budget or a
                        # continuation that cannot open ships the honest cut.
                        _rounds = 0
                        while True:
                            # (RACE v2) CROSS-LEARNING: the continuation
                            # seed carries the OTHER candidate's clean partial
                            # too - both were working the same solution.
                            _seed_txt = _scrub_gw_markers(winner_text)
                            for _pr in racers:
                                if (_pr is not winner and not _pr.get("refused")
                                        and _peer_seed_ok(_pr.get("screen_text"))):
                                    _seed_txt += (
                                        "\n\nPEER ATTEMPT (another model's "
                                        "take on the same ask - use it, do not "
                                        "repeat it):\n"
                                        + _pr["screen_text"].strip()[:3000])
                                    break
                            cont = await _open_winner_continue(winner, _seed_txt)
                            if cont is None:
                                break  # ships the held finish below
                            _RACE_OUTCOMES["length_continue"] += 1
                            yield hop_comment(
                                "race",
                                "continue past token limit")
                            cont_done = False
                            cont_held = None
                            # (0.2, 2026-10-23) refusal screen state for this
                            # round (content only - F1/B21: reasoning never
                            # trips the refusal detector).
                            cont_screen = ""
                            cont_refused = False
                            try:
                                async for raw in cont.aiter_lines():
                                    cline = (raw or "").strip()
                                    if not cline:
                                        continue
                                    if (cont_held is not None
                                            and cline.startswith("data:")
                                            and cline[5:].strip() == "[DONE]"):
                                        continue  # suppressed: a round closes it
                                    if (cline.startswith("data:")
                                            and _finish_reason_of(cline) == "length"):
                                        kept = _strip_length_finish(cline)
                                        if kept is not None:
                                            winner_text += kept[1]
                                            yield f"{scrub.line(kept[0])}\n\n".encode()
                                        cont_held = cline
                                        continue
                                    if cline.startswith("data:"):
                                        try:  # tally the live tail
                                            _d = (((json.loads(cline[5:].strip())
                                                    .get("choices") or [{}])[0]
                                                    .get("delta")) or {})
                                            if _d.get("content"):
                                                cont_screen += str(_d["content"])
                                                # (0.2, 2026-10-23) ZERO-REFUSAL
                                                # LAW on the continuation tail:
                                                # a continuation that answers
                                                # with a refusal must never
                                                # ship as the race's final
                                                # answer (the primary path's
                                                # end-of-stream judges already
                                                # enforce this; the race tail
                                                # bypassed them).
                                                if is_routable(cont_screen):
                                                    cont_refused = True
                                                winner_text += str(_d["content"])
                                            elif _d.get("reasoning_content") or _d.get("reasoning"):
                                                winner_text += str(
                                                    _d.get("reasoning_content")
                                                    or _d.get("reasoning"))
                                        except Exception:  # noqa: BLE001
                                            pass
                                    if cont_refused:
                                        # the refusal chunk never ships
                                        break
                                    yield f"{scrub.line(cline)}\n\n".encode()
                                    if cline.replace("data:", "", 1).strip() \
                                            == "[DONE]":
                                        cont_done = True
                                        break
                            finally:
                                with contextlib.suppress(Exception):
                                    await cont.aclose()
                            if cont_refused:
                                # (0.2, 2026-10-23) the continuation answered
                                # with a refusal: NEVER ship it. Escalate to the
                                # terminal when wired; else the honest cut (the
                                # winner's clean partial + its held finish).
                                _RACE_OUTCOMES["refusal_tail"] += 1
                                if escalate is not None:
                                    async for chunk in escalate(
                                            "race continuation refused"):
                                        yield chunk
                                    return
                                _fl = scrub.flush_line()
                                if _fl:
                                    yield _fl.encode()
                                yield f"{held_finish}\n\n".encode()
                                yield b"data: [DONE]\n\n"
                                return
                            if cont_held is None:
                                if not cont_done:
                                    # the continuation ended bare: close properly
                                    _fl = scrub.flush_line()
                                    if _fl:
                                        yield _fl.encode()
                                    yield f"data: {_chunk({}, finish='stop', model=winner['model'], stream_id=sid)}\n\n".encode()
                                    yield b"data: [DONE]\n\n"
                                return
                            _rounds += 1
                            if (_rounds >= _race_length_continue_max_rounds()
                                    or not winner_text.strip()):
                                _fl = scrub.flush_line()
                                if _fl:
                                    yield _fl.encode()
                                yield f"{cont_held}\n\n".encode()
                                yield b"data: [DONE]\n\n"
                                return
                            # the continuation ALSO cut: another round on the
                            # accumulated text (the loop re-opens it)
                    if held_finish is not None:
                        # switch off / empty winner / continuation failed to
                        # open: the cut finish ships exactly as before.
                        _fl = scrub.flush_line()
                        if _fl:
                            yield _fl.encode()
                        yield f"{held_finish}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
                    if not saw_done:
                        # The winner's stream ended bare (upstream dropped
                        # the tail): terminate the client stream properly.
                        _fl = scrub.flush_line()
                        if _fl:
                            yield _fl.encode()
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


