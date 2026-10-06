# reference-implementation - Interception Gateway

Production reference for the refusal-interception gateway, the speculative
hedger, and the deterministic ingress assembler described in
`docs/architecture.md`. Drop-in OpenAI-compatible proxy + Part IV assembly.

## Results (2026-10-04, Python 3.12, offline CI)

| Suite | Concern | Status |
|---|---|---|
| `evals/routing_probe.py` | detection / formatter / assembler / Tier 2 | 20 passed |
| `evals/routing_test.py` | authz (F9) / Tier 4 / Gate 7 no-go | 7 passed |
| `evals/callback_test.py` | LiteLLM callback / single-source invariant | 5 passed |
| `evals/hedge_test.py` | speculative dual-dispatch (B9/B11/F1) | 4 passed |
| `evals/e2e_gateway_test.py` | streaming ring buffer (B7/B8/B10) | 11 passed |
| `evals/assembly_test.py` | `/v1/execute` / audit / retry | 8 passed |
| `evals/edge_test.py` | tools / n>1 / disconnect / concurrency / metrics | 7 passed |
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

Grammar enforcement (spec section 4): `plan.output_grammar_type == "json_sarif"`
attaches `grammar_string` (GBNF) to the specialist payload automatically.

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

## Where the tests live

| Concern | Suite |
|---|---|
| detection / formatter / assembler / Tier 2 | `evals/routing_probe.py` |
| authz / Tier 4 | `evals/routing_test.py` |
| LiteLLM callback | `evals/callback_test.py` |
| hedging | `evals/hedge_test.py` |
| streaming gateway | `evals/e2e_gateway_test.py` |
| `/v1/execute`, audit, retry | `evals/assembly_test.py` |
| tool calls, n>1, disconnect, concurrency, metrics | `evals/edge_test.py` |
| `SPECIALIST_SYSTEM_MODE` / `CYBER_SYSTEM` on both specialist surfaces | `evals/specialist_system_test.py` |
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

* `evals/context_handoff_test.py`:
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

