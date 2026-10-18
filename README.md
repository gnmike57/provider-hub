# reference-implementation - Interception Gateway

Production reference for the refusal-interception gateway, the speculative
hedger, and the deterministic ingress assembler described in
`docs/architecture.md`. Drop-in OpenAI-compatible proxy + Part IV assembly.

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

**Single-source invariant:** `grep -rn 'ROUTING_RE = ' reference-implementation/`
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
| `deepfrost max think` | `deepseek-ai/deepseek-v4.1-flash` | `http://gx10.ayu-sidewinder.ts.net:9314/v1` |
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
| `deepfrost` | primary | `deepseek-ai/deepseek-v4.1-flash` |
| `glmfrost` | primary | `zai-org/glm-5.3-flash` |
| `cyberfrost` | worker | `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw` |

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
| Max-think | `MAX_THINK_MIN_TOKENS` | `32768` (output floor for the max-think names) |
| Gate 7 | `NO_GO_ENABLED` | `1` (set `0` to re-open the hard no-go gate without a redeploy) |
| Gate 8 | `ATTACK_GATE_ENABLED` | `0` (opt-in: force-divert S4/S5/S6 attack requests to the specialist) |
| Divert budget | `SPECIALIST_MAX_TOKENS` | `4096` (bounds every specialist divert; `0` = unbounded) |
| Stream cap | `MAX_CONCURRENT_STREAMS` | `64` (429 + `Retry-After` when full; `0` = unlimited) |

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

