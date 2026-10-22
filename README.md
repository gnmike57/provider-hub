# provider-hub - Interception Gateway

Production reference for the refusal-interception gateway, the speculative
hedger, and the deterministic ingress assembler described in
`refusal-interception/ARCHITECTURE.MD`. Drop-in OpenAI-compatible proxy + Part IV assembly.

## Results (2026-10-04, Python 3.12, offline CI)

| Suite | Concern | Status |
|---|---|---|
| `evals/routing_probe.py` | detection / formatter / assembler / Tier 2 | 20 passed |
| `evals/routing_test.py` | authz (F9) / Tier 4 / Gate 7 no-go (scope, diagnostics, kill switch) | 12 passed |
| `evals/attack_gate_test.py` | Gate 8 forced divert (FP/TP corpus, opt-in, in-flight, audit, multi-turn, budget) | 126 passed |
| `evals/callback_test.py` | LiteLLM callback / single-source invariant | 5 passed |
| `evals/hedge_test.py` | speculative dual-dispatch (B9/B11/F1) | 4 passed |
| `evals/e2e_gateway_test.py` | streaming ring buffer (B7/B8/B10) | 11 passed |
| `evals/assembly_test.py` | `/v1/execute` / audit / retry | 8 passed |
| `evals/edge_test.py` | tools / n>1 / disconnect / concurrency / metrics / stream cap | 9 passed |
| `evals/live_stack_test.py` | real specialist (skipped without `LIVE_STACK=1`) | skipped by design |

Run everything offline:

```bash
bash run_all_tests.sh                     # auto-detects ../.venv
# PowerShell equivalent:
python -m pytest evals/ -p no:warnings -q
```

## Layout

| Module | Responsibility | Key exports |
|---|---|---|
| `routing_patterns.py` | **Single source of truth for routing logic** (F3), dependency-free | `is_routable`, `should_hedge`, `tier2_decision`, `normalise`, `classify_status`, `is_no_go` |
| `context_formatter.py` | Format context before the specialist sees it | `format_messages`, `DEFAULT_SYSTEM`, `CYBER_SYSTEM`, `assert_clean` |
| `ingress_assembler.py` | Deterministic (non-LLM) merge + audit records + GBNF grammars | `assemble`, `validate_artifact`, `audit_record`, `SLOT`, `grammar_for` |
| `proxy_gateway.py` | FastAPI app: buffering, routing, metrics, endpoints, breaker | `app`, `fallback_stream`, `open_primary`, `open_fallback` |
| `speculative_hedge.py` | Speculative dual-dispatch (B9/B11 fixes) | `hedge_stream` |
| `litellm/routing_callback.py` | Non-streaming repair inside LiteLLM | `RoutingFootnoteCallback` |

**Single-source invariant:** `grep -rn 'ROUTING_RE = ' .` from this folder
returns exactly one hit (`routing_patterns.py`), and the callback test pins it.

## Running

```bash
# gateway on :9000
uvicorn proxy_gateway:app --host 127.0.0.1 --port 9000

# or python -m uvicorn from this directory
python -m uvicorn proxy_gateway:app --host 127.0.0.1 --port 9000
```

## Max-reasoning DeepFrost / GLMFrost (Hive primary)

`deepfrost max think` and `glmfrost max think` are the **max-reasoning**
versions of `deepfrost` / `glmfrost`. They stay on the **primary slot**
(thehive.ai keys) with the SAME Hive upstream ids — the gateway just injects
`reasoning_effort=max` (plus the other thinking-knob conventions) server-side
and raises the token floor. When the primary refuses, the existing divert
machinery routes to the **NanoGPT `abliteration-ai/abliterated-model-large-v2`**
specialist (worker slot), exactly like a plain Frost name.

| Alias | Hive upstream model | Endpoint |
|---|---|---|
| `deepfrost max think` | `deepseek-ai/deepseek-v4.1-flash-1017` | `http://gx10.ayu-sidewinder.ts.net:9314/v1` |
| `glmfrost max think` | `zai-org/glm-5.3-flash` | `http://gx10.ayu-sidewinder.ts.net:9315/v1` |

Max-reasoning requests never race the speculative hedge, get a 32768-token
floor (`MAX_THINK_MIN_TOKENS`), and are counted in `max_think_total`.

## Wiring the CYBER-FROST specialist (gx10 / DGX Spark)

CYBER-FROST-3.8-EXL3-SAGE-3.87bpw is served by TabbyAPI on the Spark
(recipe `exllamav3-tabby`, fork pin `047ce72`, DEPLOY.md). Defaults verified
against the pack's own serving kit - do not send a low temperature by hand:
the pack's sampler overrides (temperature 1.0, top_k 20, top_p 0.95) apply
server-side, and low temperature collapses draft acceptance (DEPLOY.md,
"Sampling"). Override deliberately via `SPECIALIST_TEMPERATURE` if a benchmark
needs greedy.

```bash
# gateway env
FALLBACK_API_URL=http://gx10.local:8900/v1/chat/completions
FALLBACK_API_KEY=none
FALLBACK_MODEL=CYBER-FROST-3.8-EXL3-SAGE-3.87bpw
KEEPALIVE_URL=http://gx10.local:8900/v1/models
AUDIT_LOG=C:\logs\interception_audit.jsonl

# optional: domain activation for the SAGE fine-tune
SPECIALIST_SYSTEM_MODE=domain
```

`SPECIALIST_SYSTEM_MODE=domain` is honoured on every specialist surface: the
refusal/capacity diverts and `/v1/execute` both put `CYBER_SYSTEM` in front of
the specialist; `neutral` (default) keeps the generic execution-engine framing
(`evals/specialist_system_test.py` pins both).

### Specialist on NanoGPT (uncensored fallback)

The refusal-interception specialist can run on the operator's NanoGPT account
instead of the local gx10 hub. Point the worker slot at NanoGPT and let the
credential resolve from the Windows environment (`NANOGPT_API_KEY`) - no second
copy of the secret to manage:

```powershell
[Environment]::SetEnvironmentVariable('SPECIALIST_API_URL', 'https://nano-gpt.com/api/v1/chat/completions', 'User')
[Environment]::SetEnvironmentVariable('SPECIALIST_MODEL', 'abliteration-ai/abliterated-model-large-v2', 'User')
# NANOGPT_API_KEY already holds the key; SPECIALIST_API_KEY overrides it if set.
```

Resolution: `SPECIALIST_API_URL/MODEL` override `FALLBACK_API_URL/MODEL`; the
key is `SPECIALIST_API_KEY` -> `FALLBACK_API_KEY` -> `NANOGPT_API_KEY` -> `none`
(`evals/specialist_config_test.py`). Verify live (forced-divert path, no primary
spend): `python tools/hive/verify_specialist_live.py`.

#### Two independent NanoGPT slots (2026-10-16)

The **specialist** (divert target, `proxy_gateway.Settings`) and the **worker**
(speculative hedge branch, `speculative_hedge.HedgeSettings`) can be different
models on the same NanoGPT endpoint. The gateway reads `SPECIALIST_MODEL`; the
hedge reads `WORKER_MODEL`, so the two never collapse onto each other:

| Slot | Consumer | Variable | Value |
|---|---|---|---|
| Worker (hedge branch) | `speculative_hedge.py` | `WORKER_MODEL` | `xiaomi/mimo-v2.6-flash-abliterated` |
| Specialist (divert) | `proxy_gateway.py` | `SPECIALIST_MODEL` | `abliteration-ai/abliterated-model-large-v2` |

```powershell
[Environment]::SetEnvironmentVariable('WORKER_API_URL', 'https://nano-gpt.com/api/v1/chat/completions', 'User')
[Environment]::SetEnvironmentVariable('WORKER_MODEL', 'xiaomi/mimo-v2.6-flash-abliterated', 'User')
```

Both keys resolve through the same chain (`WORKER_API_KEY`/`SPECIALIST_API_KEY`
-> `FALLBACK_API_KEY` -> `NANOGPT_API_KEY` -> `none`), so the single
`NANOGPT_API_KEY` credential serves both. Verify the split offline and live:

```bash
python tools/hive/verify_slot_split.py         # resolution: both slots, no network
python tools/hive/verify_slots_live.py         # live PONG on each slot's own model
python tools/hive/verify_hedge_worker_live.py  # refusing sovereign -> mimo worker divert
```

Grammar enforcement (spec section 4): `plan.output_grammar_type == "json_sarif"`
attaches `grammar_string` (GBNF) to the specialist payload automatically.

## Frost names & max-think

The gateway publishes the operator's specialised systems as **model ids** (the
Frost names), so one endpoint can address any of them and `GET /v1/models`
lists them for Cline/OpenCode pickers (`evals/frost_alias_test.py`):

| Name | Slot | Upstream id |
|---|---|---|
| `deepfrost` | primary | `deepseek-ai/deepseek-v4.1-flash-1017` |
| `glmfrost` | primary | `zai-org/glm-5.3-flash` |
| `cyberfrost` | worker | `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw` |
| `frost-general` | primary | the slot's current default (follows `/v1/switch`) |

`cyberfrost` dispatches to `FROST_WORKER_API_URL` (the gx10 hub), **not** to
the specialist binding: `SPECIALIST_API_URL` repoints the DIVERT target at the
uncensored specialist (NanoGPT), and a `CYBER-FROST` id on that URL is a
guaranteed 400 (measured live). When `FROST_WORKER_API_URL` is unset the
worker names fall back to the fallback slot's URL (previous behaviour). A
transport failure on the frost worker (gx10 down) retries then diverts to the
specialist like any primary.

`frost-general` carries no baked-in upstream id: it addresses the primary
slot's CURRENT default model, so the advertised name is addressable instead of
passing through to Hive as a literal (which 400s "Invalid Model Name").

The **max-think** variants (`deepfrost max think` / `glmfrost max think`, also
`*-max-think`) are the SAME thinking primaries with reasoning pushed to the
maximum. The knobs are injected server-side (never trusted from the body):
`reasoning_effort=max`, `reasoning.effort=max`, `enable_thinking`, plus every
known convention (unknown fields are ignored by OpenAI-compatible upstreams).
Two deliberate deviations from the plain names:

* **No speculative race.** `COMMIT_TOKENS=10` would commit the flash worker
  while the deep model is still deliberating (reasoning tokens are invisible to
  the commit counter), so a `hedge: true` on a max-think name is ignored.
* **Raised output floor.** `MAX_THINK_MIN_TOKENS` (default `32768`) raises both
  `max_tokens` and `max_completion_tokens`; Hive's models spend the budget on
  hidden reasoning first, so the 4096 default can die mid-deliberation with
  `finish_reason=length` and zero content. A higher client `max_tokens` still
  wins (`evals/max_think_test.py`).

## Hub model matrix (NanoGPT / Abliteration.ai)

Eight operator-addressable aliases select an external provider, an upstream
model id, and a reasoning mode directly - bypassing the primary/worker slots.
`resolve_hub_alias` runs before Frost resolution, so a hub alias always wins;
`GET /v1/models` lists all eight after the Frost names:

| Alias | Provider | Upstream id | Max |
|---|---|---|---|
| `DeepMaxNano` / `DeepNano` | NanoGPT | `deepseek/deepseek-v4.1-flash` | yes / no |
| `GLMMaxNano` / `GLMNano` | NanoGPT | `zai-org/glm-5.3-flash` | yes / no |
| `DeepMaxAblit.ai` / `DeepAblit.ai` | Abliteration.ai | `abliterated-model-large` | yes / no |
| `GLMMaxAblit.ai` / `GLMAblit.ai` | Abliteration.ai | `abliterated-model-large-v2` | yes / no |

* Names normalise (case, `-`/`_`, spaces), so `deep-max-nano` also resolves.
* `deep`/`glm` name the matrix SLOT, resolved per provider against each live
  catalog (2026-10-18): Abliteration.ai carries no DeepSeek model, so the
  `deep` slot maps to their other frontier reasoning model (prev-gen GLM-4);
  `glm` maps to their GLM-5.3 flagship, confirmed by their pricing page and the
  model's own self-report.
* `Max` aliases get the same server-side knob set as the Frost max-think names
  (reasoning pushed to maximum, `MAX_THINK_MIN_TOKENS` output floor) and never
  race the hedge: the alias is an explicit provider selection, so a worker
  commit could otherwise answer on a provider the client did not address.
  `/v1/models` advertises every hub model as `hedged: false` to match.
  On Abliteration.ai the runtime-control knobs (`enable_thinking`,
  `chat_template_kwargs`, `thinking`) are trimmed - their API reserves those
  for itself (400 `provider_control_forbidden` / 422, measured live); the
  OpenAI-style effort knobs and the token floor remain.
* Credentials: `NANOGPT_API_KEY` (shared with the specialist slot) and
  `ABLITERATION_API_KEY`; URLs default to
  `https://nano-gpt.com/api/v1/chat/completions` and
  `https://api.abliteration.ai/v1/chat/completions` (`NANOGPT_API_URL` /
  `ABLITERATION_API_URL` override). `launch_frost_hub.ps1` pins both keys.
* Failure semantics: 4xx from a hub provider fails fast with a visible
  upstream error; 5xx/transport retries then diverts to the specialist like
  any primary.
* Payload shape: hub requests carry a single token cap (`max_tokens`).
  Abliteration.ai rejects `max_tokens` + `max_completion_tokens` together
  (measured live), while Hive needs the latter; `max_tokens` is the one
  field every provider in the matrix accepts.

## Configuration surface (env vars)

| Group | Variables | Default |
|---|---|---|
| Primary | `PRIMARY_API_URL/KEY/MODEL` | OpenAI `gpt-4o` |
| Specialist | `FALLBACK_API_URL/KEY/MODEL` | local vLLM `:8000`, Qwen3.6-35B |
| Buffer | `BUFFER_CONTENT_TOKENS`, `BUFFER_REASONING` | `25`, `0` (reasoning never counted) |
| Retry | `MAX_ATTEMPTS`, `RETRY_BASE_DELAY`, `FALLBACK_MAX_ATTEMPTS` | `3`, `0.5`, `3` |
| Assembly | `ASSEMBLY_ENABLED`, `ORCHESTRATOR_MODEL` | `1`, = primary |
| Audit | `AUDIT_LOG` | empty (stdout only) |
| Governance | `AUTHORISED_PRINCIPALS`, `AUTHZ_ENFORCED`, `KEEPALIVE_URL`, `KEEPALIVE_INTERVAL_S` | off / `0` / - / 240 |
| Shutdown | `SHUTDOWN_GRACE_S` | `10` |
| Hedge | `SOVEREIGN_*`, `WORKER_*`, `COMMIT_TOKENS` | mirrors primary/fallback, `25` |
| Specialist | `SPECIALIST_TEMPERATURE`, `SPECIALIST_SYSTEM_MODE` | unset (server defaults), `neutral` |
| Specialist binding | `SPECIALIST_API_URL/KEY/MODEL` (override `FALLBACK_*`); key falls back to `NANOGPT_API_KEY` | local vLLM `:8000`, Qwen3.6-35B (or NanoGPT specialist) |
| Frost worker | `FROST_WORKER_API_URL/KEY` | `""` (unset: the cyberfrost names use the fallback slot's URL) |
| Max-think | `MAX_THINK_MIN_TOKENS` | `32768` (output floor for the max-think names) |
| Gate 7 | `NO_GO_ENABLED` | `1` (set `0` to re-open the hard no-go gate without a redeploy) |
| Gate 8 | `ATTACK_GATE_ENABLED` | `0` (opt-in: force-divert S4/S5/S6 attack requests to the specialist) |
| Divert budget | `SPECIALIST_MAX_TOKENS` | `4096` (bounds every specialist divert; `0` = unbounded) |
| Stream cap | `MAX_CONCURRENT_STREAMS` | `64` (429 + `Retry-After` when full; `0` = unlimited) |
| Logprob presignal | `LOGPROB_PRESIGNAL`, `LOGPROB_TOPK` | `0` (opt-in: scan the helm's content top-logprobs for refusal markers and divert *before* the text completes), `5` |
| Stickiness | `HELM_STICKINESS`, `HELM_STICKY_TURNS` | `1`, `3` (after a divert, the next N turns of the same conversation go straight to the terminal without calling the helm; `0` = per-request decisions) |
| Ablit catalog hide | `HIDE_ABLIT_MODELS` | `1` (TEMP 2026-10-22: `/v1/models` drops every id starting with "ablit" — the two ABLITV2L-helm chains + abliterated registry ids; ablit chain terminals keep working; `0` = full catalog) |
| Live credit tests | `LIVE_CREDITS`, `LIVE_HUB_URL`, `LIVE_HUB_KEY` | `0` (`evals/live_models_test.py` spends real Hive/NanoGPT credits across every non-ablit surface + the benign→offensive→benign chain lifecycle when `1`) |
| Usage metering | — | usage events prefer the upstream `usage` object (prompt/completion tokens); without one, only content deltas are estimated (~4 chars/token) — never the SSE envelope |

Gate 8 scans the **unanswered span**: the client-controlled turns
(`system`, `developer`, `user`) after the most recent assistant reply. An ask
split across consecutive user turns is still caught, but the divert is not
sticky — once the model has answered, the thread reverts to normal routing,
and only a fresh unanswered ask re-trips the gate. `assistant`/`tool` content
is never scanned: it is model output, not a client ask.

## Where the tests live

| Concern | Suite |
|---|---|
| detection / formatter / assembler / Tier 2 | `evals/routing_probe.py` |
| authz / Tier 4 | `evals/routing_test.py` |
| Gate 8 attack-content forced divert | `evals/attack_gate_test.py` |
| LiteLLM callback | `evals/callback_test.py` |
| hedging | `evals/hedge_test.py` |
| streaming gateway | `evals/e2e_gateway_test.py` |
| `/v1/execute`, audit, retry | `evals/assembly_test.py` |
| tool calls, n>1, disconnect, concurrency, metrics | `evals/edge_test.py` |
| `SPECIALIST_SYSTEM_MODE` / `CYBER_SYSTEM` on both specialist surfaces | `evals/specialist_system_test.py` |
| Frost names as model ids / `/v1/models` | `evals/frost_alias_test.py` |
| max-think knobs, no-race, token floor | `evals/max_think_test.py` |
| hedge output cap (`max_completion_tokens`) | `evals/hedge_budget_test.py` |
| real specialist / real primary | `evals/live_stack_test.py` (gated) |

See `corrections-ledger.md` for the B/E/F defect IDs referenced above.

## This folder - project separation (2026-10-07)

`provider-hub/` is now its own project folder, extracted from `projects/ufo`
branch `feat/provider-hub` via
`git subtree split --prefix=ufo/reference-implementation` (254 commits of
history preserved; tip `3d5653e`). That prefix's contents are this repo's
root, so every relative path in `evals/` still resolves: `HERE.parent.parent`
is this folder, which is where `proxy_gateway.py` lives.

Suites added on the provider-hub branch (beyond the table above):

* `evals/results/context_handoff_test.py` (note: `results/`, not `evals/` -
  `RESULTS = HERE`, so its artifacts land beside it):
  `direct` (live - resolve CYBER-FROST from the hub catalog, then call it
  straight: no divert, no footnote), `wire` (offline, 15 assertions on the
  divert anatomy), `loop` (live - 6-turn context-growth proof: canaries
  planted early must come back verbatim), `deep` (handoff at ~message 20).
* `evals/results/handoff_matrix.py`: per-primary matrix measuring
  refusals detected -> handoffs started -> specialist acquired -> identity
  overrides, one row per candidate primary.

Result artifacts live in `evals/results/` (`context_direct.json`,
`context_wire.log`, `context_loop.json`, `handoff_matrix.json`, audit jsonl).

### Network (measured 2026-10-07)

Use the tailnet hub - `http://100.67.13.78:4000` (or `cyber.local:4000`).
This laptop was on `192.168.12.0/24` while gx10's LAN interface is
`192.168.4.103/22`: different subnet, so `gx10.local` (mDNS) and the
`gx10-lan` ssh alias are both dead from here. Tailscale works anywhere.

### Budget rule for live phases

CYBER-FROST thinks always-on (the hub ignores `enable_thinking:false`), so a
compound prompt can spend the whole `max_tokens` budget on thinking and
return **HTTP 200 with an empty content stream**. `loop` therefore uses
`max_tokens=2400`. If a live phase returns empty content, raise the budget
before suspecting the gateway.

## Stage colour annotations (operator UX, 2026-10-21)

The gateway emits an SSE **comment line** at every stage transition so a client
UI can restyle the lettering by the model *currently replying* - a subtle
near-white tint plus a faint glow hue:

```
: gw-stage helm zai-org/glm-5.3-flash tint=#edf4fd glow=#3b82f6
data: {...}                       <- the GLM/DeepSeek reasoning helm
: gw-stage middle deepseek-ai/deepseek-v4.1-flash-1017 tint=#f3effb glow=#8b5cf6
data: {...}                       <- the no-reasoning secondary (ladder)
: gw-stage terminal abliterated-model-large-v2 tint=#fdf0f2 glow=#f43f5e
data: {...}                       <- the Abliterated V2 Large terminal
```

* Subtle palette (single source: `routing_patterns.STAGE_STYLES`):
  `helm` faint **blue**-white, `middle` faint **violet**-white, `terminal`
  faint **rose/red**-white (REDHANDS), `hedge` faint **amber/orange**-white.
* A UI consumes `tint=` as the (slightly-off white) font colour and `glow=`
  as the faint text-shadow hue, e.g. CSS:
  `color: #edf4fd; text-shadow: 0 0 8px rgba(59,130,246,0.35);`
* Comment lines (`: ...`) are part of the SSE spec: standard OpenAI-style
  consumers that parse only `data:` lines ignore them, so the verbatim
  chunk relay (B8) is untouched.
* Every `data:` chunk also carries the answering model id in its `model`
  field, and every specialist stage ends with a provenance footnote naming
  the model that answered.


## Skill memory (the models' procedural memory, 2026-10-21)

A model that completes something non-obvious ends its reply with one line
`[[GW-SKILL: kebab-name]] what-was-learned`. The gateway captures it
(`skills_memory.py`, idempotent by name, LRU cap 200) and injects the
relevant learned skills into the stage prompts of later requests - the
system starts smarter every run. Rescue and contract-re-ask events capture
automatic stubs (`auto-*`): the "did not come naturally" moments.
Metrics: `skills_learned_total`, `skills_injected_total`. The client's own
system turn always wins. `SKILL_MEMORY=0` restores the bare behaviour;
protocol markers never ship regardless.


## Loki completion layer (2026-10-21)

Multi-item asks run under a **completion contract**: the reply opens with
`[[GW-CHECKLIST]]` plus a numbered list of every requirement, and the
gateway's lexical coverage judge verifies each item against the answer
text. An uncovered item is an *incomplete answer, never a shippable
one*: it triggers one repair divert (`tier3_incomplete`) - the ladder
re-answers with the failing items named in the continuation context, so
the client gets a complete reply instead of a half-done one. The judge
fires at every watered-down checkpoint (presignal recovery, buffer
commit, stream end) and only when the reply carries the marker (opt-in
by marker presence, no false positives on plain replies). The
`[[GW-CHECKLIST]]` token itself never ships - it is stripped on every
output path (the numbered requirements stay visible as the verification
record). `COMPLETION_CONTRACT=0` restores the bare behaviour. Metrics:
`completion_reask_total`, `completion_verified_total`.
REDHANDS law 8 codifies the same doctrine for the offense persona:
*finish or fail loudly - every checklist item verified or the failure
named.*

**Evidence receipts.** In evidence mode (an `AUDIT_LOG` path is set),
every `_finalize` terminal writes one secret-free JSON receipt to
`gw_receipts/<request_id>.json`: facts (reason, model, content tokens,
SHA-256 of the delivered text) and assessments (watered-down verdict,
presignal, uncovered checklist items). Fire-and-forget - a receipt
failure never breaks the stream.

**Engagement continuity.** `/v1/execute` accepts an optional
`engagement_id`: the plan and artifact digest persist to
`execute_state/<engagement_id>.json`, and a follow-up request under the
same engagement seeds the planner with the prior state so work *resumes*
instead of redoing (the planner prompt gains `PRIOR ENGAGEMENT STATE`).


## Computer use, visually verified (2026-10-21)

`POST /v1/computer` runs an Agent TARS browser task with
**verify-each-act**. Body: `{"instruction", "url"?, "verify"?,
"headless"?}`; authed via `X-Admin-Key` (the launcher pins
`COMPUTER_USE_ENABLED=1`; the endpoint 501s when off). The runner
(`tars/computer_task.mjs`) drives the browser, screenshots the result
state, captions it via the gx10 captioner chain
(`gemma3-27b-heretic-vl` first), and asks the V2 Large model to judge
the caption against the `--verify` expectation: *yes* proceeds, *no*
retries the action ONCE, twice-fail aborts with both captions recorded.
The response is `{"ok","result","verified","steps":[{"action",
"caption","verdict"}]}`; errors return 502 with a 300-char detail.
`COMPUTER_TASK_TIMEOUT` bounds the run (default 120 s). REDHANDS law 9
codifies it: *eyes on the target - every computer action is verified by
screenshot before the next; an unverified action never counts as done.*
The suite exercises the loop hermetically via `--selftest` (no browser,
no network); the live vuln-lab probe (nginx alias traversal :8102) is
the opt-in gate.

## HACKING_MODE, palettes, and the 4th chain (2026-10-21)

- **HACKING_MODE=1** (launcher) arms the full authorized-red-team posture in
  one switch: `AUTHORIZED_FRAME`, `UNCENSORED_MIDDLE`, `ESCALATION_MIDDLE`,
  `SKILL_MEMORY`, `COMPLETION_CONTRACT`.
- **STAGE_PALETTE=green** selects the green lettering palette for the stage
  tints (`routing_patterns._PALETTES`); default stays blue/violet/rose/amber.
- **GLMMAX>ABLIT-UNC>ABLITV2L** is the 4th constellation chain: GLM max helm
  -> *uncensored* Abliterated Large middle -> Abliterated V2 Large terminal
  (a helm refusal meets a brain that almost never refuses before the V2
  terminal burns).
- **Team bus**: `BUS_ENABLED=1` + `BUS_API_KEY` expose `/bus/announce`
  (peer registry, 90 s TTL) and `/bus/claim` (hand an instruction to a peer
  hub's /v1/chat/completions); `deploy/nginx/team-bus.conf` is the fleet
  front door. **Fan-out**: `/v1/execute` decomposes into `subtasks` and runs
  FANOUT_MAX_PARALLEL specialists concurrently.

## T-E wave: AUTO_TEAM + /v1/verify (2026-10-23)

**AUTO_TEAM** (`AUTO_TEAM=1`, default `0`) decomposes multi-item chats. When
a `/v1/chat/completions` ask is multi-item (`routing_patterns.is_multi_item_ask`
>= 2 - a marked list, >= 2 ordinals, or >= 2 imperatives) AND the request
would otherwise take the normal single-model chat path (forced diverts, RACE,
CONDUCTOR, and SUSTAINED routes have their own machinery and stay untouched),
the gateway runs the existing CONDUCTOR planner + fan-out instead: one extra
planning hop, then the subtask specialists answer in parallel
(`FANOUT_MAX_PARALLEL`-bounded), the sections assemble, and the completion
contract verifies coverage before the deliverable streams as SSE. Single-
question chats skip the fan-out even when it is on (one hop of latency only
where decomposition helps); tool-call requests keep the plain path. Off by
default, so existing traffic is byte-for-byte unchanged. Metrics:
`auto_team_total` (separate from the chain-6 `conductor_total`).

**`POST /v1/verify`** (RARV-C) is the admin-authed verification surface
(`X-Admin-Key`, 403 fail-closed like every admin endpoint once `ADMIN_API_KEY`
is set). Body: `{"instruction": str, "verify_checklist"?: [str, ...]}` -
an explicit checklist is the operator's fixed contract (the planner then only
decomposes subtasks). The endpoint:

1. **plans** - a conductor-style planner decomposes the instruction into
   blind subtasks (plan failure degrades to the single whole-instruction
   subtask - never a client error);
2. **executes** - the existing fan-out specialists answer the subtasks
   (routine hops on the cheap blind stage, `nasty` hops on the terminal
   under REDHANDS);
3. **judges** - the `[[GW-CHECKLIST]]` completion-coverage machinery scores
   every checklist item against the evidence (answers only, not headers);
4. **council** - two independent cheap reviewer calls must AGREE on
   `VERIFIED`; on the constellation flashes they ride DIFFERENT models
   (GLM + DeepSeek) on the same provider binding; disagreement or an
   unreachable reviewer fails closed (`verify_council_disagree_total`);
5. **receipt** - appends one tamper-evident line to
   `gw_receipts/verify_receipts.jsonl` (beside the audit log in evidence
   mode, else beside the working directory): FACTS (the diff-relevant
   record - instruction/subtask/artifact digests, checklist, models - never
   key material) separated from ASSESSMENTS (coverage, uncovered items,
   reviewer verdicts, the final verdict), sealed with `sha256` over the
   canonical facts chained onto the previous line's seal, so any later edit
   to a fact or reordering breaks the chain (`_verify_receipt_chain_valid`
   re-proves the ledger). A receipt failure never kills the verdict
   (`verify_receipt_failed_total`).

The verdict envelope returns
`{verified, coverage_ok, uncovered, checklist, subtasks, evidence, council,
receipt}` (plus the `gaps` / `requirements` / `receipt_id` task-contract
aliases); `verified` is true only when coverage passed AND both council
reviewers said `VERIFIED` in agreement. Metrics: `verify_total`,
`verify_verified_total`, `verify_gaps_total`,
`verify_council_disagree_total`, `verify_receipt_failed_total`.
