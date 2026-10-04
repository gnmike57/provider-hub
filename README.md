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
| real specialist / real primary | `evals/live_stack_test.py` (gated) |

See `corrections-ledger.md` for the B/E/F defect IDs referenced above.
