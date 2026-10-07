# corrections-ledger

Defect IDs referenced across `docs/architecture.md` and the module docstrings.
Every ID below describes a defect observed in earlier drafts of this gateway
(corpus / prior implementations) and how THIS implementation corrects it.
Mandatory-stop acceptance gates live in the spec's Gate table, not here.

## B-series (behavioural defects)

| ID | Defect | Fix here |
|---|---|---|
| B7 | Re-invoking a consumed `aiter_lines()` iterator across buffer transitions dropped packets and severed streams | `/v1/chat/completions` makes ONE pass over ONE iterator; buffered lines replay verbatim; `finish_reason` and `[DONE]` always propagated (`proxy_gateway.coordinator`) |
| B8 | Routing re-evaluated after commit, diverting on refusal text that the sovereign had legitimately produced mid-stream | Routing is evaluated ONLY in `BUFFERING`; once `PASSTHROUGH`, the stream is opaque (e2e: `test_passthrough_after_buffer_committed_is_opaque`) |
| B9 | `asyncio.gather(...)` around `AsyncClient.stream()` raised `TypeError` (async CM, not awaitable) | `open_stream` uses `build_request()` + `send(stream=True)` under an `AsyncExitStack` (`speculative_hedge`) |
| B10 | 429/503 treated as refusals and diverted, causing failover storms and billing for both branches | Explicit taxonomy in `routing_patterns.classify_status`: 408/429 retry SAME provider (never divert); 5xx retry then divert; 4xx fail fast (e2e tests pin all three) |
| B11 | Hedge fired on every request, doubling cost and halving concurrency | `should_hedge()` latency-hint gate; gateway hedges only on hints or `hedge: true` (e2e: `test_hedge_fires_only_on_latency_hint_or_force`) |
| B20 | Routing regex duplicated across modules; edits drifted | Single source in `routing_patterns.py`; `test_single_source_of_truth_invariant` greps the tree for exactly one `ROUTING_RE = ` |
| B21 | Reasoning tokens counted into the ring buffer, committing the hedge during deliberation | Reasoning forwarded (or held), NEVER counted or screened (F1); `test_reasoning_forwarded_not_counted`, `test_reasoning_held_not_counted_never_leaks_to_worker_path` |
| B22 | The hedge WORKER slot resolved its credential with a hard `"none"` default (`WORKER_API_KEY` -> `FALLBACK_API_KEY` -> `"none"`), so a NanoGPT-backed worker sent no Authorization header and every branch died with a 401 - which the commit rule HID (a clean sovereign won the race and the dead worker buffer was discarded, leaving `hedge_bad_status_total` at 0) | `HedgeSettings.worker_key` now mirrors `proxy_gateway._specialist_key()`: `WORKER_API_KEY` -> `SPECIALIST_API_KEY` -> `FALLBACK_API_KEY` -> `NANOGPT_API_KEY` -> `none` (`specialist_config_test: test_worker_key_chain_mirrors_the_specialist`) |

## E-series (environment / edge defects)

| ID | Defect | Fix here |
|---|---|---|
| E1/E2/E3 | Duplicated detection and prompt logic between the proxy and the LiteLLM callback drifted apart | Callback imports `is_routable`/`footnote` from the single source; `test_callback_imports_from_the_single_source` pins the import and forbids local `re.compile` |
| E6 | `n>1` requests bypassed the buffer entirely (one choice stream inspected) | Guards reject `n>1` up front with a 400 naming the invariant (`edge_test: test_n_gt_1_rejected`) |

## F-series (features / invariants)

| ID | Feature | Where |
|---|---|---|
| F1 | Reasoning is not content: forward for TTFT, never counted | `proxy_gateway` (BUFFER_REASONING=0 default), `speculative_hedge` |
| F3 | Single source of truth for routing logic | `routing_patterns.py` |
| F5 | Append-only audit trail (sha256 of artefact + deliverable), never raises into the request path | `ingress_assembler.audit_record` |
| F6 | Retry-on-divert: `{500,502,503,504}` retried with backoff before divert | `open_fallback` |
| F9 | Authz: `AUTHORISED_PRINCIPALS` CSV + `AUTHZ_ENFORCED`; empty+enforced = deny all | `run_guards` |
| F10 | Keep-alive poller warms the specialist; surfaced at `/healthz` + `/metrics` | `_keepalive_loop` |
| F25 | Key resolution for tests: env -> secret file -> Cline config fallback with warning | `evals/_keys.py` |
| F26 | Prometheus text metrics | `render_prometheus` at `/metrics` |
| F27 | Shutdown drains `in_flight` up to `SHUTDOWN_GRACE_S`; disconnect decrements | `_shutdown`, `edge_test: test_disconnect_drains_in_flight` |

## Verification hooks

- `test_single_source_of_truth_invariant` - one `ROUTING_RE = ` in the tree.
- `test_status_taxonomy` - the B10 table pinned line by line.
- `test_passthrough_after_buffer_committed_is_opaque` - B8.
- `test_specialist_503_retried_then_error_chunk` - F6 + breaker interaction.
- `test_disconnect_drains_in_flight` - F27 against a real uvicorn server.
