# Plan: Provider Hub — dynamic primary selection for the interception gateway

> **SCOPE AMENDMENT (2026-10-22, line-by-line verification pass).** This plan
> was written against the **ufo workspace** (`…\ufo\ufo`, branch
> `feat/provider-hub` @ 8c74bb5, code under `reference-implementation/`) — all
> of which is true THERE, not in this repo. In provider-hub the modules live
> at the repo root and the plan is a **design record, largely superseded**:
> T2 landed differently (`speculative_hedge.hedge_stream(messages, *,
> request_id, settings, client, tools, tool_choice, escalate)` — the worker
> is still reduced to `[system, last user]` by design, and only tools are
> forwarded); `/v1/models` serves the constellation chains, not a registry
> union; T4 (`admin_ui.py` / `/admin/api/*`) and T5's referenced docs
> (`docs/run_speculative_gateway.md`, `docs/integrations/opencode_gemma27b.md`)
> were never built here (the Control Room at `/admin/models` is a different
> surface). The registry work that DID land: `providers.py` `upsert_provider` /
> `set_default` / `catalog` / `masked` / `load_registry` + `model_switch.py`.

Base: `main` @ 8c74bb5. Branch: `feat/provider-hub`.
Workspace root: `C:\Users\lnxzf\Desktop\projects\ufo\ufo`.
All code under `reference-implementation/`; tests under `reference-implementation/evals/`.
Venv python: `..\.venv\Scripts\python.exe` (from `reference-implementation/`).
Test runner: `..\.venv\Scripts\python.exe -m pytest evals/<file>.py -p no:warnings -q` run
with CWD=`reference-implementation/`.

**Commit discipline:** commit ONLY files your task touched (`git add <explicit paths>`).
There are pre-existing unrelated dirty files on main — never stage them.

## Goal

Turn `proxy_gateway.py` (:9000) into a provider-agnostic hub:
- A persistent registry of providers (Anthropic, OpenAI, xAI/Grok, OpenRouter,
  the local hub, …), each with base URL, wire API, stored key, model list.
- An admin web page reachable on the LAN (e.g. `http://settings.local:9000/admin`)
  where a user adds a provider (paste API key, discover+pick models), and selects
  the default primary + worker.
- `POST /v1/chat/completions` resolves `model` against the registry:
  1. explicit `provider:model`, 2. unique registered model name, 3. default primary.
- `GET /v1/models` returns the union of registered models (OpenAI shape) so
  Cline/OpenCode model pickers work.
- Two wire adapters: `openai` (passthrough) and `anthropic` (Messages API,
  x-api-key auth, SSE event translation). Normalized internal event stream so
  refusal-screening, hedge, and footnote logic stay provider-blind.
- F9 fix: the hedge path forwards `tools`, `tool_choice`, `temperature`,
  `max_tokens` and the FULL messages list to BOTH branches.
- BYOK: if a provider has no stored key, forward the client's `Authorization`.
- Back-compat: with no registry file, synthesize the registry from
  `PRIMARY_*`/`FALLBACK_*` env; existing behavior and `evals/hedge_test.py` keep working.

## Tasks

### T1 — providers.py completion + unit tests
Finish `reference-implementation/providers.py` (already written: docstring,
`Event`, `Provider`, `Target`, `mask_key`, `request_headers`, `_strip_chat_suffix`,
`_legacy_env_providers`, `Registry.__init__/reload/save`). Add:
- `Registry.upsert_provider(pid, api, base_url, key=None, models=None)` — `key=None`
  or `""` keeps stored key; `save()` after.
- `Registry.delete_provider(pid)` — removes provider; prunes defaults pointing at it.
- `Registry.set_default(role, pid)` — role in {"primary","worker"}; KeyError on unknown.
- `Registry.catalog()` — OpenAI list entries: {id, object:"model", created:0, owned_by:<pid>}.
- `Registry.masked()` — dict with providers (key masked, has_key, models, chat_url),
  defaults, `from_env` flag (`self._mtime == 0.0`).
- `Registry.resolve(model, role="primary") -> Target` with 3-step precedence.
- `load_registry(path="")` factory.
- Adapters:
  - `build_upstream_request(target, body) -> dict` — api=="openai": copy model
    (→ upstream_model), messages, stream, and tools/tool_choice/temperature/
    max_tokens when present. api=="anthropic": Messages payload — hoist system role
    messages to top-level `system` (join with "\n\n"); assistant message
    `tool_calls` → content blocks {type:tool_use, id, name, input(parsed args json)};
    tool-role messages → user message with tool_result blocks
    {type:tool_result, tool_use_id, content} (group consecutive tool messages);
    `tools` → [{name, description, input_schema:parameters}]; `tool_choice`:
    "auto"→{"type":"auto"}, "none"→{"type":"none"}, "required"→{"type":"any"},
    function-style → {"type":"tool","name":X}; `max_tokens` mandatory
    (body value or 4096); temperature/top_p passthrough; `stream` copied.
  - `anthropic_finish_reason(stop_reason) -> str` — end_turn→stop, tool_use→tool_calls,
    max_tokens→length, stop_sequence→stop, else passthrough.
  - `normalize_stream(api, response) -> AsyncGenerator[Event]` parsing SSE.
    openai: choices[0].delta.content → content; delta.reasoning_content → reasoning;
    delta.tool_calls entries → Event("tool_call", index=tc["index"], tool_id, name,
    args); finish_reason → Event("finish"); usage → Event("usage"); error payload →
    Event("error", error=...); skip [DONE] and blank lines.
    anthropic: message_start → usage(input_tokens); content_block_start type=tool_use
    → Event("tool_call", index, tool_id, name); content_block_delta text_delta →
    content; input_json_delta → tool_call args delta; thinking_delta → reasoning;
    message_delta → Event("finish", finish=anthropic_finish_reason(...)) +
    usage(output_tokens); type=error → Event("error"); content_block_stop /
    message_stop / ping ignored.
  - `to_openai_chunk(ev, model, stream_id, created=0) -> bytes | None` — content/
    reasoning/tool_call → delta chunks; finish → chunk with finish_reason; usage →
    None; error → `data: {"error": {"message": ...}}`.
- Tests `evals/providers_test.py`: env back-compat; JSON round-trip incl. masking +
  key preservation on upsert with blank key; resolve precedence; anthropic request
  transform (system hoist, tools input_schema, tool_calls→tool_use, tool_result
  grouping, tool_choice map, max_tokens default); anthropic normalize over synthetic
  SSE incl. tool_use with two input_json_delta chunks + message_delta stop_reason;
  openai normalize incl. tool_calls + finish; to_openai_chunk ids; mask_key edges.
Acceptance: `pytest evals/providers_test.py` green; desktop module import clean.

### T2 — hedge rework (F9 fix + cross-provider)
`speculative_hedge.py`: hedge_stream gains the full agent payload. New primary
signature: `hedge_stream(*, body: dict, sovereign: Target, worker: Target,
request_id: str, settings=None, client=None)` with **back-compat**: the old
positional form `(messages, request_id=..., settings=..., client=...)` keeps
working by synthesizing `body={"messages": messages}` and env Targets — so
`evals/hedge_test.py` passes UNCHANGED.
- Both branch payloads via `providers.build_upstream_request` from the FULL body:
  complete messages (worker NO LONGER reduced to [system, last user]) plus
  tools/tool_choice/temperature/max_tokens when present.
- Both streams consumed via `providers.normalize_stream`; buffers hold normalized
  Events; refusal screen on concatenated content text via routing_patterns
  (keep footnote/is_routable/normalise/should_hedge usage).
- Emission via `providers.to_openai_chunk`; worker path keeps the footnote
  (`footnote(worker_model)`) placed before the finish chunk, adopting the worker
  stream id (current R1/R4 semantics preserved).
- Commit semantics unchanged: sovereign timeout/transport-error → worker;
  ≥COMMIT_TOKENS content tokens, finish, or [DONE] → sovereign wins, replay
  verbatim, cancel worker. Reasoning forwarded live per HEDGE_LIVE_REASONING,
  never screened.
- HedgeSettings env surface unchanged; used to build default Targets when none
  are passed.
- Tests `evals/hedge_tools_test.py` (new): agent-shaped body (multi-turn context,
  tools, tool_choice, max_tokens, temperature) with two mock upstreams
  (httpx.MockTransport): (a) BOTH upstream requests carry tools + full messages +
  max_tokens; (b) sovereign refusal → worker answer + footnote; (c) sovereign
  clean ≥commit → sovereign wins; (d) sovereign refuses + worker emits tool_calls
  → client sees finish_reason "tool_calls" (F9 regression).
Acceptance: hedge_tools_test green AND `pytest evals/hedge_test.py` green.

### T3 — gateway integration in proxy_gateway.py
- Module-global `REGISTRY = providers.load_registry()`; in `chat_proxy` resolve
  Target for `body["model"]` (role "primary"); build upstream payload + headers
  via providers; BYOK: `providers.request_headers(target, client_key)` where
  client_key = client Bearer token w/o prefix.
- Normal path keeps the ring-buffer refusal screen but consumes
  `providers.normalize_stream` and emits `to_openai_chunk`. Divert target:
  `registry.resolve("", role="worker")` (env-worker back-compat).
- Hedge branch passes full `body` + sovereign Target + worker Target to the
  reworked hedge_stream.
- New `GET /v1/models`: `{"object":"list","data": REGISTRY.catalog()}`.
- Honor `stream:false`: same flow, collect events, return ONE OpenAI JSON
  completion (choices[0].message with content/tool_calls, finish_reason, usage
  when seen; application/json). Hedge is skipped for non-stream requests
  (documented in the code comment).
- resolve() KeyError (empty registry) → 400 JSON {"detail": ...}; upstream-open
  failure keeps the existing in-band SSE error format.
- Audit/metrics/guards semantics unchanged (authz, body cap, n>1 400…).
Acceptance: new `evals/gateway_routing_test.py` — mock anthropic + mock openai
providers: model names route to the right upstream URL (assert captured
requests); /v1/models lists both catalogs; stream:false returns JSON; unknown
model → default primary; hedge with agent body emits tool_calls through the
gateway (T2+T3 integration); existing evals/hedge_test.py green.

### T4 — admin page + admin API
New `admin_ui.py` imported by proxy_gateway:
- `GET /admin` → self-contained HTML page (no CDN; vanilla JS/CSS): provider
  table (id, api, base_url, masked key, models, primary/worker badges),
  add/edit form (id, api select, base_url, key field with "keep existing"
  placeholder, models editor as `exposed=upstream` lines), Delete/Test/Discover
  buttons, radios for default primary + default worker, Apply. Status line shows
  API outcomes.
- API: `GET /admin/api/registry` (masked); `PUT /admin/api/providers/{pid}`
  {api, base_url, key?, models{}} — blank key keeps stored; `DELETE .../{pid}`;
  `POST /admin/api/defaults` {primary?, worker?}; `POST /admin/api/providers/
  {pid}/test` → GET `provider.models_url()` with stored headers, 10s timeout →
  {ok, status, model_count|error}; `GET /admin/api/providers/{pid}/upstream-models`
  → parsed id list (both APIs return {"data":[{"id"...}]}).
- Auth: every /admin* route requires header `X-Admin-Token` == env `ADMIN_TOKEN`
  when set; unset → only loopback client hosts (127.0.0.1 / ::1). Else 403.
- Mutations use the SAME Registry instance the gateway resolves through.
Acceptance: `evals/admin_ui_test.py` — CRUD round-trip via httpx ASGI transport,
masked keys in GET, blank-key preserves secret, test endpoint against
MockTransport upstream, admin-token and non-loopback 403 cases, /admin page 200.

### T5 — docs
- `docs/run_speculative_gateway.md`: "Provider hub" section — registry JSON
  schema, `GATEWAY_REGISTRY`, `ADMIN_TOKEN`, bind note (network access needs
  `uvicorn --host 0.0.0.0` + hosts entry mapping `settings.local` → machine IP),
  resolution order, BYOK, page walkthrough, per-provider examples (Anthropic
  https://api.anthropic.com + claude-*; xAI https://api.x.ai/v1 + grok-*; OpenAI
  https://api.openai.com/v1; local hub), hedge tool-compat fix note.
- `docs/integrations/opencode_gemma27b.md`: hub configuration (baseURL at :9000,
  models from /v1/models), hedge interplay note.
Acceptance: commands copy-paste-accurate; schema matches code.

### T6 — final gate
`pytest evals -p no:warnings -q` green (CWD reference-implementation); gateway
boots under uvicorn (127.0.0.1) with tmp registry; GET /healthz, /admin,
/v1/models all 200; no secrets in the tracked diff (grep sk-ant / raw Bearer
literals in added files).

## Rulings (append as decided)
- R1: Fix round cap 5 per task, then controller adjudicates.
- R2: Pre-existing unrelated dirty files on main stay untouched; per-task commits
  stage explicit paths only.
- R3: Tasks are tightly coupled (providers → hedge → gateway → UI), so the
  controller implements them in sequence; each task gets an independent reviewer
  subagent whose findings drive fix rounds. Fresh reviewer context per round.

