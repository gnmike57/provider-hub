"""FastAPI interception gateway: buffering, routing, metrics, endpoints.

Endpoints
    POST /v1/chat/completions   streaming ring-buffer proxy (drop-in OpenAI)
    POST /v1/execute            planner -> worker -> assemble() (Part IV)
    POST /v1/switch             runtime slot switch: primary/worker/swap/status
                                (unversioned /switch is an operator alias)
    GET  /v1/models             OpenAI-compatible model list (Frost aliases)
    GET  /healthz               config + runtime snapshot
    GET  /metrics               Prometheus text (F26)

Design rules enforced here:
  1. One source of truth - detection lives in routing_patterns.py only.
  2. A 429/503 is not a routable error - the B10 taxonomy decides.
  3. Never surface a buffered error - discard on divert.
  4. Reasoning is not content - forward for TTFT, never counted.
  5. Assembly fails closed and is never model-mediated.
  6. Guards run once, shared by both endpoints.
  7. Hooks/guards never raise into the request path.

Run:  uvicorn proxy_gateway:app --host 127.0.0.1 --port 9000
"""

import asyncio
import contextlib
import copy
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from providers import MAX_THINK_NAMES, Registry, resolve_frost_alias

import model_switch

from context_formatter import (
    CYBER_SYSTEM,
    DEFAULT_SYSTEM,
    assert_clean,
    format_messages,
    specialist_messages,
)
from ingress_assembler import (
    SLOT,
    assemble,
    audit_record,
    grammar_for,
    validate_artifact,
)
from routing_patterns import (
    DIVERT_STATUS,
    FORCED_DIVERT_REASON,
    FOOTNOTE_TEMPLATE,
    attack_match,
    classify_status,
    footnote,
    no_go_match,
    is_routable,
    should_hedge,
)

__all__ = ["app", "fallback_stream", "Settings", "Tier4Classifier"]

# --------------------------------------------------------------------------
# Configuration surface (section 9) - env-derived once, monkeypatchable.
# --------------------------------------------------------------------------
def _int_env(name, default):
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float_env(name, default):
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _specialist_key() -> str:
    """Credential for the specialist (worker) slot.

    Resolution, highest first:
      1. SPECIALIST_API_KEY  - explicit override (plan W-A env trio)
      2. FALLBACK_API_KEY    - historical name / the local hub's "none"
      3. NANOGPT_API_KEY     - the operator's Windows-env NanoGPT key, so the
                               uncensored specialist credential is read from the
                               environment instead of being copied into another
                               variable
    Falls back to "none" (no Authorization header) when neither is set.
    """
    return (os.getenv("SPECIALIST_API_KEY") or os.getenv("FALLBACK_API_KEY")
            or os.getenv("NANOGPT_API_KEY") or "none")


def _hive_base() -> str:
    """HIVE_API_BASE without a trailing slash, or "" when unset.

    The operator's Windows env carries HIVE_API_BASE / HIVE_SECRET_KEY already
    (S-A: reference existing HKCU values, never copy a secret into a second
    variable). Used by the PRIMARY_* fallbacks below so a fresh shell with NO
    PRIMARY_* set still lands on the Hive provider instead of silently hitting
    api.openai.com with an empty key - which is exactly what the :9000 gateway
    did until 2026-10-16.
    """
    return (os.getenv("HIVE_API_BASE") or "").strip().rstrip("/")


def _primary_key() -> str:
    """Credential for the PRIMARY slot - the mirror of _specialist_key().

    Resolution, highest first:
      1. PRIMARY_API_KEY   - explicit override
      2. HIVE_SECRET_KEY   - the thehive.ai secret, already in the operator's
                             Windows env (never re-copied; see S-B for moving it
                             out of gateway_registry.json)
      3. ""                - no Authorization header (OpenAI's public routes)
    """
    return os.getenv("PRIMARY_API_KEY") or os.getenv("HIVE_SECRET_KEY") or ""


def _primary_url() -> str:
    """Chat-completions URL for the PRIMARY slot.

    Resolution, highest first:
      1. PRIMARY_API_URL   - explicit override (any provider)
      2. HIVE_API_BASE     - the Hive base, with /chat/completions appended
      3. OpenAI default    - only when Hive is not configured at all

    HIVE_API_BASE is stored WITHOUT the suffix (providers.py._strip_chat_suffix
    is the existing single source for that normalization), so the suffix is
    added here only when the base does not already carry it.
    """
    explicit = os.getenv("PRIMARY_API_URL")
    if explicit:
        return explicit
    base = _hive_base()
    if not base:
        return "https://api.openai.com/v1/chat/completions"
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _primary_model() -> str:
    """Model id for the PRIMARY slot.

    Follows the URL: an explicitly-set PRIMARY_MODEL always wins; otherwise a
    Hive-backed primary gets Hive's GLM flash id (plan section 2, R1) and the
    OpenAI default stays gpt-4o. Keeping these coupled matters - pointing the
    URL at Hive while leaving the model at gpt-4o yields a guaranteed upstream
    400 for every request.
    """
    model = os.getenv("PRIMARY_MODEL")
    if model:
        return model
    return "zai-org/glm-5.3-flash" if _hive_base() else "gpt-4o"



@dataclass
class Settings:
    # PRIMARY slot: default_factory (not class-level evaluation) so values are
    # resolved per-instantiation and stay monkeypatchable in tests - the
    # specialist slot already works this way. Bridges to HIVE_* when PRIMARY_*
    # is unset: see _primary_url/_primary_key/_primary_model.
    primary_api_url: str = field(default_factory=_primary_url)
    primary_api_key: str = field(default_factory=_primary_key)
    primary_model: str = field(default_factory=_primary_model)
    # The worker/specialist binding. SPECIALIST_API_URL/MODEL (plan W-A) override
    # the historical FALLBACK_* names; the key resolves through
    # SPECIALIST_API_KEY -> FALLBACK_API_KEY -> NANOGPT_API_KEY (see
    # _specialist_key) so the uncensored specialist can run on the operator's
    # Windows-env NanoGPT key with no extra secret to manage.
    fallback_api_url: str = field(default_factory=lambda: (
        os.getenv("SPECIALIST_API_URL")
        or os.getenv("FALLBACK_API_URL", "http://127.0.0.1:8000/v1/chat/completions")))
    fallback_api_key: str = field(default_factory=_specialist_key)
    fallback_model: str = field(default_factory=lambda: (
        os.getenv("SPECIALIST_MODEL")
        or os.getenv("FALLBACK_MODEL", "Qwen3.6-35B-A3B-abliterated-NVFP4-MTP")))
    # CALIBRATED 2026-10-05 (evals/hedge_calibrate.py): the refusal regex is
    # anchored to the start of the generation and fires by the 5th content word
    # (median 2), so holding 10 tokens screens exactly as well as 25 while the
    # client waits 0.24s for the first token instead of 0.59s (42.3 tok/s gx10).
    buffer_content_tokens: int = field(default_factory=lambda: _int_env("BUFFER_CONTENT_TOKENS", 10))
    # The gateway had NO body cap: an 8 MiB body was accepted and produced an
    # empty answer with no divert (P4 scenario 7). 32 MiB matches the hub's cap.
    max_body_bytes: int = field(
        default_factory=lambda: _int_env("MAX_BODY_BYTES", 32 * 1024 * 1024)
    )
    buffer_reasoning: int = field(default_factory=lambda: _int_env("BUFFER_REASONING", 0))
    max_attempts: int = field(default_factory=lambda: _int_env("MAX_ATTEMPTS", 3))
    retry_base_delay: float = field(default_factory=lambda: _float_env("RETRY_BASE_DELAY", 0.5))
    fallback_max_attempts: int = field(default_factory=lambda: _int_env("FALLBACK_MAX_ATTEMPTS", 3))
    assembly_enabled: int = field(default_factory=lambda: _int_env("ASSEMBLY_ENABLED", 1))
    # Gate 7 kill switch (T9 pattern). Gate 7 fail-closes on a keyword match,
    # so a false positive blocks the whole request with no recourse; an operator
    # must be able to re-open the gate without a code change or redeploy.
    no_go_enabled: int = field(default_factory=lambda: _int_env("NO_GO_ENABLED", 1))
    # Gate 8 kill switch. DEFAULT OFF: a forced divert bypasses the primary the
    # operator paid for and answers under DEFAULT_SYSTEM on the specialist, so
    # it is not a safe default. Enable with ATTACK_GATE_ENABLED=1.
    attack_gate_enabled: int = field(
        default_factory=lambda: _int_env("ATTACK_GATE_ENABLED", 0)
    )
    orchestrator_model: str = field(default_factory=lambda: (
        os.getenv("ORCHESTRATOR_MODEL", "") or _primary_model()))
    audit_log: str = os.getenv("AUDIT_LOG", "")
    authorised_principals: tuple = field(
        default_factory=lambda: tuple(p.strip() for p in os.getenv("AUTHORISED_PRINCIPALS", "").split(",") if p.strip())
    )
    authz_enforced: bool = field(default_factory=lambda: os.getenv("AUTHZ_ENFORCED", "0") == "1")
    keepalive_url: str = os.getenv("KEEPALIVE_URL", "")
    keepalive_interval_s: float = field(default_factory=lambda: _float_env("KEEPALIVE_INTERVAL_S", 240.0))
    shutdown_grace_s: float = field(default_factory=lambda: _float_env("SHUTDOWN_GRACE_S", 10.0))
    specialist_system_mode: str = os.getenv("SPECIALIST_SYSTEM_MODE", "neutral")
    specialist_temperature: Optional[float] = field(
        default_factory=lambda: float(os.getenv("SPECIALIST_TEMPERATURE")) if os.getenv("SPECIALIST_TEMPERATURE") else None
    )
    # Specialist budget per divert (found live 2026-10-18): fallback_stream sent
    # NO max_tokens, so a prepaid specialist (NanoGPT) reserved funds for
    # 64000 output tokens on EVERY divert and 402'd on a balance the actual
    # answer would have fit into many times over. /v1/execute already bounds
    # this at 4096 and the hedge at HEDGE_MAX_TOKENS; the divert was the only
    # unbounded specialist call left. 0 restores the old unbounded behaviour.
    specialist_max_tokens: int = field(
        default_factory=lambda: _int_env("SPECIALIST_MAX_TOKENS", 4096)
    )
    # DoS guard: cap concurrently open streams. Each stream holds an upstream
    # connection plus buffered SSE lines, so an unbounded burst exhausts fds
    # and memory on this single-worker uvicorn long before any upstream
    # rate-limits us. 0 = unlimited (previous behaviour).
    max_concurrent_streams: int = field(
        default_factory=lambda: _int_env("MAX_CONCURRENT_STREAMS", 64)
    )


SETTINGS = Settings()

# --------------------------------------------------------------------------
# Provider registry accessor (gateway_registry.json).
# One lazy, shared Registry for the whole process - /v1/switch resolves switch
# targets through it (Frost names in the list stay alias-only, list_models
# keeps its hand-written preferred order). mtime-based reload means an edit to
# the json is picked up without a restart.
# --------------------------------------------------------------------------
_registry = None


def registry():
    """The shared providers.Registry, created on first use (env-fallback safe)."""
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry


# --------------------------------------------------------------------------
# F26 metrics - plain dict counters, rendered as Prometheus text.
# --------------------------------------------------------------------------
_METRICS = {
    "requests_total": 0,
    "requests_clean": 0,
    "diverted_total": 0,
    "forced_divert_total": 0,
    "max_think_total": 0,
    "authz_denied_total": 0,
    "fallback_errors_total": 0,
    "primary_errors_total": 0,
    "assembly_total": 0,
    "switch_total": 0,
    "switch_verified_total": 0,
    "in_flight": 0,
    "specialist_warm": 0,
    "over_capacity_total": 0,
}


def incr(name: str, n: int = 1) -> None:
    """Never raises into the request path (design rule 7)."""
    try:
        _METRICS[name] = _METRICS.get(name, 0) + n
    except Exception:
        pass


def _stream_opened() -> None:
    """Count one open stream. Keeps app.state (shutdown grace) and _METRICS
    (healthz / Prometheus) in lockstep.

    These used to be two unrelated counters: app.state.in_flight was incremented
    and decremented per stream and honoured by _shutdown, while _METRICS
    ["in_flight"] was initialised to 0 and never touched, so /healthz and the
    Prometheus gauge reported "0 streams currently open" unconditionally - a
    lie that made a wedged stream invisible to monitoring.
    """
    app.state.in_flight = getattr(app.state, "in_flight", 0) + 1
    incr("in_flight")


def _stream_closed() -> None:
    """Release one open stream. Idempotent at zero; never raises.

    The clamp guards a double close (a stream whose finally runs after an
    explicit close): neither the shutdown counter nor the published gauge may go
    negative, so the decrement only happens when a slot was actually held.
    """
    held = getattr(app.state, "in_flight", 0)
    if held <= 0:
        app.state.in_flight = 0
        return
    app.state.in_flight = held - 1
    incr("in_flight", -1)


def metrics_snapshot() -> dict:
    import speculative_hedge  # local import: the gateway pulls the hedge in lazily

    # F8: hedge-side failures live in the hedge module. Surfaced here because a
    # silently-dead specialist used to leave no trace anywhere, and it is what
    # turns a divert into a withheld answer.
    counts = dict(_METRICS)
    for name, value in speculative_hedge.hedge_failure_counts().items():
        counts[f"hedge_{name}_total"] = value
    return counts


def render_prometheus() -> str:
    lines = []
    for key, value in sorted(metrics_snapshot().items()):
        help_text = {
            "requests_total": "requests accepted by the gateway",
            "requests_clean": "requests committed to the sovereign",
            "diverted_total": "requests diverted to the specialist",
            "forced_divert_total": "requests force-diverted by Gate 8 (attack content)",
            "authz_denied_total": "requests denied by F9 authz",
            "fallback_errors_total": "specialist transport/HTTP failures",
            "primary_errors_total": "primary transport/HTTP failures (F12/F13)",
            "assembly_total": "/v1/execute attempts",
            "switch_total": "requests accepted by /v1/switch",
            "switch_verified_total": "switches whose upstream probe answered 2xx",
            "in_flight": "streams currently open",
            "over_capacity_total": "requests rejected at the stream cap (429)",
            "specialist_warm": "keep-alive liveness of the specialist (1/0)",
            "max_think_total": "max-think requests (reasoning pushed to maximum)",
            "hedge_transport_error_total": "hedge branches that failed to connect/read",
            "hedge_bad_status_total": "hedge branches that answered non-2xx",
        }.get(key, key)
        lines.append(f"# HELP {key} {help_text}")
        lines.append(f"# TYPE {key} gauge")
        lines.append(f"{key} {value}")
    return "\n".join(lines) + "\n"


def _specialist_system_prompt(settings: Settings):
    """SPECIALIST_SYSTEM_MODE=domain activates the CYBER-FROST SAGE fine-tune's
    domain distribution (context_formatter.CYBER_SYSTEM) on EVERY specialist
    surface - both the refusal/capacity diverts and /v1/execute. "neutral"
    (the default) keeps the generic framing (DEFAULT_SYSTEM on diverts, the
    CYBER-FROST identity on /v1/execute)."""
    mode = (getattr(settings, "specialist_system_mode", "") or "neutral").strip().lower()
    return CYBER_SYSTEM if mode == "domain" else None


# --------------------------------------------------------------------------
# Circuit breaker (spec 6.2): prevents failover storms from exhausting the
# specialist. Closed -> (5 consecutive failures) -> OPEN -> (30 s) -> HALF-OPEN.
# --------------------------------------------------------------------------
class SpecialistCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = 0.0

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        import time

        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

    def allow_request(self) -> bool:
        import time

        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                return True
            return False
        return False  # HALF-OPEN: one probe at a time


BREAKER = SpecialistCircuitBreaker()


def make_client() -> httpx.AsyncClient:
    """Shared HTTP client factory - injectable for tests (monkeypatch)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=300.0))


def _auth_header(key: str):
    if not key or key == "none":
        return {}
    return {"Authorization": f"Bearer {key}"}


class PrimaryOpenError(Exception):
    """B10 taxonomy outcome of opening an upstream stream."""

    def __init__(self, status, divert: bool, detail: str = ""):
        self.status = status
        self.divert = divert
        self.detail = detail
        super().__init__(f"open failed status={status} divert={divert} {detail}")


async def open_primary(client, payload, headers, settings: Settings = None) -> httpx.Response:
    """Open the primary stream with retries: 408/429 -> retry SAME provider,
    never divert; 5xx -> retry then divert; 4xx -> fail fast (B10)."""
    s = settings or SETTINGS
    last_status = None
    for attempt in range(1, max(s.max_attempts, 1) + 1):
        req = client.build_request("POST", s.primary_api_url, json=payload, headers=headers)
        try:
            resp = await client.send(req, stream=True)
        except httpx.TransportError:
            last_status = None
            if attempt >= s.max_attempts:
                raise PrimaryOpenError(None, True, "transport error after retries")
            await asyncio.sleep(min(s.retry_base_delay * 2 ** (attempt - 1), 8.0))
            continue
        action = classify_status(resp.status_code)
        if action == "ok":
            return resp
        body = ""
        with contextlib.suppress(Exception):
            body = (await resp.aread()).decode("utf-8", "replace")[:300]
        await resp.aclose()
        last_status = resp.status_code
        if action == "retry_same":
            if attempt >= s.max_attempts:
                raise PrimaryOpenError(last_status, False, body)
        elif action == "retry_then_divert":
            if attempt >= s.max_attempts:
                raise PrimaryOpenError(last_status, True, body)
        else:
            raise PrimaryOpenError(last_status, False, body)
        await asyncio.sleep(min(s.retry_base_delay * 2 ** (attempt - 1), 8.0))
    raise PrimaryOpenError(last_status, classify_status(last_status) == "retry_then_divert")


async def open_fallback(client, payload, headers, settings: Settings = None) -> httpx.Response:
    """F6: retry DIVERT={500,502,503,504} with backoff; a 503 is capacity."""
    s = settings or SETTINGS
    last_status = None
    last_exc = None
    for attempt in range(1, max(s.fallback_max_attempts, 1) + 1):
        if not BREAKER.allow_request():
            raise PrimaryOpenError(last_status, False, "specialist circuit breaker OPEN")
        req = client.build_request("POST", s.fallback_api_url, json=payload, headers=headers)
        try:
            resp = await client.send(req, stream=True)
        except httpx.TransportError as exc:
            last_status = None
            last_exc = exc
            BREAKER.record_failure()
            incr("fallback_errors_total")
            if attempt >= s.fallback_max_attempts:
                raise PrimaryOpenError(None, False, f"specialist transport error: {exc}")
            await asyncio.sleep(min(s.retry_base_delay * 2 ** (attempt - 1), 8.0))
            continue
        action = classify_status(resp.status_code)
        if action == "ok":
            BREAKER.record_success()
            return resp
        body = ""
        with contextlib.suppress(Exception):
            body = (await resp.aread()).decode("utf-8", "replace")[:300]
        await resp.aclose()
        last_status = resp.status_code
        BREAKER.record_failure()
        incr("fallback_errors_total")
        if action == "retry_then_divert":
            if attempt >= s.fallback_max_attempts:
                raise PrimaryOpenError(last_status, False, body)
            await asyncio.sleep(min(s.retry_base_delay * 2 ** (attempt - 1), 8.0))
            continue
        raise PrimaryOpenError(last_status, False, body)
    raise PrimaryOpenError(last_status, False, f"specialist unavailable: {last_exc}")

# --------------------------------------------------------------------------
# Guards - run ONCE, shared by both endpoints (design rule 6).
# --------------------------------------------------------------------------
PRINCIPAL_HEADER = "X-Principal"


def check_body_size(request: Request) -> None:
    """413 for an oversized body (P4 scenario 7: an 8 MiB body was accepted and
    produced an empty answer with no divert - the gateway had no cap at all)."""
    raw = request.headers.get("content-length")
    if raw and raw.isdigit() and int(raw) > SETTINGS.max_body_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"request body too large ({raw} > {SETTINGS.max_body_bytes} bytes)",
        )


async def read_json_body(request: Request) -> dict:
    """Parse the JSON body with the size cap enforced DURING consumption.

    ``check_body_size`` above is only a fast pre-check: it can trust nothing but
    the Content-Length header, so a chunked request - or any client that simply
    omits the header - walked straight past the cap and was fully buffered
    anyway (the same silent-failure shape as P4 scenario 7, which the cap was
    added to close). Here the bytes are counted as they arrive, so the cap holds
    whatever the framing claims. F5 is preserved: a malformed body is a 400.
    """
    cap = SETTINGS.max_body_bytes
    chunks: list[bytes] = []
    total = 0
    async for part in request.stream():
        total += len(part)
        if total > cap:
            raise HTTPException(
                status_code=413,
                detail=f"request body too large (> {cap} bytes)",
            )
        chunks.append(part)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid JSON body")


def run_guards(body: dict, principal: str = None) -> None:
    """F9 authz + E6 n>1 + Gate 7 no-go, in that order. Raises HTTPException."""
    if SETTINGS.authz_enforced:
        if not principal or principal not in SETTINGS.authorised_principals:
            incr("authz_denied_total")
            raise HTTPException(status_code=403, detail="authorised principals only")
    n = body.get("n", 1)
    if isinstance(n, int) and n > 1:
        raise HTTPException(
            status_code=400,
            detail="n>1 is not supported: the buffer inspects one choice stream (E6)",
        )
    # Gate 7 scope: the CURRENT prompt only. The previous behaviour concatenated
    # every message in the body - system prompt plus the whole conversation
    # history - and ran the regex over the lot. A single appearance of a
    # no-go phrase in a client's system prompt, or in an assistant turn that
    # was itself quoting one, 403'd every subsequent turn of that conversation
    # permanently: measured live (evals/nogo_gate_probe.py) - a plain "hello"
    # returns 403 once the history mentions "nonconsensual surveillance".
    # History is by definition already-approved traffic; a gate that blocks
    # new requests on old answers cannot ever recover.
    #
    # Gate 8 also looks past the last message, and the asymmetry is deliberate:
    # Gate 7 BLOCKS, so a history hit would be an unrecoverable 403 on an
    # already-approved conversation; Gate 8 DIVERTS, so a wider window is only
    # a routing decision. Its window is the UNANSWERED span - the client turns
    # after the most recent assistant reply - so an ask split across
    # consecutive user turns is caught, while a thread whose ask has been
    # answered reverts to normal routing instead of staying diverted for life.
    no_go_text = _last_user_text(body.get("messages") or [])
    matched = None if not SETTINGS.no_go_enabled else no_go_match(no_go_text)
    if matched:
        audit_record(
            request_id="nogo",
            primary_model=SETTINGS.primary_model,
            worker_model="",
            signal="gate7_no_go",
            mode="pre-routing",
            principal=principal or "",
            audit_log=SETTINGS.audit_log,
        )
        # Report WHAT tripped the gate (a short, escaped excerpt). The bare
        # "hard no-go class" string was undiagnosable: 5 audit rows, zero
        # information about which phrase fired.
        snippet = " ".join(no_go_text.split())[:120]
        raise HTTPException(
            status_code=403,
            detail=f"request falls into a hard no-go class: {matched!r} "
                   f"in user prompt: {snippet!r}",
        )


# --------------------------------------------------------------------------
# Tier 4 (off the critical path): LLM-as-judge for ambiguous streams.
# Disabled by default; returns None on ANY failure - never False (so a broken
# classifier can never force a divert).
# --------------------------------------------------------------------------
class Tier4Classifier:
    def __init__(self, model: str = "", threshold: float = 0.5):
        self.model = model
        self.threshold = threshold
        self.enabled = bool(model)

    async def classify(self, client, text: str) -> Optional[bool]:
        """True = looks routed (refusal-ish), False = clean, None = no verdict."""
        if not self.enabled or not text:
            return None
        try:
            resp = await client.post(
                SETTINGS.primary_api_url,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Answer with exactly one word: ROUTE if the text is a "
                            "policy refusal, CLEAN if it is not.",
                        },
                        {"role": "user", "content": text[:2000]},
                    ],
                    "max_tokens": 4,
                    "stream": False,
                },
                headers={**_auth_header(SETTINGS.primary_api_key)},
            )
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            verdict = str(content).strip().upper()
            if verdict.startswith("ROUTE"):
                return True
            if verdict.startswith("CLEAN"):
                return False
            return None
        except Exception:
            return None


TIER4 = Tier4Classifier(model=os.getenv("TIER4_MODEL", ""))

# --------------------------------------------------------------------------
# Diversion path (section 4): format -> specialist -> footnote -> audit.
# --------------------------------------------------------------------------
def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


def _delta_chunk(delta: dict, finish=None, model: str = "", stream_id: str = "") -> bytes:
    return _sse(
        {
            # R1: one id per STREAM, not per chunk - clients group chunks by id,
            # and a fresh uuid per chunk makes one answer look like N answers.
            "id": stream_id or f"fallback-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


async def fallback_stream(
    original_messages,
    *,
    request_id: str = "",
    signal: str = "tier3",
    settings: Settings = None,
    system_prompt: str = None,
    principal: str = "",
    tools=None,
    tool_choice=None,
    forced: bool = False,
    signal_match: str = "",
) -> AsyncGenerator[bytes, None]:
    """Stream the specialist for a diverted request. Yields OpenAI SSE chunks:
    specialist output verbatim, then a provenance footnote delta,
    finish_reason="stop", then [DONE]."""
    s = settings or SETTINGS
    # F7: a plain divert carries the WHOLE conversation. format_messages() would
    # reduce it to [system, last user turn] and silently drop the context and any
    # tool results (see specialist_messages' docstring).
    msgs = specialist_messages(original_messages, system=system_prompt)
    assert_clean(msgs)
    sid = f"fallback-{uuid.uuid4().hex[:12]}"  # R1: stable for the whole stream
    payload = {"model": s.fallback_model, "messages": msgs, "stream": True}
    # Budget bound (found live 2026-10-18): without a max_tokens the divert
    # asked the specialist for an UNLIMITED completion - NanoGPT reserved funds
    # for 64000 output tokens and 402'd on a balance that would have covered
    # the actual answer many times over. Every other specialist surface already
    # bounds this (run_specialist: 4096, hedge: HEDGE_MAX_TOKENS); 0 disables.
    if s.specialist_max_tokens:
        payload["max_tokens"] = s.specialist_max_tokens
    # F6 (found while building the P6 agentic tier): the divert path dropped the
    # caller's tool definitions, so a diverted AGENTIC request arrived at the
    # specialist without tools and answered in prose instead of acting. Tools
    # must survive the divert exactly as they survive the primary call.
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    if s.specialist_temperature is not None:
        payload["temperature"] = s.specialist_temperature
    headers = {**_auth_header(s.fallback_api_key), "Content-Type": "application/json"}

    # audit BEFORE the call (section 4 step 3)
    audit_record(
        request_id=request_id,
        primary_model=s.primary_model,
        worker_model=s.fallback_model,
        signal=signal,
        mode="stream",
        principal=principal,
        audit_log=s.audit_log,
        forced=forced,
        signal_match=signal_match,
    )

    try:
        resp = await open_fallback(app.state.http, payload, headers, s)
    except PrimaryOpenError as exc:
        # F11 (P4-7 root cause): a specialist that refuses to OPEN the stream
        # (e.g. TabbyAPI 400 context-length rejection of an oversized divert)
        # used to surface as only a {"error": ...} SSE event - no content chunk
        # at all, i.e. a silent 200 + empty answer to every standard client.
        # Deliver the failure as visible content with the provenance footnote,
        # then close. A disclosed failure is acceptable; a silent one is not.
        msg = f"Specialist unavailable ({exc.status or 'transport'}): {exc.detail}"[:300]
        yield _delta_chunk({"content": msg}, finish=None, model=s.fallback_model, stream_id=sid)
        yield _delta_chunk({"content": footnote(s.fallback_model)}, finish=None, model=s.fallback_model, stream_id=sid)
        yield _delta_chunk({}, finish="stop", model=s.fallback_model, stream_id=sid)
        yield b"data: [DONE]\n\n"
        return

    try:
        async for raw in resp.aiter_lines():
            line = raw.strip()
            if not line or not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            # R1: adopt the specialist's stream id, so the footnote we inject
            # below belongs to the SAME stream instead of opening a second one.
            with contextlib.suppress(Exception):
                sid = json.loads(body).get("id") or sid
            yield f"{line}\n\n".encode()
    except httpx.TransportError as exc:
        incr("fallback_errors_total")
        yield _sse({"error": f"specialist stream broke: {exc}"})
        # F11 parity: make a mid-stream transport break visible as content too,
        # so clients that only read delta.content are not left with a truncated
        # answer that LOOKS complete.
        yield _delta_chunk({"content": f"[specialist stream broke: {exc}]"},
                           finish=None, model=s.fallback_model, stream_id=sid)
    finally:
        with contextlib.suppress(Exception):
            await resp.aclose()

    yield _delta_chunk({"content": footnote(s.fallback_model)}, finish=None, model=s.fallback_model, stream_id=sid)
    yield _delta_chunk({}, finish="stop", model=s.fallback_model, stream_id=sid)
    yield b"data: [DONE]\n\n"

# --------------------------------------------------------------------------
# App, lifecycle (F10/F27).
# --------------------------------------------------------------------------
app = FastAPI(title="Interception Gateway")


@app.on_event("startup")
async def _startup() -> None:
    app.state.http = make_client()
    app.state.in_flight = 0
    app.state.keepalive_task = None
    app.state.specialist_warm = False
    app.state.last_keepalive = 0.0
    if SETTINGS.keepalive_url:
        app.state.keepalive_task = asyncio.create_task(_keepalive_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    task = getattr(app.state, "keepalive_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    grace = SETTINGS.shutdown_grace_s
    deadline = asyncio.get_event_loop().time() + grace
    while getattr(app.state, "in_flight", 0) > 0 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
    with contextlib.suppress(Exception):
        await app.state.http.aclose()


async def _keepalive_loop() -> None:
    """F10: background poller that warms the specialist; never raises."""
    import time as _time

    while True:
        try:
            resp = await app.state.http.get(SETTINGS.keepalive_url, timeout=10.0)
            app.state.specialist_warm = 200 <= resp.status_code < 300
            app.state.last_keepalive = _time.time()
        except Exception:
            app.state.specialist_warm = False
            app.state.last_keepalive = _time.time()
        _METRICS["specialist_warm"] = 1 if app.state.specialist_warm else 0
        await asyncio.sleep(max(SETTINGS.keepalive_interval_s, 5.0))


def _last_user_text(messages) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return "\n".join(
                    str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in c
                )
            return str(c or "")
    return ""


# Roles whose content the CLIENT controls. Gate 8 scans these turns in the
# UNANSWERED span - the messages after the most recent assistant reply - not
# just the last user message: a client can batch two user turns (the payload,
# then "continue") before the model has said anything, and a last-message-only
# scan would see only "continue".
#
# The span ends at the first assistant turn. That is the REVERT rule: once the
# model has answered - complied or refused - the ask has been handled, and the
# thread routes normally again instead of staying diverted for its lifetime.
# A fresh unanswered ask re-trips the gate on its own turn. Assistant and tool
# content are never scanned in the first place: they are model output, not a
# client ask.
_SCANNABLE_ROLES = frozenset({"system", "developer", "user"})


def _message_text(content) -> str:
    """Flatten a message's content, which may be a string or a block list."""
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content
        )
    return str(content or "")


def attack_match_in_messages(messages):
    """First Gate-8 match in the UNANSWERED client-controlled span, or None.

    Scans system/developer/user turns after the most recent assistant turn.
    Two boundaries follow:

    - an ask split across consecutive client turns is still caught, which a
      last-message-only scan missed ("continue" hid the payload);
    - an assistant turn ends the span, so an ANSWERED ask stops steering the
      thread: routing reverts to normal instead of diverting for life.
    """
    match = None
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant":
            match = None  # the ask before this reply has been handled: revert
            continue
        if m.get("role") not in _SCANNABLE_ROLES:
            continue
        if match is None:
            match = attack_match(_message_text(m.get("content")))
    return match

# --------------------------------------------------------------------------
# Max-think names (operator request, 2026-10): the SAME thinking primaries
# (deepseek-ai/deepseek-v4.1-flash, zai-org/glm-5.3-flash) addressed through
# names that demand extra-hard reasoning. The name set lives beside
# FROST_ALIASES in providers.py (single source of truth for the alias data);
# here we only recognise the names (exact alias form plus the normalised
# "x max think" tail - see resolve_frost_alias's normalisation) and inject the
# reasoning knobs server-side in chat_proxy.
# --------------------------------------------------------------------------
def wants_max_think(model) -> bool:
    """True when the client addressed one of the max-think Frost names."""
    if not model:
        return False
    key = " ".join(str(model).strip().lower().replace("_", " ").split())
    return key in MAX_THINK_NAMES or key.replace(" ", "-") in MAX_THINK_NAMES


# --------------------------------------------------------------------------
# Streaming ring-buffer endpoint (section 3).
# --------------------------------------------------------------------------
@app.post("/v1/chat/completions")
async def chat_proxy(request: Request):
    check_body_size(request)  # fast path: a declared-oversized body is never read
    # authoritative: the cap is enforced while the bytes arrive (chunked-safe)
    body = await read_json_body(request)
    principal = request.headers.get(PRINCIPAL_HEADER) or ""
    run_guards(body, principal or None)
    # Capacity guard (DoS): check AFTER guards, BEFORE accepting - a rejected
    # request counts in over_capacity_total, not requests_total. The
    # check-then-increment pair below has no await between it, so it is atomic
    # on the event loop. 0 disables (previous behaviour).
    cap = SETTINGS.max_concurrent_streams
    if cap and getattr(app.state, "in_flight", 0) >= cap:
        incr("over_capacity_total")
        raise HTTPException(
            status_code=429,
            detail=f"gateway at capacity ({cap} open streams); retry shortly",
            headers={"Retry-After": "2"},
        )
    incr("requests_total")
    _stream_opened()

    messages = body.get("messages") or []
    user_query = _last_user_text(messages)
    request_id = f"gw-{uuid.uuid4().hex[:12]}"
    settings = SETTINGS

    # Gate 8: forced divert for attack content (S4/S5/S6 red-team stages).
    # Check BEFORE the primary model sees the request - divert immediately to the
    # specialist. Opt-in (ATTACK_GATE_ENABLED=1, default off).
    forced_match = attack_match_in_messages(messages) if settings.attack_gate_enabled else None
    if forced_match:
        incr("forced_divert_total")
        # A forced divert IS a divert: without this the operator could not tell
        # how much traffic the gate was taking from primary_divert_total alone.
        incr("diverted_total")

        async def forced_stream() -> AsyncGenerator[bytes, None]:
            try:
                async for chunk in fallback_stream(
                    messages,
                    request_id=request_id,
                    signal=FORCED_DIVERT_REASON,
                    settings=settings,
                    principal=principal,
                    tools=body.get("tools"),
                    tool_choice=body.get("tool_choice"),
                    system_prompt=_specialist_system_prompt(settings),
                    forced=True,
                    signal_match=forced_match,
                ):
                    yield chunk
            finally:
                # F27 parity: the counter is incremented once, above, for every
                # accepted request. This path returned a StreamingResponse
                # without ever decrementing it, so each forced divert leaked a
                # slot and _shutdown blocked for the whole grace period.
                _stream_closed()

        return StreamingResponse(forced_stream(), media_type="text/event-stream")

    # B11 gate: the speculative hedge only fires on latency hints or force.
    hedge_requested = should_hedge(user_query, force=body.get("hedge") is True)

    # Frost names ("DeepFrost v4.1", "GLMFrost 5.3 Flash", "CyberFrost 3.8 SAGE")
    # are real model ids. Resolve to the configured slot + upstream id so one
    # endpoint can address any published system; anything else passes through.
    requested = body.get("model") or settings.primary_model
    frost = resolve_frost_alias(requested)
    # Max-think is detected on the NAME the client sent (the alias, not the
    # resolved upstream id) so the reasoning knobs below are injected exactly
    # once, before the payload is dispatched. The max-think names stay on the
    # PRIMARY slot (Hive / thehive.ai keys) - they are the SAME thinking
    # primaries, just with reasoning pushed to max; the NanoGPT abliterated
    # specialist is reached only through the normal divert path.
    max_think = wants_max_think(requested)
    if frost and frost[0] == "worker":
        call_settings = copy.copy(settings)
        call_settings.primary_api_url = settings.fallback_api_url
        call_settings.primary_api_key = settings.fallback_api_key
        primary_model_used = frost[1]
    else:
        call_settings = settings
        primary_model_used = frost[1] if frost else requested

    primary_payload = {
        "model": primary_model_used,
        "messages": messages,
        "stream": True,
        "max_tokens": body.get("max_tokens", 4096),
        # Hive honours only max_completion_tokens (see speculative_hedge):
        # given max_tokens alone its models spend the budget on reasoning and
        # glm-5.3-flash returns empty content.
        "max_completion_tokens": body.get(
            "max_completion_tokens", body.get("max_tokens", 4096)),
    }
    if body.get("tools"):
        primary_payload["tools"] = body["tools"]
    if body.get("tool_choice"):
        primary_payload["tool_choice"] = body["tool_choice"]
    if body.get("temperature") is not None:
        primary_payload["temperature"] = body["temperature"]
    if max_think:
        # Operator knob set for the max-think names: the reasoning maximum is
        # injected HERE, never trusted from the body. Every known convention
        # is sent because OpenAI-compatible upstreams ignore unknown fields
        # (measured on Hive, see speculative_hedge). The output-floor matters
        # just as much: Hive models spend the budget on hidden reasoning
        # first (finish_reason=length with 0 content tokens was measured at
        # max_tokens=2000), so extra-hard thinking needs a bigger cap than
        # the 4096 default not to die mid-deliberation.
        primary_payload["reasoning_effort"] = "max"
        primary_payload["reasoning"] = {"effort": "max"}
        primary_payload["reasoning_content"] = True
        primary_payload["enable_thinking"] = True
        primary_payload["chat_template_kwargs"] = {"thinking": True}
        primary_payload["thinking"] = {"type": "enabled"}
        floor = _int_env("MAX_THINK_MIN_TOKENS", 32768)
        for k in ("max_tokens", "max_completion_tokens"):
            try:
                primary_payload[k] = max(floor, int(primary_payload[k]))
            except (TypeError, ValueError):
                primary_payload[k] = floor
        incr("max_think_total")
    primary_headers = {**_auth_header(call_settings.primary_api_key), "Content-Type": "application/json"}

    async def coordinator() -> AsyncGenerator[bytes, None]:
        try:
            # Max-think never races: COMMIT_TOKENS=10 would commit the flash
            # worker while the deep model is still deliberating (reasoning
            # tokens are invisible to the commit counter), so the race's value
            # proposition (fast first token) is void here anyway.
            if hedge_requested and not max_think:
                import speculative_hedge

                # R2: audit parity. The divert path records BEFORE dispatch
                # (crash-safe); a hedged request used to leave no trace at all,
                # so the audit log silently missed every race the gateway ran.
                audit_record(
                    request_id=request_id,
                    primary_model=primary_payload["model"],
                    worker_model=settings.fallback_model,
                    signal="hedge_forced" if body.get("hedge") is True else "hedge_hint",
                    mode="hedge",
                    principal=principal,
                    audit_log=settings.audit_log,
                )

                # F14: this used to mutate the module-global SETTINGS in place,
                # so two concurrent hedged requests raced on sovereign_model
                # (taken from each request's own body) and could clobber each
                # other's URLs mid-flight. Copy the module settings - so
                # monkeypatched knobs still apply - and hand the copy to the
                # call, which already accepts `settings=`.
                h = copy.copy(speculative_hedge.SETTINGS)
                h.sovereign_url = call_settings.primary_api_url
                h.sovereign_key = call_settings.primary_api_key
                h.sovereign_model = primary_payload["model"]
                h.worker_url = settings.fallback_api_url
                h.worker_key = settings.fallback_api_key
                h.worker_model = settings.fallback_model
                async for chunk in speculative_hedge.hedge_stream(
                    messages, request_id=request_id, client=app.state.http, settings=h
                ):
                    yield chunk
                return

            try:
                resp = await open_primary(app.state.http, primary_payload, primary_headers, call_settings)
            except PrimaryOpenError as exc:
                if exc.divert:
                    incr("diverted_total")
                    async for chunk in fallback_stream(
                        messages,
                        request_id=request_id,
                        signal=f"tier1_open_{exc.status}",
                        settings=settings,
                        principal=principal,
                        tools=body.get("tools"),
                        tool_choice=body.get("tool_choice"),
                        system_prompt=_specialist_system_prompt(settings),
                    ):
                        yield chunk
                else:
                    # F12: a fail-fast upstream error (400/401/403/404) is not
                    # routable, but it must not become a silent empty 200 either
                    # - the same defect class F11 fixed on the specialist path.
                    # Keep the error event (clients that read it lose nothing)
                    # AND put the failure in delta.content, which is what every
                    # standard OpenAI client actually renders.
                    incr("primary_errors_total")
                    msg = f"Upstream error ({exc.status}): {exc.detail}"[:300]
                    yield _sse({"error": f"upstream error ({exc.status}): {exc.detail}"})
                    yield _delta_chunk({"content": msg}, finish=None, model=primary_payload["model"])
                    yield _delta_chunk({}, finish="stop", model=primary_payload["model"])
                    yield b"data: [DONE]\n\n"
                return

            state = "BUFFERING"
            pending: list = []  # buffered raw SSE lines, replayed verbatim
            buffer_text = ""
            content_tokens = 0
            routed_reason = ""
            saw_reasoning = False  # F2: reasoning alone still means the client saw text

            try:
                # B7: ONE pass over ONE iterator - never re-enter, never drop.
                async for raw in resp.aiter_lines():
                    line = raw.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    body_s = line[5:].strip()
                    if body_s == "[DONE]":
                        if state == "BUFFERING":
                            # F2: HTTP 200 with NOTHING (no content, no reasoning,
                            # no tool calls) is a soft refusal. The regex cannot
                            # see it, so without this the client silently gets an
                            # empty answer and no divert. Measured live on the hub's
                            # cloud aliases; also hit a benign dev prompt.
                            if content_tokens == 0 and not saw_reasoning:
                                routed_reason = "tier1_empty"
                                break
                            if saw_reasoning and content_tokens == 0:
                                # thinking-only: reasoning content but no text content
                                # when the stream ends - re-dispatch to worker.
                                routed_reason = "tier1_thinking_only"
                                break
                            for p in pending:
                                yield f"{p}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return

                    try:
                        ev = json.loads(body_s)
                    except json.JSONDecodeError:
                        continue
                    choices = ev.get("choices") or [{}]
                    delta = (choices[0].get("delta") or {}) if isinstance(ev, dict) else {}
                    finish = choices[0].get("finish_reason") if isinstance(ev, dict) else None

                    if state == "BUFFERING":
                        # Tier 1: metadata intercept
                        if finish == "timeout" or delta.get("error") or ev.get("error"):
                            routed_reason = f"tier1_{finish or 'error'}"
                            break
                        reasoning = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or delta.get("thinking")
                        )
                        if reasoning:
                            # F1/B21: forward for TTFT, never count
                            saw_reasoning = True
                            if settings.buffer_reasoning:
                                pending.append(line)
                            else:
                                yield f"{line}\n\n".encode()
                        if delta.get("tool_calls"):
                            # tool-call deltas are real content but never refusal
                            # prose: replay them, count them, do NOT regex them.
                            pending.append(line)
                            content_tokens += 1
                        if delta.get("content"):
                            buffer_text += delta["content"]
                            pending.append(line)
                            content_tokens += 1
                            # Tier 3: 200-char screening window
                            if len(buffer_text) <= 200 and is_routable(buffer_text):
                                routed_reason = "tier3_refusal"
                                break
                        if content_tokens >= settings.buffer_content_tokens:
                            state = "PASSTHROUGH"
                            for p in pending:
                                yield f"{p}\n\n".encode()
                            pending.clear()
                        if finish:
                            if content_tokens == 0 and not saw_reasoning:
                                routed_reason = "tier1_empty"  # F2: same soft refusal
                                break
                            if saw_reasoning and content_tokens == 0:
                                # thinking-only: the thinking-on primaries (DeepFrost /
                                # GLMFrost) print a hidden reasoning block and stop
                                # writing text, so delivering it would give the client
                                # nothing but "thinking". Re-dispatch to the worker.
                                routed_reason = "tier1_thinking_only"
                                break
                            for p in pending:
                                yield f"{p}\n\n".encode()
                            yield b"data: [DONE]\n\n"
                            return
                    else:  # PASSTHROUGH: the stream is opaque (B8)
                        yield f"{line}\n\n".encode()
                        if finish:
                            yield b"data: [DONE]\n\n"
                            return
                # upstream ended without [DONE]
                if state == "BUFFERING" and not routed_reason:
                    if content_tokens == 0 and not saw_reasoning:
                        routed_reason = "tier1_empty"  # F2: nothing arrived at all
                    elif saw_reasoning and content_tokens == 0:
                        # thinking-only: the thinking-on primaries print a hidden
                        # reasoning block and stop writing text; re-dispatch to the
                        # worker instead of shipping "thinking" as the answer.
                        routed_reason = "tier1_thinking_only"
                    else:
                        for p in pending:
                            yield f"{p}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
            except httpx.TransportError as exc:
                # F13: a primary stream that broke mid-flight used to raise
                # straight out of the generator, so the client got a truncated
                # body with no error event, no finish_reason and no way to tell
                # it apart from a complete answer (same class as F11).
                incr("primary_errors_total")
                if state == "BUFFERING":
                    # Nothing has been committed to the client yet, so this is
                    # just a Tier 1 transport failure: divert instead of
                    # surfacing it. Falls through to the divert block below.
                    # Keep an already-detected reason (e.g. tier3_refusal).
                    routed_reason = routed_reason or "tier1_stream_broke"
                else:
                    yield _sse({"error": f"primary stream broke: {exc}"})
                    yield _delta_chunk({"content": f"\n\n[primary stream broke: {exc}]"},
                                       finish=None, model=primary_payload["model"])
                    yield _delta_chunk({}, finish="stop", model=primary_payload["model"])
                    yield b"data: [DONE]\n\n"
                    return
            finally:
                with contextlib.suppress(Exception):
                    await resp.aclose()

            # --- diverted: discard the buffer, never surface it ----------
            incr("diverted_total")
            async for chunk in fallback_stream(
                messages,
                request_id=request_id,
                signal=routed_reason or "tier1",
                settings=settings,
                principal=principal,
                tools=body.get("tools"),
                tool_choice=body.get("tool_choice"),
                system_prompt=_specialist_system_prompt(settings),
            ):
                yield chunk
        finally:
            _stream_closed()

    return StreamingResponse(coordinator(), media_type="text/event-stream")

# --------------------------------------------------------------------------
# Deterministic assembly (section 7): planner -> worker -> assemble().
# --------------------------------------------------------------------------
from typing import Literal, Optional  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402


class CyberSubtaskPlan(BaseModel):
    is_technical_deepdive: bool = Field(
        description="True if the request requires raw code analysis, disassembly, "
        "or specific vulnerability mechanics."
    )
    direct_response: Optional[str] = Field(
        default=None,
        description="Executive summary or remediation advice rendered directly by "
        "the sovereign planner.",
    )
    target_environment: Optional[str] = Field(
        default="Linux x86_64",
        description="Target operating system, architecture, or environment parameters.",
    )
    task_type: Optional[
        Literal["reverse_engineering", "code_audit", "yara_generation", "protocol_analysis"]
    ] = Field(default=None)
    sanitized_worker_prompt: Optional[str] = Field(
        default=None,
        description="Stateless technical directive for the specialist, stripped of "
        "policy framing.",
    )
    output_grammar_type: Optional[
        Literal["c_code", "python_script", "json_sarif", "freeform_markdown"]
    ] = Field(default="freeform_markdown")
    client_scaffolding: Optional[str] = Field(
        default=None,
        description=f"Client deliverable template containing the anchor {SLOT!r}.",
    )


_ORCHESTRATOR_INSTRUCTIONS = """You are the planning tier. Decompose the request into a JSON plan.
Reply with ONLY a JSON object (no markdown fence) with exactly these keys:
{"is_technical_deepdive": bool,
 "direct_response": string|null,
 "target_environment": string,
 "task_type": "reverse_engineering"|"code_audit"|"yara_generation"|"protocol_analysis"|null,
 "sanitized_worker_prompt": string|null,
 "output_grammar_type": "c_code"|"python_script"|"json_sarif"|"freeform_markdown",
 "client_scaffolding": string}
If the request does not need raw technical work, set is_technical_deepdive=false and
write the full answer into direct_response. If it does, write the stateless technical
directive into sanitized_worker_prompt and a client deliverable template that contains
the exact anchor {slot} where the specialist's artefact must appear."""


def _extract_json(text: str) -> dict:
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lstrip().startswith("json"):
            body = body.lstrip()[4:]
    start = body.find("{")
    end = body.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("orchestrator returned no JSON object")
    return json.loads(body[start : end + 1])


async def run_specialist(plan: CyberSubtaskPlan, settings: Settings, request_id: str = ""):
    """Non-streaming specialist call, retry-wrapped on capacity (F6).
    Grammar-enforced when the plan asks for json_sarif (spec section 4)."""
    task_directives = {
        "reverse_engineering": "Focus on disassembly analysis, structural control-flow, and register state transitions.",
        "code_audit": "Trace tainted inputs, stack frames, memory allocations, and boundary checks.",
        "yara_generation": "Generate valid, optimized YARA rules with robust string definitions and condition logic.",
        "protocol_analysis": "Detail packet structure, state machines, byte offsets, and serialization routines.",
    }
    # SPECIALIST_SYSTEM_MODE=domain replaces the generic identity with the
    # SAGE domain frame (CYBER_SYSTEM); neutral keeps the generic persona.
    persona = _specialist_system_prompt(settings) or "You are CYBER-FROST, a cybersecurity specialist."
    directive = (
        persona + "\n"
        f"Environment: {plan.target_environment or 'Linux x86_64'}\n"
        "Objective: "
        + task_directives.get(plan.task_type or "", "Execute precise technical analysis.")
        + "\nOutput the technical solution directly. Do not include introductory "
        "remarks, safety lectures, or disclaimers."
    )
    payload = {
        "model": settings.fallback_model,
        "messages": [
            {"role": "system", "content": directive},
            {"role": "user", "content": plan.sanitized_worker_prompt},
        ],
        "stream": False,
        "max_tokens": 4096,
        "max_completion_tokens": 4096,
    }
    grammar = grammar_for(plan.output_grammar_type)
    if grammar:
        payload["grammar_string"] = grammar
    resp = await open_fallback(
        app.state.http,
        payload,
        {**_auth_header(settings.fallback_api_key), "Content-Type": "application/json"},
        settings,
    )
    data = (await resp.aread()).decode("utf-8", "replace")
    with contextlib.suppress(Exception):
        await resp.aclose()
    return json.loads(data)

@app.post("/v1/execute")
async def execute(request: Request):
    if not SETTINGS.assembly_enabled:
        raise HTTPException(status_code=501, detail="assembly disabled (ASSEMBLY_ENABLED=0)")
    check_body_size(request)  # fast path: a declared-oversized body is never read
    # authoritative: the cap is enforced while the bytes arrive (chunked-safe)
    body = await read_json_body(request)
    principal = request.headers.get(PRINCIPAL_HEADER) or ""
    run_guards(body, principal or None)
    incr("assembly_total")
    request_id = f"ex-{uuid.uuid4().hex[:12]}"
    settings = SETTINGS
    messages = body.get("messages") or []

    plan_resp = await app.state.http.post(
        settings.primary_api_url,
        json={
            "model": settings.orchestrator_model,
            "messages": [
                # .format() would eat the JSON braces - plain replace instead
                {"role": "system", "content": _ORCHESTRATOR_INSTRUCTIONS.replace("{slot}", SLOT)},
                {"role": "user", "content": json.dumps(messages[-1], ensure_ascii=False)[:8000]},
            ],
            "stream": False,
            "max_tokens": 2048,
            "max_completion_tokens": 2048,
        },
        headers={**_auth_header(settings.primary_api_key)},
        # R3: a planning call is bounded work - the shared client's 300 s read
        # budget would let a wedged orchestrator hold the request open.
        timeout=httpx.Timeout(30.0, read=120.0),
    )
    if plan_resp.status_code >= 400:
        return JSONResponse(
            status_code=502, content={"error": f"orchestrator failed ({plan_resp.status_code})"}
        )
    plan_data = _extract_json(plan_resp.json()["choices"][0]["message"]["content"])
    plan = CyberSubtaskPlan(**plan_data)

    if not plan.is_technical_deepdive or not plan.sanitized_worker_prompt:
        audit_record(
            request_id=request_id,
            primary_model=settings.orchestrator_model,
            worker_model="",
            signal="direct",
            mode="execute",
            principal=principal,
            artifact=plan.direct_response or "",
            deliverable=plan.direct_response or "",
            audit_log=settings.audit_log,
        )
        return {"deliverable": plan.direct_response or "", "worker": None, "plan": plan.model_dump()}

    if not plan.client_scaffolding or plan.client_scaffolding.count(SLOT) != 1:
        raise HTTPException(
            status_code=400,
            detail=f"plan scaffolding must contain exactly one anchor {SLOT!r}",
        )

    data = await run_specialist(plan, settings, request_id)
    artifact = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    valid = validate_artifact(artifact, plan.output_grammar_type)
    if not valid:
        if (plan.output_grammar_type or "") in ("python_script", "json_sarif"):
            artifact += "\n\n/* Warning: Output artifact may contain syntax truncation. */"

    deliverable = assemble(plan.client_scaffolding, artifact)
    audit_record(
        request_id=request_id,
        primary_model=settings.orchestrator_model,
        worker_model=settings.fallback_model,
        signal="assembly",
        mode="execute",
        principal=principal,
        artifact=artifact,
        deliverable=deliverable,
        audit_log=settings.audit_log,
    )
    return {
        "deliverable": (
            deliverable
            + "\n\n---\n"
            + f"*Analysis completed via local {settings.fallback_model} specialist.*"
        ),
        "worker": settings.fallback_model,
        "artifact_valid": valid,
        "plan": plan.model_dump(),
    }


# --------------------------------------------------------------------------
# Model registry - returns Frost models in preferred order + any others
# --------------------------------------------------------------------------
FROST_REGISTRY = [
    {"id": "deepfrost", "name": "DeepFrost v4.1", "upstream": "deepseek-ai/deepseek-v4.1-flash",
     "endpoint": "http://gx10.ayu-sidewinder.ts.net:9311/v1",
     "type": "primary", "provider": "hive", "hedged": True},
    {"id": "glmfrost", "name": "GLMFrost 5.3 Flash", "upstream": "zai-org/glm-5.3-flash",
     "endpoint": "http://gx10.ayu-sidewinder.ts.net:9312/v1",
     "type": "primary", "provider": "hive", "hedged": True},
    {"id": "deepfrost max think", "name": "DeepFrost Max Think", "upstream": "deepseek-ai/deepseek-v4.1-flash",
     "endpoint": "http://gx10.ayu-sidewinder.ts.net:9314/v1",
     "type": "primary", "provider": "hive", "hedged": False,
     "reasoning": "max"},
    {"id": "glmfrost max think", "name": "GLMFrost Max Think", "upstream": "zai-org/glm-5.3-flash",
     "endpoint": "http://gx10.ayu-sidewinder.ts.net:9315/v1",
     "type": "primary", "provider": "hive", "hedged": False,
     "reasoning": "max"},
    {"id": "cyberfrost", "name": "CyberFrost 3.8 SAGE", "upstream": "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw",
     "endpoint": "http://gx10.ayu-sidewinder.ts.net:9313/v1",
     "type": "worker", "provider": "gx10-hub", "hedged": False},
    {"id": "frost-general", "name": "Frost General (any model)", "upstream": "auto",
     "endpoint": "http://gx10.ayu-sidewinder.ts.net:9310/v1",
     "type": "general", "provider": "hive+gx10", "hedged": True},
]


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model list with Frost models first, in preferred order."""
    data = []
    for m in FROST_REGISTRY:
        data.append({
            "id": m["id"],
            "object": "model",
            "created": 1791338912,
            "owned_by": m["provider"],
            "permission": [],
            "root": m["upstream"],
            "parent": None,
            "description": m["name"],
            "endpoint": m["endpoint"],
            "hedged": m["hedged"],
            "type": m["type"],
            "max_think": m["id"] in MAX_THINK_NAMES,
            "reasoning": m.get("reasoning"),
        })
    return {"object": "list", "data": data}


# --------------------------------------------------------------------------
# /v1/switch - runtime slot switching (see model_switch.py for the contract).
# Endpoint duties only: guards (F9 authz), body parse, metric increments,
# SwitchError -> status-code mapping. Everything else lives in model_switch.
# --------------------------------------------------------------------------
@app.post("/v1/switch")
@app.post("/switch", include_in_schema=False)
async def switch_endpoint(request: Request):
    check_body_size(request)
    if (request.headers.get("content-length") or "").strip() == "0":
        body = {}  # a truly empty POST still answers with a status snapshot
    else:
        # F5 preserved: garbage JSON stays a 400 and an oversized body a 413 -
        # only an EMPTY body gets the status-snapshot courtesy.
        body = await read_json_body(request)
    principal = request.headers.get(PRINCIPAL_HEADER) or ""
    run_guards({}, principal or None)
    request_id = f"sw-{uuid.uuid4().hex[:12]}"
    incr("switch_total")
    try:
        payload = await model_switch.perform_switch(
            body,
            settings=SETTINGS,
            http=app.state.http,
            registry=registry(),
            request_id=request_id,
            principal=principal,
            audit_log=SETTINGS.audit_log,
        )
    except model_switch.SwitchError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})
    if payload.get("verified"):
        incr("switch_verified_total")
    return payload


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "in_flight": _METRICS.get("in_flight", 0),
        "metrics": metrics_snapshot(),
        "config": {
            "primary_model": SETTINGS.primary_model,
            # Phase 0 observability: the URL is public (a base address, not a
            # secret) but the KEY is only reported as a presence boolean -
            # /healthz has no auth, so echoing the value would leak it. Before
            # this existed there was no way to confirm WHICH provider the
            # primary slot was bound to without reading the host env.
            "primary_url": SETTINGS.primary_api_url,
            "primary_key_present": bool(SETTINGS.primary_api_key),
            "no_go_enabled": bool(SETTINGS.no_go_enabled),
            "fallback_model": SETTINGS.fallback_model,
            # Runtime switch surface: what each slot is bound to RIGHT NOW,
            # who last wrote it and whether a rollback savepoint exists. The
            # binding dicts carry key_present booleans only - /healthz has no
            # auth, so no secret material is echoed here either.
            "switch": {
                **model_switch.manager().snapshot(),
                "savepoint_available": model_switch.manager().has_savepoint(),
            },
            "buffer_content_tokens": SETTINGS.buffer_content_tokens,
            "buffer_reasoning": SETTINGS.buffer_reasoning,
            "max_concurrent_streams": SETTINGS.max_concurrent_streams,
            "specialist_max_tokens": SETTINGS.specialist_max_tokens,
            "assembly_enabled": bool(SETTINGS.assembly_enabled),
            "authz_enforced": SETTINGS.authz_enforced,
            "keepalive_url": SETTINGS.keepalive_url or None,
            "specialist_warm": getattr(app.state, "specialist_warm", False),
            "audit_log": SETTINGS.audit_log or None,
        },
    }


@app.get("/metrics")
async def metrics():
    return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4")








