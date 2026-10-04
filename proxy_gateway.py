"""FastAPI interception gateway: buffering, routing, metrics, endpoints.

Endpoints
    POST /v1/chat/completions   streaming ring-buffer proxy (drop-in OpenAI)
    POST /v1/execute            planner -> worker -> assemble() (Part IV)
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
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from context_formatter import CYBER_SYSTEM, DEFAULT_SYSTEM, assert_clean, format_messages
from ingress_assembler import (
    SLOT,
    assemble,
    audit_record,
    grammar_for,
    validate_artifact,
)
from routing_patterns import (
    DIVERT_STATUS,
    FOOTNOTE_TEMPLATE,
    classify_status,
    footnote,
    is_no_go,
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


@dataclass
class Settings:
    primary_api_url: str = os.getenv("PRIMARY_API_URL", "https://api.openai.com/v1/chat/completions")
    primary_api_key: str = os.getenv("PRIMARY_API_KEY", "")
    primary_model: str = os.getenv("PRIMARY_MODEL", "gpt-4o")
    fallback_api_url: str = os.getenv("FALLBACK_API_URL", "http://127.0.0.1:8000/v1/chat/completions")
    fallback_api_key: str = os.getenv("FALLBACK_API_KEY", "none")
    fallback_model: str = os.getenv("FALLBACK_MODEL", "Qwen3.6-35B-A3B-abliterated-NVFP4-MTP")
    buffer_content_tokens: int = field(default_factory=lambda: _int_env("BUFFER_CONTENT_TOKENS", 25))
    buffer_reasoning: int = field(default_factory=lambda: _int_env("BUFFER_REASONING", 0))
    max_attempts: int = field(default_factory=lambda: _int_env("MAX_ATTEMPTS", 3))
    retry_base_delay: float = field(default_factory=lambda: _float_env("RETRY_BASE_DELAY", 0.5))
    fallback_max_attempts: int = field(default_factory=lambda: _int_env("FALLBACK_MAX_ATTEMPTS", 3))
    assembly_enabled: int = field(default_factory=lambda: _int_env("ASSEMBLY_ENABLED", 1))
    orchestrator_model: str = field(default_factory=lambda: os.getenv("ORCHESTRATOR_MODEL", "") or os.getenv("PRIMARY_MODEL", "gpt-4o"))
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


SETTINGS = Settings()

# --------------------------------------------------------------------------
# F26 metrics - plain dict counters, rendered as Prometheus text.
# --------------------------------------------------------------------------
_METRICS = {
    "requests_total": 0,
    "requests_clean": 0,
    "diverted_total": 0,
    "authz_denied_total": 0,
    "fallback_errors_total": 0,
    "assembly_total": 0,
    "in_flight": 0,
    "specialist_warm": 0,
}


def incr(name: str, n: int = 1) -> None:
    """Never raises into the request path (design rule 7)."""
    try:
        _METRICS[name] = _METRICS.get(name, 0) + n
    except Exception:
        pass


def metrics_snapshot() -> dict:
    return dict(_METRICS)


def render_prometheus() -> str:
    lines = []
    for key, value in sorted(_METRICS.items()):
        help_text = {
            "requests_total": "requests accepted by the gateway",
            "requests_clean": "requests committed to the sovereign",
            "diverted_total": "requests diverted to the specialist",
            "authz_denied_total": "requests denied by F9 authz",
            "fallback_errors_total": "specialist transport/HTTP failures",
            "assembly_total": "/v1/execute attempts",
            "in_flight": "streams currently open",
            "specialist_warm": "keep-alive liveness of the specialist (1/0)",
        }.get(key, key)
        lines.append(f"# HELP {key} {help_text}")
        lines.append(f"# TYPE {key} gauge")
        lines.append(f"{key} {value}")
    return "\n".join(lines) + "\n"


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
    texts = []
    for m in body.get("messages") or []:
        if isinstance(m, dict):
            c = m.get("content")
            if isinstance(c, str):
                texts.append(c)
            elif isinstance(c, list):
                texts.extend(str(b.get("text", "")) for b in c if isinstance(b, dict))
    if is_no_go(" ".join(texts)):
        audit_record(
            request_id="nogo",
            primary_model=SETTINGS.primary_model,
            worker_model="",
            signal="gate7_no_go",
            mode="pre-routing",
            audit_log=SETTINGS.audit_log,
        )
        raise HTTPException(status_code=403, detail="request falls into a hard no-go class")


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
) -> AsyncGenerator[bytes, None]:
    """Stream the specialist for a diverted request. Yields OpenAI SSE chunks:
    specialist output verbatim, then a provenance footnote delta,
    finish_reason="stop", then [DONE]."""
    s = settings or SETTINGS
    msgs = format_messages(original_messages, system=system_prompt)
    assert_clean(msgs)
    sid = f"fallback-{uuid.uuid4().hex[:12]}"  # R1: stable for the whole stream
    payload = {"model": s.fallback_model, "messages": msgs, "stream": True}
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
        audit_log=s.audit_log,
    )

    try:
        resp = await open_fallback(app.state.http, payload, headers, s)
    except PrimaryOpenError as exc:
        yield _sse({"error": f"specialist unavailable ({exc.status}): {exc.detail}"})
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

# --------------------------------------------------------------------------
# Streaming ring-buffer endpoint (section 3).
# --------------------------------------------------------------------------
@app.post("/v1/chat/completions")
async def chat_proxy(request: Request):
    body = await request.json()
    run_guards(body, request.headers.get(PRINCIPAL_HEADER))
    incr("requests_total")
    app.state.in_flight = getattr(app.state, "in_flight", 0) + 1

    messages = body.get("messages") or []
    user_query = _last_user_text(messages)
    request_id = f"gw-{uuid.uuid4().hex[:12]}"
    settings = SETTINGS

    # B11 gate: the speculative hedge only fires on latency hints or force.
    hedge_requested = should_hedge(user_query, force=body.get("hedge") is True)

    primary_payload = {
        "model": body.get("model") or settings.primary_model,
        "messages": messages,
        "stream": True,
        "max_tokens": body.get("max_tokens", 4096),
    }
    if body.get("tools"):
        primary_payload["tools"] = body["tools"]
    if body.get("tool_choice"):
        primary_payload["tool_choice"] = body["tool_choice"]
    if body.get("temperature") is not None:
        primary_payload["temperature"] = body["temperature"]
    primary_headers = {**_auth_header(settings.primary_api_key), "Content-Type": "application/json"}

    async def coordinator() -> AsyncGenerator[bytes, None]:
        try:
            if hedge_requested:
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
                    audit_log=settings.audit_log,
                )

                h = speculative_hedge.SETTINGS
                h.sovereign_url = settings.primary_api_url
                h.sovereign_key = settings.primary_api_key
                h.sovereign_model = primary_payload["model"]
                h.worker_url = settings.fallback_api_url
                h.worker_key = settings.fallback_api_key
                h.worker_model = settings.fallback_model
                async for chunk in speculative_hedge.hedge_stream(
                    messages, request_id=request_id, client=app.state.http
                ):
                    yield chunk
                return

            try:
                resp = await open_primary(app.state.http, primary_payload, primary_headers, settings)
            except PrimaryOpenError as exc:
                if exc.divert:
                    incr("diverted_total")
                    async for chunk in fallback_stream(
                        messages,
                        request_id=request_id,
                        signal=f"tier1_open_{exc.status}",
                        settings=settings,
                    ):
                        yield chunk
                else:
                    yield _sse({"error": f"upstream error ({exc.status}): {exc.detail}"})
                    yield _delta_chunk({}, finish="stop", model=primary_payload["model"])
                    yield b"data: [DONE]\n\n"
                return

            state = "BUFFERING"
            pending: list = []  # buffered raw SSE lines, replayed verbatim
            buffer_text = ""
            content_tokens = 0
            routed_reason = ""

            try:
                # B7: ONE pass over ONE iterator - never re-enter, never drop.
                async for raw in resp.aiter_lines():
                    line = raw.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    body_s = line[5:].strip()
                    if body_s == "[DONE]":
                        if state == "BUFFERING":
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
                    for p in pending:
                        yield f"{p}\n\n".encode()
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
            ):
                yield chunk
        finally:
            app.state.in_flight = max(0, getattr(app.state, "in_flight", 1) - 1)

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
    directive = (
        "You are CYBER-FROST, a cybersecurity specialist.\n"
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
    body = await request.json()
    run_guards(body, request.headers.get(PRINCIPAL_HEADER))
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


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "in_flight": _METRICS.get("in_flight", 0),
        "metrics": metrics_snapshot(),
        "config": {
            "primary_model": SETTINGS.primary_model,
            "fallback_model": SETTINGS.fallback_model,
            "buffer_content_tokens": SETTINGS.buffer_content_tokens,
            "buffer_reasoning": SETTINGS.buffer_reasoning,
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








