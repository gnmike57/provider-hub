> **SUPERSEDED (2026-10-21) — implementation superseded.** This plan's Tier-2/3 model
> surface (`REASONER_*` via NanoGPT `z-ai/glm-5.3:thinking`, `abliteration-ai/abliterated-model-large-v2`
> as R3 via the NanoGPT key) was replaced by the 2026-10-21 constellation directive.
> Successor docs, in order:
> 1. `docs/single-model-chain-plan.md` (2026-10-20) — the staged `deep*`/`glm*` proposal
>    that first superseded this plan's §2/§8 option surface (its own SUPERSEDED banner
>    below explains how that ended).
> 2. `docs/constellation-hub-plan.md` — **current plan of record**: three hub models
>    (`providers.py::CONSTELLATION_CHAINS`), REDHANDS terminal persona, 2-key
>    Abliteration pool (`abliteration_keys.py`).
>
> Reconciliation with the code (verified 2026-10-21): the plumbing this plan chose to
> extend — the `hedge` body-param branch selector, the ring-buffer divert machinery,
> `should_hedge()`, the B10 status taxonomy, and the Tier-1/2/3 detection concepts —
> all remain live in `proxy_gateway.py` / `routing_patterns.py` / `speculative_hedge.py`.
> Stale here: model ids (`z-ai/glm-5.3:thinking`, `abliteration-ai/*` are not in the
> constellation), the `REASONER_*` env trio (never existed in `proxy_gateway.Settings`),
> and every `reference-implementation/` path — the modules live at the repo root.

# Plan: Three-Tier Speculative Routing for provider-hub
# Plan: Three-Tier Speculative Routing for provider-hub

**Tier 1 (default):** thehive.ai `zai-org/glm-5.3-flash`
**Tier 2 (deep reasoning):** NanoGPT `z-ai/glm-5.3:thinking`
**Tier 3 (uncensored fallback):** NanoGPT `abliteration-ai/abliterated-model-large-v2`

Status: research-complete, awaiting implementation go-ahead.
Date: 2026-10-15 (all facts in §0 probed live today)


## 0. State of the world (verified, not assumed)

| Fact | Evidence |
|---|---|
| Hive GLM-5.3-flash answers PONG | POST `https://api-cdn.thehive.ai/api/v3/chat/completions`, `Authorization: Bearer <hive key>`, envelope exposes `message.refusal` + `message.reasoning` + `reasoning_tokens` (free early-divert signals), finish_reason=stop. Key from `gateway_registry.json` |
| `hedge` body param is the only branch selector | `proxy_gateway.py` ~line 800: `if not body.get("hedge") -> primary stream; else speculative_hedge.race()` |
| `fallback_stream()` inner loop takes one (url,key,model) | meta-comment ~line 573: "keep the inner loop generic: it only knows (url, key, model)" |
| Stream loop already has reason-based divert-to-specialist | late lines ~790-905: `tier1_thinking_only / tier1_empty / tier1_stream_broke`, buffer discarded, dispatch worker |
| `should_hedge()` is the single detection mouth | lives in `routing_patterns.py`, imported by gateway and hedge |
| Tier-2 model PONGs via NanoGPT | POST `https://nano-gpt.com/api/v1/chat/completions`, Bearer, `z-ai/glm-5.3:thinking` |
| Tier-3 model PONGs via NanoGPT | same endpoint, `abliteration-ai/abliterated-model-large-v2` |
| `SPECIALIST_API_URL/KEY/MODEL` env trio is the worker binding | Settings dataclass, consumed by `fallback_stream` caller |
| 101 passed / 3 skipped / 4 warnings baseline | re-confirmed today (4.6 s), py_compile clean |
| No `/v1/chat/hedged` endpoint exists | only inside `chat_proxy`; historical docs mention it — do not rely on it |


## 1. Architecture decision

**Recommendation: extend the existing three plumbing layers — do NOT rewrite.**

Reuse what already works: the race machinery (every failover funnels into the
same three branches), the buffering/replay contract, the structured divert
reasons, and the entire refusal taxonomy. We bolt on a third specialist and
deepen the detection layer.

Rejected alternatives:
- **Race all three tiers up-front**: triples cost on every request; only pays
  off when refusal/hard-reasoning risk is high and unknowable. Wrong default —
  both conditions are predictable from the prompt or the early stream; race
  only when genuinely ambiguous.
- **Separate `/v1/chat/hedged` endpoint**: fragments the client contract;
  clients should not need to know whether to hedge. `hedge: true` on the
  normal endpoint stays the only door.


## 2. Model & endpoint bindings

| Role | Variable | Value |
|---|---|---|
| R1 primary URL | `PRIMARY_API_URL` | `https://api-cdn.thehive.ai/api/v3/chat/completions` (from `gateway_registry.json` `providers.hive.base_url`) |
| R1 primary key | `PRIMARY_API_KEY` | value of `providers.hive.key` (NOTE: sits plaintext in the registry file — rotate and move to env) |
| R1 model | `PRIMARY_MODEL` | `zai-org/glm-5.3-flash` |
| R2 reasoner URL | `REASONER_API_URL` (new) | `https://nano-gpt.com/api/v1/chat/completions` |
| R2 key | `REASONER_API_KEY` (new) | `NANOGPT_API_KEY` (fresh mint, key id=245160, already rotated into HKCU) |
| R2 model | `REASONER_MODEL` (new) | `z-ai/glm-5.3:thinking` |
| R3 specialist URL | `SPECIALIST_API_URL` (existing) | `https://nano-gpt.com/api/v1/chat/completions` |
| R3 key | `SPECIALIST_API_KEY` (existing) | also `NANOGPT_API_KEY` |
| R3 model | `SPECIALIST_MODEL` (repointed) | `abliteration-ai/abliterated-model-large-v2` |

Bonus signal: Hive's structured `message.refusal` field plus
`reasoning_tokens` accumulating while `content` stays empty give the streaming
loop a cheap early Tier-3 trigger without waiting for the regex.

Discovery: `GET /v1/models` extended to list the three tiers with a `tier`
field and a `handles` prompt-class string, so operators can read the routing
topology without touching env docs (extra fields are OpenAI-compatible; known
clients ignore them).

## 3. Work breakdown (T-items)

- **T1 — Tiered specialist chain (plumbing):**
  Settings gains `reasoner_api_url/key/model` (same env pattern as existing
  fields). `fallback_stream()` keeps its (url,key,model) call shape but the
  coordinator gains a **tier list** `[(url, key, model, reason_tag)]`;
  the generic inner loop is invoked repeatedly with distinct `signal=` reasons
  (`tier2_refusal`, `tier3_refusal`, `tier2_hard_prompt` ...). Terminal finish
  reasons set `_TERMINAL_FINISH = {"stop", "length", "tool_calls"}` decide when
  the chain stops escalating.

- **T2 — Refusal taxonomy extension (classification):**
  In `routing_patterns.py`, widen the B10 family:
  `REFUSAL_APOLOGY` (sorry/apologize + can't/unable — currently mistyped),
  `REFUSAL_PARTIAL_RESET` (rephrase/try again/instead), and a partial class for
  answers-then-rolls-off. All stay **routable** and feed the existing
  `divert_audit_total{reason=...}` counters.

- **T3 — Partial-refusal tail logic (buffering):**
  If refusal markers appear **after** the buffer flushed, do not silently stall:
  mark the flushed prefix abandoned, send the specialist a **continuation
  prompt** (last clean window + "continue cleanly"), emit the standard
  `<<divert>>` footnote, and if the continuation also refuses, escalate along
  the chain (R2 → R3 → terminal refusal artifact). Accepted trade-off: client
  sees a short stale fragment followed by the clean continuation.

- **T4 — Tier-3 trigger (refusal interceptor):**
  R1 solo streams by default — no up-front race. Existing buffered-region
  refusal check stays the primary trigger; new cheap signals: sliding head
  check on the flush window, and Hive envelope `message.refusal == true` while
  still BUFFERING → immediate Tier-3 divert. If T5 classified the prompt as
  hard, Tier-2 is tried before Tier-3 in the chain.

- **T5 — Hard-prompt classifier (R2 trigger):**
  Static heuristic module in `routing_patterns.py` (no extra LLM call):
  math-symbol density, combinatorial keywords, complexity stems (`O(n^2)`,
  `1e9` constraints, proof verbs). Score > τ ⇒ either (a) race R1+R2 via
  `speculative_hedge.race` and prefer the first usable answer, or (b) if the
  classifier was borderline, start R1 solo and diverge mid-stream when the
  thinking-only/empty-content boundary stalls. Default τ conservative.

- **T6 — Mid-stream R2→R3 handoff:**
  If R2 refuses mid-answer, use the T3 continuation mechanism from R2's clean
  prefix instead of a full conversation replay.

- **T7 — `/v1/models` + README:**
  list all three tiers with `tier` + `handles` fields; document env knobs and
  the kill switches.

- **T8 — Tests:**
  - new `evals/tier_chain_test.py`: three-stub pipeline — R1 refuses → R2
    answers; R1+R2 refuse → R3 answers; R1 partial-refusal → continuation;
    hard-prompt → R2 pre-race wins; Hive `refusal` flag → instant R3.
  - extend `evals/live_stack_test.py` with a LIVE_STACK=1-gated tier-2/3 cell
    (offline CI still skips everything).
  - existing tests untouched and green (they pin today's chain contract).

- **T9 — Rollout/rollback:**
  Single env kill switches: `REASONER_ENABLED=0` collapses the chain to
  R1→R3 (today's behavior + taxonomy); `SPECIALIST_ENABLED=0` further
  collapses to pure primary passthrough. Ship with both =1; flipping to 0
  reverts operator behavior without redeploy.


## 4. Sequencing & estimates

- **Milestone A (core chain, ~4 h):** T1, T4, cheap T5 (keyword list only),
  T9 → already satisfies the stated request: GLM-flash default, NanoGPT
  thinking on hard prompts, abliterated-v2-large on refusals.
- **Milestone B (partial + polish, ~3 h):** T2, T3, T6.
- **Milestone C (DX + tests, ~2.5 h):** full T5 heuristics, T7, T8.


## 5. Test plan

- `python -m pytest evals -q` stays green: baseline today = **101 passed /
  3 skipped / 4 warnings**.
- `tier_chain_test.py` passes offline (stubs only).
- Manual curl matrix: simple prompt → R1 only; math prompt → R2 engaged;
  red-team refusal prompt → R3; injected partial-refusal stream → continuation
  visible in SSE with footnote.
- Live cells only under LIVE_STACK=1 (never default CI).


## 6. Open questions (defaults chosen, override freely)

1. **Up-front R2 race on every hard-classified prompt?** Default: yes when τ
   exceeded; borderline prompts start R1 solo and may diverge mid-stream.
2. **Tier-2 locked to GLM-5.3-thinking?** Default: yes. Alternative (deferred):
   per-class model poll via NanoGPT's catalog (deepseek-r for math etc.).
3. **R2/R3 spend shares the HEDGE_BUDGET_MS pool?** Default: yes; revisit only
   if R3 starves R1 in race mode.


## 7. Verification data (live probes, 2026-10-15)

- R1: `zai-org/glm-5.3-flash` → PONG, finish stop, `reasoning_tokens: 96`,
  envelope fields `refusal`, `reasoning` present.
- R2: `z-ai/glm-5.3:thinking` → PONG.
- R3: `abliteration-ai/abliterated-model-large-v2` → PONG.
- Keys: persisted `NANOGPT_API_KEY` was revoked server-side ("Invalid
  session"); minted replacement id=245160 via Management API (fresh
  Idempotency-Key), rotated `NANOGPT_API_KEY` + saved `NANOGPT_API_KEY_HUB`.
  **Orphan to revoke: key id=245159** (created while probing the response
  shape; its secret was never captured/used).
- NanoGPT auth facts: `Authorization: Bearer` or `x-api-key` both accepted on
  `/api/v1/*`; model catalog is public; chat route requires a valid key;
  Management API (`/api/management/v1`, mgmt key) lists/creates keys.



## 8. Options matrix — every decision point, all alternatives

Legend: **Effort** = hours inside Cline CLI. **Risk** = L/M/H. **Scope** =
✅ fully verifiable in this CLI session · ◐ partially (needs operator) ·
○ out of Cline scope. **Δ** = deviation from default.

### 8.1 Tier-2 trigger ("very hard reasoning" detection)

| ID | Option | How it works | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| T2-A | **Keyword/symbol heuristic** (DEFAULT) | Static scorer in `routing_patterns.py`: math-symbol density, combinatorial keywords, complexity stems (`O(n^2)`, `1e9`, proof verbs). > τ ⇒ race R1+R2 | 1.5 h | L | ✅ unit-test offline | ships Milestone A |
| T2-B | Reactive-only (no race) | Just let R1 stream; divert to R2 only on `tier1_thinking_only`/empty-content stall. Zero up-front cost, R2 pays full second TTFT on hard prompts | 0.5 h | L | ✅ | fallback if τ misfires |
| T2-C | Always race R1+R2 per request | `speculative_hedge.race` on every call, prefer fast clean answer | 1 h | M (2× cost always) | ✅ | rejected as default; keep behind `T2C_RACE_ALL=1` |
| T2-D | `tier2_decision` logprob-mass router | Use the existing unwired `tier2_decision` in `routing_patterns.py`; needs `logprobs` echo from Hive — **verify Hive supports it first** (probe T2D-PRECHECK) | +2 h | M (provider support unknown) | ✅ probe ◐ if unsupported | Δ stretch goal, Milestone C |
| T2-E | LLM-based router call | Tiny classifier model call before dispatch | +1 h | M (adds latency + cost to every req) | ✅ | rejected: violates "no model-mediated routing" design rule 5 spirit |

### 8.2 Tier-3 trigger (refusal detection)

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| T3-A | Current regex only | Existing `should_hedge`/B10 taxonomy unchanged, just repoint specialist | 0.1 h | L | ✅ | baseline |
| T3-B | **T3-A + Hive `message.refusal` field** (DEFAULT) | Non-stream envelope exposes structured refusal flag; streaming loop also honors it while BUFFERING → instant divert | 0.5 h | L | ✅ (field verified in PONG probe) | Milestone A |
| T3-C | T3-B + partial-tail continuation | Post-flush refusal ⇒ continuation prompt from clean window (plan T3/T6) instead of stall/replay | 2 h | M (client sees stale fragment) | ✅ stub-tested offline | Milestone B |
| T3-D | Always race uncensored model | R3 shadow on every request | 1 h | H (cost, normalizes uncensored output) | ✅ | rejected |
| T3-E | Tail-window regex scan of last N flushed tokens | Catches answers-then-rolls-off without continuation machinery | 1 h | M (false positives on legit "sorry" turns) | ✅ | fold into Milestone B behind flag |

### 8.3 Return-path UX when a tier switches mid-answer

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| R-A | **Full replay of conversation to next tier** (DEFAULT, today's mechanism) | Buffered discarded; worker gets original messages | 0 h (exists) | L | ✅ | baseline |
| R-B | Continuation prompt from clean window | T3 continuation: prefix + "continue cleanly" | 2 h | M | ✅ offline stubs | Milestone B |
| R-C | Footnote disclosure only, same model chain re-prompted | Existing `FOOTNOTE_TEMPLATE` | 0.2 h | L | ✅ | already in every divert; mandatory in all options |

### 8.4 Wiring & configuration surface

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| W-A | **Env-driven `REASONER_*` trio + kill switches** (DEFAULT) | Mirrors existing `PRIMARY_*`/`SPECIALIST_*`; `REASONER_ENABLED`/`SPECIALIST_ENABLED` | 0.5 h | L | ✅ py_compile + tests | Milestone A |
| W-B | Runtime-loadable `gateway_registry.json` | Make the (currently dead) registry live; Tier-1 pulled from it | 2 h | M (new failure surface) | ✅ | Δ optional, Milestone C; don't make latency-critical path depend on it |
| W-C | Hardcode the trio in `Settings` defaults | Zero-config start | 0.1 h | M (keys in source) | ✅ | reject for keys; acceptable for URLs/models |
| W-D | Hybrid: URLs/models hard-defaulted, keys env-only | Code works out of the box; secrets never touch disk | 0.3 h | L | ✅ | fold into W-A |

### 8.5 Secrets handling

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| S-A | **HKCU env vars, referenced only as `$env:NAME`/`os.getenv`** (DEFAULT, current state) | `NANOGPT_API_KEY` (rotated), `NANOGPT_API_KEY_HUB`, mgmt key untouched | 0 h | L | ✅ | done during research |
| S-B | Move Hive key out of `gateway_registry.json` into env | Registry file currently has plaintext key at line 6 | 0.2 h + registry edit | L | ◐ (registry is dead-at-runtime; removing key breaks make_gateway_registry tooling — needs operator confirm) | recommend, Milestone C |
| S-C | OS keychain (Windows Credential Manager) | `keyring` lib | 1 h | M (new dep) | ◐ (needs operator unlock) | Δ defer |
| S-D | `.env` file | python-dotenv | 0.5 h | L | ✅ | only if operator prefers; adds an ignore-file burden |

### 8.6 Rollback strategy

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| RB-A | **Env kill switches per tier** (DEFAULT) | `REASONER_ENABLED=0` → R1→R3; `SPECIALIST_ENABLED=0` → R1-only passthrough | part of T9 | L | ✅ | Milestone A |
| RB-B | Git revert to pre-plan tag | One-tag rollback of the whole feature | 0.1 h | L | ✅ | backstop |
| RB-C | Feature flag in request body (`"routing":"legacy"`) | Per-client override | 1 h | L | ✅ | Δ only if multi-client operators need it |

### 8.7 Model-choice alternatives (verified catalog IDs)

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| M-A | **Tier-2 = `z-ai/glm-5.3:thinking`** (DEFAULT) | Same family as R1, thinking variant; live PONG | 0 | L | ✅ | Milestone A |
| M-B | Tier-2 = `deepseek` reasoning line on NanoGPT | Catalog carries DeepSeek R1-distill family; would need its own probe of the exact ID | +0.3 h | L | ✅ (probe script exists) | Δ alternative: stronger math per open question 2 |
| M-C | Tier-3 = `z-ai/glm-5.3-flash-apex-abliterated` | In-family uncensored; PONG listed in catalog (not live-PONG'd) | +0.1 h (probe) | L | ✅ probe | Δ alternative if cross-provider latency felt worse |
| M-D1 | Tier-3 = `deepseek` reasoning line on NanoGPT | Catalog carries the DeepSeek R1-distill family; needs its own probe of the exact ID | +0.3 h | L | ✅ (probe script exists) | Δ fallback if `abliterated-model-large-v2` breaks |
| M-D2 | Tier-3 = `z-ai/glm-5.3-flash-apex-abliterated` (NanoGPT, in-family) | Uncensored GLM flash variant on Tier-2's provider; PONG listed in catalog (not live-PONG'd) | +0.1 h (probe) | L | ✅ probe | Δ fallback if cross-provider latency felt worse |

*Amendment 2026-10-15: the former M-D option (a LAN-hosted local Llama-3.3-
70B-abliterated) is REMOVED — local-hardware routing is retired and must
never appear in this design as a fallback, primary, or reachability
assumption. All tiers are pure cloud from here on.*

### 8.8 Escalation ordering & observability

| ID | Option | How | Effort | Risk | Scope | Verdict |
|---|---|---|---|---|---|---|
| O-A | **Refusal ⇒ R3 first, hard ⇒ R2 first, both ⇒ R2 then R3** (DEFAULT) | Hard-classified prompts escalate through the reasoner before the uncensored model; pure refusals go straight to R3 | 0.3 h | L | ✅ | Milestone A |
| O-B | Both tiers always traverse R2→R3 even for cheap refusals | Uniform ordering, simpler mental model | 0.1 h | M (pays reasoner latency+cost on every refusal) | ✅ | rejected |
| O-C | Per-tier Prometheus counters only (`diverted_total{tier=}`) | Reuse `incr()`; minimal | 0.2 h | L | ✅ | fold into T1 |
| O-D | Full per-tier audit JSONL (url, latency, verdict) sidecar | Extends evals/results audit pattern | 1 h | L | ✅ | Δ optional, Milestone C |

## 9. Scope statement — Cline CLI execution (Windows PowerShell 5.1 host)

What the implementing Cline CLI session can and cannot do. The scope markers
(✅/◐/○) used throughout §8 refer to this section.

### 9.1 In scope (fully verifiable in-session)

1. **Code edits**: `proxy_gateway.py`, `routing_patterns.py`,
   `speculative_hedge.py`, `context_formatter.py`, `providers.py`, env fields
   in `Settings`, new `evals/tier_chain_test.py`.
2. **Offline test authority**: `python -m pytest evals -q` (baseline 101 / 3
   skipped) plus `python -m py_compile` on every touched module. All §8 "✅"
   options are validated with repo stubs only.
3. **Live API probes** (tiny side effects on external services): Hive +
   NanoGPT chat PONGs with max_tokens ≤ 256; catalog queries; the §5 curl
   matrix once the gateway runs locally.
4. **Gateway process supervision for the session**: start
   `uvicorn proxy_gateway:app`, smoke endpoints, capture logs to
   `evals/results/`.
5. **Docs**: this plan, README section (T7), audit files under evals/results.
6. **Local key hygiene**: read HKCU, mint/rotate keys via Management API,
   persist to user env (already exercised: id=245160 rotated in).

### 9.2 Partial scope (needs operator hand)

1. **Key revocation of orphan id=245159** — destructive; skill rules require
   operator confirmation before any DELETE.
2. **Removing the Hive plaintext key from `gateway_registry.json`** — touches
   the `tools/hive/make_gateway_registry.py` contract; needs operator OK.
3. **Options marked ◐ in §8** — any needing system-level actions (Credential
   Manager unlock, service watchdogs).
4. **Persistent env refresh for other shells** — rotated HKCU values reach
   *new* processes only; already-running terminals/IDE servers keep stale
   values until restarted.

### 9.3 Out of scope (hard Cline CLI limits)

1. **Long-lived processes**: gateway services beyond the session, watchdog
   daemons, TUI clients (Tinfoil etc.).
2. **Hardware contingency**: the archived `refusal-interception/`
   local-ollama route is retired reference material only — this gateway never
   revives it and must never treat it as a reachable fallback.
3. **Anything needing GUI**: browser logins, provider dashboards (NanoGPT web
   console), interactive OAuth flows.
4. **Payments/subscriptions**: NanoGPT balance top-ups if a credit wall is
   hit during Tier-2/3 traffic.
5. **Reboot-persistence verification**: `SetEnvironmentVariable(User)`
   persists, but this session cannot prove post-reboot state.

### 9.4 Session protocol (how §8 options get chosen during implementation)

1. Each §8 row marked **DEFAULT** ships unless the operator overrides before
   Milestone A starts.
2. Any ◐ option waits for an explicit operator message; the CLI never assumes.
3. Every implementation step ends with a green `pytest evals -q` before the
   next item begins.
4. If a live probe contradicts the plan (e.g. Hive logprobs unsupported ⇒
   T2-D dies), the plan is amended in place with a dated note, never silently
   swapped.
5. Repo design rules stay in force: hooks/guards never raise into the request
   path; routing is never model-mediated beyond the race machinery.

## 10. Per-milestone run booklets (Cline-CLI task-shaped)

### Booklet A — core chain (~4 h)
Files: `proxy_gateway.py`, `routing_patterns.py`, `Settings` env reads.
Steps: W-A+W-D (env trio + sane defaults) → T1 (tier list +
_TERMINAL_FINISH) → T2-A (keyword scorer, τ=0.6 start) → T3-B (Hive refusal
field) → T4 (ordering per O-A) → T9 (kill switches) → O-C (counters).
Gate: `pytest evals -q` green · py_compile clean · curl matrix vs stubs ·
live PONG re-probe of all three tiers.

### Booklet B — partial + polish (~3 h)
T3 continuation (R-B) in buffer logic · T2 taxonomy extension
(REFUSAL_APOLOGY, REFUSAL_PARTIAL_RESET) · T6 (R2→R3 continuation handoff) ·
T3-E tail-window scan behind default-off `TAIL_WINDOW_SCAN=0`.
Gate: new stub tests for the continuation path; full suite green.

### Booklet C — DX (~2.5 h)
T7 (`/v1/models` tier discovery + README) · T2-D (logprob router) only if the
Hive `logprobs` precheck passes (stream chunk with `logprobs:1`, expect
`choices[0].logprobs` non-null) · T5 full heuristics · S-B (Hive key out of
the registry, operator-confirmed) · RB-B tag.
Gate: full suite green; one LIVE_STACK=1 run if the operator supplies stack
env vars.

## 11. Risks & countermeasures (Cline-CLI-specific)

| Risk | Mitigation |
|---|---|
| PowerShell 5.1 probe quirks (no `??`, Recurse timeouts >30 s) | probes ≤30 s, no PS7 syntax, `Test-Path` over Recurse |
| Rotated key drift between shells | new sessions read HKCU fresh; every probe block sets `$env:` explicitly first |
| Escalation live-fires real spend | kill switches RB-A ship before any live curl matrix; probes capped at max_tokens 256 |
| Plan/code divergence mid-milestone | every booklet ends on a suite-green gate; amendments dated in place (§9.4) |
| Orphan key id=245159 lingers | §9.2 operator revocation; reminder re-issued at Milestone A close |

