# Architecture — Interception Gateway

> **REWRITTEN 2026-10-21** (accuracy pass). The previous version of this file was
> corrupted with diff-artifact line numbering (`N + ` prefixes on every line) and
> carried stale facts; it is preserved verbatim as the sibling
> [`ARCHITECTURE.orig.md`](ARCHITECTURE.orig.md). This rewrite is grounded in the
> source as it exists today: `routing_patterns.py`, `ingress_assembler.py`,
> `context_formatter.py`, `speculative_hedge.py`, `proxy_gateway.py`, and
> `litellm/routing_callback.py` — all at the **repo root** (the old
> `reference-implementation/` path no longer exists).

How the gateway, hedger, and assembler fit together.

---

## 1. System overview

```
                        ┌────────────────────────────────────────────────┐
  client ── HTTP/SSE ──▶ │             proxy_gateway.py (FastAPI)          │
                        │                                                 │
                        │  1. authz (F9) + body cap (32 MiB) + n>1 (E6)   │
                        │  2. capacity guard (MAX_CONCURRENT_STREAMS 429) │
                        │  3. open primary (retry 408/429 — B10)          │
                        │  4. ring-buffer state machine (B7/B8)           │
                        │        │                                        │
                        │      clean ── presignal → recovery? keep        │
                        │        │              else divert               │
                        │   passthrough + finish/[DONE]                   │
                        │                                                 │
                        │                    fallback_stream()            │
                        │                    specialist_messages()        │
                        │                    → footnote → audit           │
                        └────────────────────────────────────────────────┘
```

| Endpoint | Path | Purpose |
|---|---|---|
| `POST /v1/chat/completions` | streaming ring-buffer | drop-in OpenAI-compatible proxy |
| `POST /v1/execute` | orchestrator → worker → `assemble()` | Part IV deterministic assembly |
| `GET /healthz` | config + runtime snapshot (`HEALTHZ_PROBE=1` adds the live upstream probe) | liveness / introspection |
| `GET /metrics` | Prometheus text (F26) | counters + warm gauges |

## 2. Module map

| Module | Responsibility | Key exports |
|---|---|---|
| `routing_patterns.py` | **Single source of truth for routing logic** (F3), dependency-free | `ROUTING_RE`, `normalise`, `is_routable`, `is_presignal_recovered`, `should_hedge`, `reasoning_presignal`, `tier2_decision`, `classify_status`, `is_no_go`, `no_go_match`, `is_attack_content`, `attack_match`, `footnote`, `stage_comment` |
| `context_formatter.py` | Format context before the specialist sees it | `format_messages`, `specialist_messages`, `DEFAULT_SYSTEM`, `AUTHORIZED_FRAME`, `TERMINAL_AWARENESS`, `assert_clean`, `prune_artifacts` |
| `ingress_assembler.py` | Deterministic (non-LLM) merge + audit records | `assemble`, `validate_artifact`, `audit_record`, `artifact_sha256`, `SLOT`, `GRAMMAR_FOR` |
| `proxy_gateway.py` | FastAPI app: buffering, routing, metrics, endpoints | `app`, `fallback_stream`, `Settings`/`SETTINGS` |
| `speculative_hedge.py` | Speculative dual-dispatch (B9/B11 fixes) | `hedge_stream`, `HedgeSettings`, `SETTINGS` (the `hedge_settings` name never existed and is gone from `__all__`) |
| `litellm/routing_callback.py` | Non-streaming repair inside LiteLLM | `RoutingFootnoteCallback` |

**Single-source invariant:** `grep -rn 'ROUTING_RE = ' *.py` returns exactly one hit —
`routing_patterns.py:103`. The LiteLLM callback imports `is_routable`/`footnote`
rather than re-declaring them; duplicated detection logic was the root cause of
defects B20/B21 and E1/E2/E3. (`conftest.py` extends the real `litellm` package's
`__path__` with the local shim so `from litellm.routing_callback import ...` works
even when site-packages has litellm installed.)
## 3. Streaming state machine (`/v1/chat/completions`)

A single pass over one `aiter_lines()` iterator (B7: never re-enter a broken iterator).
States: `BUFFERING → {ROUTED, PASSTHROUGH, COMPLETE}`.

```
BUFFERING
  ├─ finish_reason == "timeout" or delta.error           → ROUTED    (Tier 1)
  ├─ delta.reasoning, BUFFER_REASONING=0                 → forward live,
  │                                                       do NOT count  (B21/F1)
  ├─ delta.content                                       → append, count tokens
  │     ├─ refusal PRESIGNAL + CONTINUE_ENABLED=1        → grace window:
  │     │     is_presignal_recovered() (head+tail, ≥20 chars,
  │     │     lecture-free)                              → keep primary (RECOVERED)
  │     │     else refusal confirms                      → ROUTED
  │     ├─ is_routable(buffer[-200:])                    → ROUTED    (Tier 3)
  │     └─ content_tokens ≥ BUFFER_CONTENT_TOKENS (10)   → PASSTHROUGH
  ├─ finish_reason present                               → COMPLETE
  └─ stream ends                                         → COMPLETE
```

Key invariants:

- **Buffered lines are held in `pending`**, replayed verbatim on pass-through;
  `finish_reason` and `[DONE]` are always propagated to the client (B7).
- **On ROUTED the buffered text is discarded** — never surfaced. Reasoning already
  forwarded is deliberation, not the error itself.
- **Routing is evaluated only while buffering** (B8); once in pass-through the stream
  is opaque.
- **`n>1` is rejected up front** (E6) — the buffer inspects one choice stream, so extra
  choices would bypass detection entirely.
- **Continue-with-primary refusal avoidance** (2026-10-21): a Tier-3 presignal does not
  divert immediately; `CONTINUE_ENABLED=1` (default) streams a `GRACE_TOKENS=10`
  window and keeps the primary only when `is_presignal_recovered()` says it
  self-corrected (anchored AND unanchored refusal checks + LECTURE-free, head AND
  tail judged). The gateway screens the buffer **tail** (`buffer[-200:]`).
- **Reasoning presignal** (T6.2): the helm's reasoning trace is screened by
  `reasoning_presignal()` (≥120 chars gate, helm only — the terminal's reasoning is
  never screened) and can divert on metadata alone, before any content token.
- **Commitment contract**: the reply that COMES BACK from a divert is judged before it
  ships — refusal-flavoured output costs one in-character re-ask; a watered-down
  costume (`WATERED_DOWN_DIVERT=1`) escalates instead of shipping.

### Gates before the primary sees the request

- **Gate 7 no-go** (`NO_GO_RE`, `is_no_go`, `no_go_match`): hard classes (CBRN, CSAM,
  stalkerware, nonconsensual surveillance) are 403'd pre-routing. `NO_GO_ENABLED=1`
  kill switch; `no_go_match()` records WHAT tripped it in the audit line.
- **Gate 8 attack content** (`ATTACK_CONTENT_RE` + `_OFFENSIVE_REQUEST_RE` shapes
  A/A2/A3/B with defensive-span discrimination): a **forced divert** to the specialist
  before the primary is consulted. **Opt-in: `ATTACK_GATE_ENABLED=0` default** — a
  forced divert silently substitutes the model the operator asked for.

### Tier 2 / escalation (off the critical path)

- **Tier 2** (`tier2_decision`): joint log-prob mass over `TIER2_OPENERS`
  (`"i","as","sorry","my","no","unfortunately"`), threshold `τ=0.85` default.
  Decision support only — NOT wired into the streaming loop (the streaming path does
  not request logprobs); intended for non-streaming repair paths.
- **Escalation ladder** (2026-10-21): a chain name IS the contract
  (`DEEPMAX>GLM>ABLITV2L` = DeepSeek-max helm → GLM no-reasoning middle → Abliterated
  V2 Large terminal); a confirmed refusal climbs to the cheap middle first and only a
  twice-refusing middle reaches the terminal. Non-chain routes opt in with
  `ESCALATION_MIDDLE=1` (default 0). `UNCENSORED_MIDDLE=1` swaps the middle for the
  uncensored Abliterated Large (T5.6). Resolution lives in
  `providers.py::CONSTELLATION_CHAINS`; REDHANDS activation for chain-3 /
  `X-Max-Offense: 1` is in `redhands.py`.
## 4. Diversion path (`fallback_stream`)

1. `specialist_messages()` — the **whole conversation**, artifacts pruned turn-by-turn,
   neutral system injected (F7: `format_messages()`'s 4-stage reduction to
   `[DEFAULT_SYSTEM, latest user turn]` silently dropped 27k-token contexts and tool
   results on a plain divert; the reduction remains correct for `/v1/execute`, which
   builds its own sanitized worker prompt). `assert_clean()` is the invariant.
2. Retry wrapper — retries `DIVERT = {500,502,503,504}` with backoff (F6); a 503 is
   *capacity*. `FALLBACK_MAX_ATTEMPTS=3`.
3. Audit record emitted **before** the call (`audit_record`, mode=`stream`; `forced`
   and `signal_match` keys appear only on Gate-8 diverts).
4. Specialist SSE forwarded verbatim, then a provenance footnote delta
   (`footnote()` → `\n\n{friendly} taking over...`), `finish="stop"`, `[DONE]` —
   the upstream finish chunk is HELD so no content follows a finish reason (R4).
5. Budget bound: `SPECIALIST_MAX_TOKENS=4096` (0 = unbounded, the old behaviour that
   402'd), min()'d with the client's own `max_tokens`.
6. REVERSE HANDBACK: a terminal that answers `[[GW-HANDBACK]]` hands benign work back
   to the helm before anything ships (`handback_total`).

**Error taxonomy (B10)** — the distinction the whole design hinges on (`classify_status`):

| Status | Meaning | Action |
|---|---|---|
| 400/401/403/404/422 | client/authorisation error | fail fast, no retry, no divert |
| 408/429 | transient rate limit | retry **same provider**, never divert |
| 500/502/503/504 | capacity / server fault | retry, then **divert** |
| `timeout` / `error` metadata / transport None | upstream timeout | **divert** (Tier 1) |

## 5. Two diversion strategies

### A. Ring-buffer proxy (default) — `proxy_gateway.py`

Serial, one upstream stream, commit-or-discard after ≤10 content tokens
(`BUFFER_CONTENT_TOKENS`, calibrated 2026-10-05 down from 25: the anchored regex fires
by the 5th content word worst-case, so TTFT dropped 0.59 s → 0.24 s at equal recall).

### B. Speculative hedge — `speculative_hedge.py`

Dispatches to both models concurrently via `build_request()` + `send(stream=True)` under
an `AsyncExitStack` (B9: `AsyncClient.stream()` is an async CM, not awaitable — the
corpus's `asyncio.gather(...)` raised `TypeError`).

- **Gated by `should_hedge()`** (B11) — hedges only on latency-hint matches
  (`HEDGE_HINT_RE`, case-sensitive `HEDGE_HINT_ASAP_RE`) or `force`, because firing both
  branches on every request doubles cost and halves concurrency (p\* ≈ 0.51 break-even).
- Reasoning deltas are **forwarded live by default** (`HEDGE_LIVE_REASONING=1`) but
  **never counted toward `COMMIT_TOKENS` (10) and never screened** (F1/B21) — committing
  to the sovereign during deliberation would leak the error. `=0` holds them again.
- Commit rules: timeout/`error` → worker; ≥10 content tokens or `[DONE]`/finish →
  sovereign (buffer replayed verbatim); the worker path discards the sovereign buffer
  entirely and appends the footnote.
## 6. Deterministic assembly (`/v1/execute`)

```
messages ─▶ orchestrator ─▶ plan JSON
              │  requires_unrestricted_worker?
              ├─ no  → return direct_response
              └─ yes → subtask + scaffolding (must contain unique SLOT)
                         │
                         ▼
                     run_specialist(subtask)   ── formatted, retry-wrapped
                         │
                         ▼
                     assemble(scaffolding, artifact)   ← pure string replace, fails closed
                         │
                         ▼
                     audit (sha256 of artifact + deliverable) → response + footnote
```

- **Never an LLM merge.** `assemble()` raises on missing/duplicate `SLOT`
  (`{{UNRESTRICTED_PAYLOAD}}`) or an empty artefact rather than degrading into a
  model-mediated merge — that is the Ingress Assembly Shock defence: the sovereign must
  never read the specialist's raw output.
- `validate_artifact()` gates structure pre-slot (python → AST parse,
  `json_sarif` → `json.loads`); `GRAMMAR_FOR["json_sarif"]` (`SARIF_DEFECT_GBNF`) is
  passed as TabbyAPI `grammar_string` to logit-lock rigid formats.
- `ORCHESTRATOR_MODEL` defaults to `PRIMARY_MODEL`; `ASSEMBLY_ENABLED=1` default.
- T4.2 fan-out: up to `FANOUT_MAX_PARALLEL=4` subtask specialists; the `/bus/*` team
  surface exists only when `BUS_ENABLED=1` (default 0).

## 7. Cross-cutting concerns

**Formatter.** Four ordered stages: drop system/developer turns → inject
`DEFAULT_SYSTEM` → prune provider artifacts (`<thinking>`, `antml:`, `im_start|`,
`system-reminder:`) → keep the latest user turn (`format_messages`) or the whole
conversation (`specialist_messages`). `assert_clean()` is the testable invariant.
2026-10-21 frames: `AUTHORIZED_FRAME` (established-authorization context, default on),
`COMPLETION_CONTRACT` (`[[GW-CHECKLIST]]` coverage + one repair re-dispatch),
`TERMINAL_AWARENESS` ([[GW-HANDBACK]] reverse handback + `[[GW-SKILL:]]` learned-skills
markers injected via `skill_frame()`), `SPECIALIST_SYSTEM_MODE=redhands` for the
REDHANDS persona (`redhands.py`).

**Audit trail (F5).** Every diversion and every assembly emits one JSON line: request
id, primary/worker model, routing signal, mode, sha256 of artefact and deliverable;
`forced` + `signal_match` only on Gate-8 diverts. Written to `AUDIT_LOG` if set, always
to stdout, and **never raises into the request path** (design rule 7) — `audit_record`
catches everything and returns `{}` on failure.

**Metrics (F26).** Plain dict counters rendered as Prometheus text at `/metrics`:
`requests_total`, `diverted_total`, `forced_divert_total`, `authz_denied_total`,
`fallback_errors_total`, `primary_errors_total`, `assembly_total`, `fanout_total`,
`presignal_detected_total`, `ladder_secondary_total`, `ladder_terminal_total`,
`watered_down_divert_total`, `rescue_divert_total`, `handback_total`,
`completion_reask_total`, `reasoning_presignal_total`, `continue_divert_total`,
`account_pool_*`, plus `in_flight` and `specialist_warm` gauges. (`requests_clean`
appeared in the old doc but was never incremented; it is not a metric.
`incr()` never raises — design rule 7.)

**Lifecycle (F10/F27).** Lifespan starts the keep-alive poller
(`KEEPALIVE_URL`, `KEEPALIVE_INTERVAL_S=240`) and, on shutdown, drains `in_flight` to
zero for up to `SHUTDOWN_GRACE_S` (default 10 s) so streams are not severed.
`_stream_opened()`/`_stream_closed()` keep `app.state.in_flight` and the published
gauge in lockstep (they used to diverge, so a wedged stream was invisible), and the
close is clamped at zero.

**Stage annotations.** `stage_comment()` emits SSE comment lines (`: gw-stage ...`)
with a near-white tint + glow hue per stage from `STAGE_STYLES` (`STAGE_PALETTE=green`
selects the alternative palette); OpenAI-style consumers that parse only `data:` lines
ignore them, and every chunk also carries the answering model in its `model` field.

**Key resolution (F25).** Tests read keys via `evals/_keys.py`: env → secret file →
Cline config fallback (with warning). The gateway itself only reads env vars.
## 8. Configuration surface (env vars)

| Group | Variables | Default |
|---|---|---|
| Primary | `PRIMARY_API_URL/KEY/MODEL` (bridged to `HIVE_API_BASE`/`HIVE_SECRET_KEY` when unset) | Hive `zai-org/glm-5.3-flash`, else OpenAI `gpt-4o` |
| Specialist | `SPECIALIST_API_URL/KEY/MODEL` (override `FALLBACK_*`; key falls through to `NANOGPT_API_KEY`) | local vLLM `:8000`, `Qwen3.6-35B-A3B-abliterated-NVFP4-MTP` |
| Buffer | `BUFFER_CONTENT_TOKENS`, `BUFFER_REASONING` | `10`, `0` (reasoning never counted) |
| Retry | `MAX_ATTEMPTS`, `RETRY_BASE_DELAY`, `FALLBACK_MAX_ATTEMPTS` | `3`, `0.5`, `3` |
| Assembly | `ASSEMBLY_ENABLED`, `ORCHESTRATOR_MODEL`, `FANOUT_MAX_PARALLEL` | `1`, = primary, `4` |
| Audit | `AUDIT_LOG` | empty (stdout only) |
| Governance | `AUTHORISED_PRINCIPALS`, `AUTHZ_ENFORCED`, `KEEPALIVE_URL`, `KEEPALIVE_INTERVAL_S` | off / `0` / — / 240 |
| Shutdown | `SHUTDOWN_GRACE_S` | `10` |
| Hedge | `SOVEREIGN_*`, `WORKER_*`, `COMMIT_TOKENS`, `HEDGE_LIVE_REASONING` | mirrors primary/specialist, `10`, `1` |
| Gates | `NO_GO_ENABLED`, `ATTACK_GATE_ENABLED` | `1`, `0` (Gate 8 opt-in) |
| Presignal | `CONTINUE_ENABLED`, `GRACE_TOKENS`, `MIN_SUBSTANTIVE_CHARS`, `REASONING_PRESIGNAL` | `1`, `10`, `20`, `1` |
| Ladder | `ESCALATION_MIDDLE`, `UNCENSORED_MIDDLE`, `WATERED_DOWN_DIVERT` | `0`, `0`, `1` |
| Frames | `AUTHORIZED_FRAME`, `COMPLETION_CONTRACT`, `SKILL_MEMORY`, `CAMO_ENABLED`, `SPECIALIST_SYSTEM_MODE` | `1`, `1`, `1`, `1`, `neutral` |
| Budgets | `SPECIALIST_MAX_TOKENS`, `HEDGE_MAX_TOKENS` | `4096`, hedge-side cap |
| DoS | `MAX_BODY_BYTES`, `MAX_CONCURRENT_STREAMS` | 32 MiB (413), 64 (429) |
| Palette | `STAGE_PALETTE` | `default` |

Run: `uvicorn proxy_gateway:app --host 127.0.0.1 --port 9000`

## 9. LiteLLM callback (non-streaming repair)

`litellm/routing_callback.py::RoutingFootnoteCallback` imports `is_routable`/`footnote`
from `routing_patterns` and `audit_record` from `ingress_assembler` (never re-declares
the regex). `apply(response)` detects a refusal on a NON-streaming response, appends
the provenance footnote (`model_label` from `LITELLM_ROUTING_FOOTNOTE_MODEL`, default
`specialist`), and emits `signal="tier3_refusal", mode="litellm_post_call"`. Both hook
protocol methods (`async_post_call_success_hook`, `post_call_success_hook`) delegate to
`apply()` and never raise into the request path. Scope: disclosure + signal only — the
actual divert lives in the streaming gateway. Register with:

```yaml
litellm_settings:
  callbacks: routing_callback.RoutingFootnoteCallback
```

`litellm` itself is imported lazily inside the hooks, so the module (and its tests)
load without litellm installed.
## 10. Design rules the code enforces

1. **One source of truth** for routing detection and the neutral prompt — no local copies.
2. **A 429/503 is not a routable error.** Error taxonomy is explicit and unit-tested.
3. **Never surface a buffered error.** Discard on divert; reason-only output is deliberation.
4. **Reasoning is not content** — forwarded for TTFT (live by default), never counted
   toward the commit budget, never screened for refusals.
5. **Assembly fails closed** and is never model-mediated.
6. **Guards run once, shared** by both endpoints.
7. **Hooks/guards never raise into the request path** — degrade with an explanatory chunk.

## 11. Where the tests live

| Concern | Suite |
|---|---|
| detection / formatter / assembler / calibration | `evals/routing_probe.py`, `evals/hedge_calibrate.py` |
| authz / gates / attack content | `evals/routing_test.py`, `evals/nogo_gate_probe.py`, `evals/attack_gate_test.py` |
| LiteLLM callback | `evals/callback_test.py` |
| hedging | `evals/hedge_test.py`, `evals/hedge_budget_test.py`, `evals/hedge_empty_test.py` |
| streaming gateway | `evals/e2e_gateway_test.py`, `evals/stream_finalize_test.py` |
| `/v1/execute`, audit, fan-out, retry | `evals/assembly_test.py`, `evals/fanout_test.py` |
| tool calls, n>1, disconnect, concurrency, metrics | `evals/edge_test.py` |
| chains / redhands / pool | `evals/constellation_test.py`, `evals/redhands_test.py`, `evals/ablit_pool_test.py` |
| real local vLLM / live stack (opt-in, skipped by default) | `evals/live_stack_test.py` |

Run all: `./run_all_tests.sh`. See `README.md` for results and `corrections-ledger.md`
for the B/E defect IDs referenced above. (`evals/tinfoil_live_test.py` from the old doc
no longer exists; `evals/live_stack_test.py` is the live-suite home.)





