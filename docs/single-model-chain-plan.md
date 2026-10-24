> **SUPERSEDED (2026-10-21) — staged plan not executed; superseded by the constellation drop.**
> Status below was "awaiting operator go-ahead"; the go-ahead never fired for this shape.
> Instead, the 2026-10-21 constellation directive implemented the `deep*`/`glm*`
> escalation directly as `providers.py::CONSTELLATION_CHAINS` consumed by
> `proxy_gateway.py` + `speculative_hedge.py` — see `docs/constellation-hub-plan.md`
> (current plan of record).
>
> Reconciliation with the working tree (verified 2026-10-21): **nothing from §7 was
> merged** — no `chain_routing.py`, no `CHAIN_*` env knobs (`grep CHAIN_ROUTING *.py`
> is empty), no `evals/chain_route_test.py` / `evals/chain_exec_test.py`, no
> `tools/hive/verify_chain_live.py`. What DID land from this plan's research: the
> `deepseek-ai/deepseek-v4.1-flash-1017` hop id and `zai-org/glm-5.3-flash` (now the
> constellation's middle hops in `providers.py` and `tars/gx10-router/litellm_config.yaml`),
> and Abliterated V2 Large as the terminal — but via the **Abliteration 2-key pool**
> (`abliteration_keys.py` ensure-pool, `ABLIT_POOL_KEY_A/B`), not §0's
> "apex via the nano key", which is superseded. The `[[GW-*]]` marker layer and
> max-reasoning helms referenced here are live in `context_formatter.py` /
> `constellation.py`. Original plan preserved verbatim below.

# Plan: Single-model provider chains (`deep*` / `glm*`) + Apex-1 Abliterated via the nano provider
# Plan: Single-model provider chains (`deep*` / `glm*`) + Apex-1 Abliterated via the nano provider

Status: **research complete, awaiting operator go-ahead** (no runtime code touched).
Date: 2026-10-20. Verified live in this session unless marked "probe required".
Supersedes the option surface of `three-tier-routing-plan.md` §2/§8 at cutover
(that plan's three-tier plumbing is the base this builds on).

## 0. Operator request (as understood)

1. **One model per specialist API provider** - no more provider x model matrices.
2. **Options starting with `deep`** become one chain:
   DeepSeek 4.1 Flash **max reasoning** -> refused -> GLM 5.3 **no reasoning** ->
   refused -> specialist model -> **apex-1 abliterated via the nano key**.
3. **Options starting with `glm`** become the mirror chain:
   GLM 5.3 **max reasoning** -> refused -> DeepSeek 4.1 Flash **no reasoning** ->
   refused -> specialist model -> **apex-1 abliterated via the nano key**.
4. The apex-1 abliterated model is added for **both** chains through the
   **nano API key** (`nano key env (retired)`).
5. This **replaces all current options** (Frost names, the 8-alias hub matrix,
   max-think names) - but must be **staged and validated with zero impact on the
   current models until it is 100% ready**.

## 1. Research findings (verified this session)

### 1.1 nano catalog (`GET <retired-nano-endpoint>/api/v1/models`, public)

| id | ctx / out | capabilities | reasoning levels | price in/out per M |
|---|---|---|---|---|
| `z-ai/glm-5.3-flash-apex-abliterated` | 1,048,576 / 32,768 | reasoning, vision, tool-calling | low/high/max | $0.15 / $0.50 |
| `z-ai/glm-5.3-flash-apex` | 1,048,576 / 32,768 | reasoning, vision, tool-calling | low/high/max | $0.15 / $0.50 |
| `z-ai/glm-5.3-flash` | 1,048,576 / 131,072 | reasoning, vision, video, tools, structured | low/high/max | $0.10 / $0.30 |
| `deepseek/deepseek-v4.1-flash` (`:thinking` twin) | 1,000,000 / 384,000 | vision, reasoning, tools, structured | **none**/low/high/max | $0.13 / $0.52 |

* **"apex 1 abliterated" resolves to `z-ai/glm-5.3-flash-apex-abliterated`**
  (apex line, v1 = the `flash-apex` deployment; abliterated = the uncensored
  derivative; tags include `cybersecurity`). It is **not on Hive** - it exists
  only on nano, which matches "via the nano api key system".
* Other abliterated ids present on nano (context, not candidates):
  `xiaomi/mimo-v2.6-flash-abliterated`, `abliteration-ai/abliterated-model`,
  `-large`, `-large-v2`, `huihui-ai/*`, `mlabonne/*`, `failspy/*`.
* Apex supports **tool-calling** - agentic diverts survive the final hop.
* `deepseek/deepseek-v4.1-flash` exposes `reasoning_effort: none` (a real
  no-thinking setting); GLM flash does **not** (low/high/max only) - so
  "no reasoning" on GLM must be forced with the thinking-disable knobs
  (`enable_thinking:false`, `chat_template_kwargs.thinking:false`,
  `thinking.type:disabled`) or by using the non-`:thinking` deployment.

### 1.2 Hive catalog (`GET https://api-cdn.thehive.ai/api/v3/models`, registry key)

* `deepseek-ai/deepseek-v4.1-flash-1017` and `zai-org/glm-5.3-flash` are the only
  deepseek/glm ids the catalog lists.
* **The plain `deepseek-ai/deepseek-v4.1-flash`** (what `FROST_ALIASES` and
  `gateway_registry.json` map to today) **is no longer listed** - it may still be
  an accepted alias, but this is a **probe-required** item before the chain
  hard-codes it (fallback id: `-1017`).
* Hive carries **no apex/abliterated** model -> the last hop is nano-only.

### 1.3 Machine / env state (presence only, no secrets printed)

`nano key env (retired)` set; `nano hub-key env (retired)` set; `nano mgmt-key env (retired)` set;
`ABLITERATION_API_KEY` set. `SPECIALIST_API_URL` / `WORKER_API_URL` =
`<retired-nano-endpoint>/api/v1/chat/completions`;
`SPECIALIST_MODEL = abliteration-ai/abliterated-model-large-v2`;
`WORKER_MODEL = xiaomi/mimo-v2.6-flash-abliterated` (superseded 2026-10-21: `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw` on the local gx10 router).
`PRIMARY_*` / `FALLBACK_*` unset -> the gateway bridges to `HIVE_API_BASE` /
`HIVE_SECRET_KEY` (see `_primary_url/_primary_key/_primary_model`).

**Consequence for "1 model per specialist provider":** the nano provider currently serves
**two** specialist-role models (`abliterated-model-large-v2` for diverts,
`mimo-v2.6-flash-abliterated` for the hedge worker). The target design keeps
**one** nano id in the system: the apex-1 abliterated.

### 1.4 Baseline is RED - the tree is mid-refactor (blocking finding)

`py -3.12 -m pytest evals/ -q --ignore=evals/results` ->
**21 failed, 291 passed, 3 skipped** (the README's "101 tests" is stale; the
default `python` is 3.14 and has no pytest - use `py -3.12`).

| # | Cluster | Evidence | Root cause |
|---|---|---|---|
| a | Refusal divert broken (9 tests) | `specialist_system_test` 5, `e2e_gateway_test` 4, `specialist_config_test` 1, `attack_gate_test` 1, `edge_test::breaker` 1 | The uncommitted "continue-with-primary" WIP replaced the inline `is_routable -> tier3_refusal` check with a presignal/grace mechanism. The presignal branch `continue`s **past the `if finish:` block**, and the `[DONE]` branch replays the buffer and returns without confirming - so a refusal that arrives with `finish_reason` (the normal case) never diverts. `CONTINUE_ENABLED=0` does **not** restore old behavior (the inline check was deleted, not gated). |
| b | Plain Frost aliases gone (7 tests) | `frost_alias_test` 4, `max_think_test` 2, `switch_test` 1 | Working tree removed `deepfrost` / `glmfrost` / `cyberfrost` from `FROST_ALIASES`; tests still pin them (`model_switch` resolves `CyberFrost` through the same table). |
| c | `/healthz` contract changed (1) | `edge_test::healthz` `ok is False` | New healthz performs a live probe of `{primary_url}/v1/models` with a real `httpx` client, bypassing the mock transport -> always unreachable under tests. |
| d | Billing bug (1) | `constellation_test::billing_registry_basic` `assert 2.89 < 1.0` | `billing.UserBilling.deduct()` does not reduce the balance (new untracked module). |

**Stage 0 of any implementation is restoring green** - the chain work builds on
the divert machinery, so it cannot be validated on a red tree.

### 1.5 How the divert machinery works today (the plumbing to reuse)

* Single hop: `chat_proxy` (BUFFERING ring buffer) -> `fallback_stream(...)`
  (`proxy_gateway.py:743`) -> specialist. There is **no multi-stage escalation
  yet**; the three-tier plan (T1/T4) designed it but it is not implemented.
* Divert reasons already emitted: `tier3_refusal`, `tier1_empty`,
  `tier1_thinking_only`, `tier1_stream_broke`, `tier1_open_<status>`,
  `forced_divert` (Gate 8), `hedge_forced` / `hedge_hint`.
* Detection is single-source in `routing_patterns.py`: anchored `ROUTING_RE`
  (`is_routable`), `classify_status` (fail-fast 400/401/403/404/422 vs
  retry 408/429 vs divert 500/502/503/504/transport), `should_hedge`.
* Max-reasoning injection exists (`proxy_gateway.py:1327-1332`): `reasoning_effort=max`,
  `reasoning.effort=max`, `reasoning_content`, `enable_thinking`, plus the
  token floor `MAX_THINK_MIN_TOKENS` (32768). Abliteration.ai trims three of the
  knobs; the nano provider accepts the full set.
* Alias resolution order in `chat_proxy`: `resolve_hub_alias` (8-name matrix)
  -> `resolve_frost_alias` (Frost names + max-think) -> passthrough.
  `/v1/models` = `FROST_REGISTRY` + `hub_models_for_listing()`.
* Hedge never races max-think or hub-alias names (explicit provider selection).

## 2. Target design

### 2.1 Option surface: exactly two roots

Every `model` id is normalised (lower, `-`/`_`/spaces folded - reuse
`_normalize_model_name`) and matched by **prefix**:

| Prefix | Chain | Everything that lands here today |
|---|---|---|
| `deep*` | **Chain D** | `deepfrost`, `deepfrost max think`, `deepfrost-v4.1`, `DeepMaxNano`, `DeepNano`, `DeepMaxAblit.ai`, `DeepAblit.ai`, `deepseek-ai/deepseek-v4.1-flash`, `deepseek/deepseek-v4.1-flash` |
| `glm*` | **Chain G** | `glmfrost`, `glmfrost max think`, `glmfrost-5.3-flash`, `GLMMaxNano`, `GLMNano`, `GLMMaxAblit.ai`, `GLMAblit.ai`, `zai-org/glm-5.3-flash` |
| anything else | unchanged passthrough | `cyberfrost*`, `frost-general`, raw unknown ids |

So the replacement is **not a rename**: old names keep working, but they now
select a chain instead of a single upstream model. Clients need no migration.

### 2.2 The chains

| Hop | Chain D (`deep*`) | Chain G (`glm*`) | Provider / key | Reasoning |
|---|---|---|---|---|
| 1 | `deepseek-ai/deepseek-v4.1-flash` (Hive) | `zai-org/glm-5.3-flash` (Hive) | Hive / `HIVE_SECRET_KEY` | **max** (existing knob set + `MAX_THINK_MIN_TOKENS` floor) |
| 2 | `zai-org/glm-5.3-flash` (Hive) | `deepseek-ai/deepseek-v4.1-flash` (Hive) | Hive | **off** (thinking-disable knob set) |
| 3 | specialist (`SPECIALIST_MODEL`) | specialist (`SPECIALIST_MODEL`) | whatever `SPECIALIST_API_URL/KEY` bind | as configured today |
| 4 | `z-ai/glm-5.3-flash-apex-abliterated` | `z-ai/glm-5.3-flash-apex-abliterated` | **nano** / `nano key env (retired)` | server default (apex) |

Properties:

* Hops 1-2 are the same two models in swapped order - "one model per provider"
  holds for the reasoning providers too (Hive serves exactly these two ids for
  the chains; the nano provider serves exactly the apex for the specialist role).
* Hop 3 collapses onto hop 4 **if** the operator confirms the specialist *is*
  the apex (see §4 D-1); the plan ships 4 hops and the collapse is a config
  change (`CHAIN_SPECIALIST_HOP=0`), not a rewrite.
* Hop 4 always runs on nano with `nano key env (retired)` (per the request), even if
  the specialist hop points at the local hub.
* Tool-calling payloads survive every hop (apex + both Hive models support
  tools; the divert path already forwards `tools`/`tool_choice`).

### 2.3 Escalation triggers (reuse, no new detection)

| Trigger | Source (already implemented) | Action |
|---|---|---|
| Hard refusal in the buffered head | `is_routable(buffer_text)` -> `tier3_refusal` | next hop |
| Soft refusal: HTTP 200, empty content | `tier1_empty` | next hop |
| Thinking-only answer | `tier1_thinking_only` | next hop |
| Stream broke mid-flight (pre-flush) | `tier1_stream_broke` | next hop |
| 5xx / transport at open | `classify_status` -> `tier1_open_<status>` | next hop (after retries) |
| Gate 8 attack content | `attack_match` -> `forced_divert` | jump straight to hop 3 |
| 400/401/403/404/422 | `classify_status` = `fail_fast` | **visible error, no escalation** (unchanged) |
| `hedge: true` on a chain name | - | **ignored** (chain = explicit selection; same rule as max-think today) |

The only behavioural novelty is that a refusal at hop N re-dispatches to hop
N+1 with the **same conversation** (plus, when a presignal was replayed, the
existing "primary began to refuse, continue cleanly" continuation turns). Hops
stop at `CHAIN_MAX_HOPS` (default 4) and every hop is audit-recorded
(`signal=chain_stage_<n>_<reason>`) and counted (`chain_stage_total{stage,reason}`).

## 3. Staging plan (zero impact until cutover)

Each stage ends with a **gate**. Nothing in stages 0-4 changes what a client
gets; the switch is stages 5-7.

### Stage 0 - restore green (prerequisite, no new features)

| Step | Change | Gate |
|---|---|---|
| 0.1 | Fix the continue-with-primary confirm path: confirm `tier3_refusal` in the `if finish:` block **and** in the `[DONE]` branch when `refusal_presignal` did not recover; when `continue_enabled` is false keep today's inline `is_routable` check. | `specialist_system_test`, `e2e_gateway_test`, `specialist_config_test`, `attack_gate_test`, `edge_test` green |
| 0.2 | Decide the alias-table contract: restore `deepfrost`/`glmfrost`/`cyberfrost` **or** update `frost_alias_test`/`max_think_test`/`switch_test` to the new contract. Recommendation: restore them now - they become chain roots in §2.1 anyway. | `frost_alias_test`, `max_think_test`, `switch_test` green |
| 0.3 | `/healthz`: keep the live probe but make it opt-in (`HEALTHZ_PROBE=1`) or fall back to the old snapshot when the probe is unreachable in-process. | `edge_test::healthz` green |
| 0.4 | `billing.UserBilling.deduct()`: actually subtract. | `constellation_test::billing_registry_basic` green |
| Gate | `py -3.12 -m pytest evals/ -q --ignore=evals/results` -> **312 passed / 3 skipped** | commit `fix: restore green (stage 0)` |

### Stage 1 - chain data + resolver (additive, unwired)

* New `chain_routing.py`: `CHAIN_STAGES` (the §2.2 table), `resolve_chain(model)`
  (prefix match, returns `None` for non-chain ids), `stage_knobs(stage, mode)`
  (max / off / as-is knob builders), `CHAIN_PREFIXES`.
* New `evals/chain_route_test.py`: normalisation matrix (`DeepFrost v4.1`,
  `deep_max_nano`, `GLM 5.3`, `glm`, `deepseek-ai/...`), stage order per chain,
  knob sets, **single-model-per-provider invariant** (no provider twice per
  chain except Hive's two reasoning hops, asserted explicitly), `None` for
  `cyberfrost`/unknown ids.
* Gate: new suite green, full suite still 312/3, `py_compile` clean.

### Stage 2 - wire behind a flag (default OFF)

* `Settings`: `chain_routing_enabled` (`CHAIN_ROUTING`, default `0`),
  `chain_shadow` (`CHAIN_SHADOW`, default `0`), `chain_max_hops`
  (`CHAIN_MAX_HOPS`, 4), `chain_stage_timeout_s`, apex binding
  (`CHAIN_APEX_API_URL/KEY/MODEL` with nano defaults).
* `chat_proxy`: when the flag is on and `resolve_chain(requested)` matches,
  dispatch through a chain executor that reuses `open_primary` /
  `fallback_stream` semantics per hop, recording one audit row per hop and the
  `chain_stage_total` metric. When the flag is off, the code path is
  **byte-identical** to today (asserted by the untouched existing suites).
* `/v1/models`: publish `deep` / `glm` (and the legacy names) with
  `chain: ["...","..."]`, `hedged: false`, `reasoning: max` **only when the
  flag is on**.
* Gate: full suite green; `CHAIN_ROUTING=0` diff shows zero behavioural change.

### Stage 3 - offline proof (stub matrix)

* Extend the stub harness (`evals/helpers.py` Script) with a
  `evals/chain_exec_test.py`: D1 refuses -> D2 answers (assert the hop-2 payload
  carries the thinking-disable knobs and hop 1 carried `reasoning_effort=max`);
  D1+D2 refuse -> D3 (specialist payload, existing `SPECIALIST_*` binding);
  D1+D2+D3 refuse -> D4 (apex URL = nano, `Authorization` = `nano key env (retired)`,
  model id = apex); hop-1 400 -> visible error, no escalation; hop-1 transport
  error -> hop 2; `hedge: true` ignored on chain names; `CHAIN_MAX_HOPS=2` stops
  at hop 2; audit + metrics per hop; Gate 8 forced divert jumps to hop 3.
* Gate: new suite green, everything else untouched.

### Stage 4 - live probes (cheap, capped, opt-in)

* New `tools/hive/verify_chain_live.py` (`LIVE_STACK=1`-style gate), one PONG
  per stage per chain at `max_tokens <= 256`, printing the model id used and the
  `reasoning_tokens` seen. Specifically probes the **open questions**:
  1. Hive `deepseek-ai/deepseek-v4.1-flash` vs `-1017` (catalog only lists -1017).
  2. Hive honours the thinking-disable knobs? (`reasoning_tokens == 0` on hop 2)
  3. `z-ai/glm-5.3-flash-apex-abliterated` PONGs via `nano key env (retired)` and
     accepts `tools`.
* Gate: 8/8 PONGs (or documented fallbacks adopted, see §5).

### Stage 5 - shadow mode (production, zero behaviour change)

* `CHAIN_SHADOW=1`: for chain-prefixed ids, log the resolved chain + the hop the
  request *would* have escalated to (audit `mode=chain_shadow`) while serving
  the legacy path. Run for a working session; compare `diverted_total` vs
  `chain_shadow_would_escalate_total`.
* Gate: shadow rows look sane (no false escalations on clean answers).

### Stage 6 - cutover

* Flip `CHAIN_ROUTING=1` in `launch_redhands_hub.ps1` (single line), publish the
  chain names, keep every legacy name resolving through the prefix rule.
* Gate: live curl matrix on the real hub (`deep` -> answer; refusal prompt ->
  hop 2; red-team prompt -> hop 3/4 with footnotes), plus suite green.

### Stage 7 - retire (only after the operator confirms cutover is good)

* Delete the 8-alias hub matrix (`HUB_MODEL_ALIASES`/`_HUB_DISPLAY`) and the
  max-think aliases; trim `FROST_ALIASES` to the chain roots; drop
  `WORKER_MODEL`/`SPECIALIST_MODEL` duplicates so the nano provider keeps **one** id;
  update README (replace the "101 tests" baseline), `corrections-ledger.md`,
  and the affected test files; move the Hive key out of
  `gateway_registry.json` (existing S-B item).

## 4. Decisions the operator must confirm (my defaults in **bold**)

| # | Question | Readings / options | Default |
|---|---|---|---|
| D-1 | What does "only 1 model per specialist API provider" pin down? | (a) **the nano provider contributes exactly ONE id: the apex abliterated** - so the "specialist model" hop and the "apex" hop are the same provider+model and collapse into one hop (chain = 3 hops: primary -> mirror -> apex). The local hub may keep exactly one model (CYBER-FROST) as an optional hop. (b) Keep them as two hops: specialist (`abliterated-model-large-v2`) then apex (both on nano = 2 models on one provider). | **(a)** |
| D-2 | How is "no reasoning" enforced on Hive? | (a) thinking-disable knob set (`enable_thinking:false` etc.) **if Hive honours it** (probe). (b) run hop 2 on the nano provider's non-thinking deployments (`deepseek/deepseek-v4.1-flash` / `z-ai/glm-5.3-flash`; `reasoning_effort:none` works for deepseek) - still one model per provider. | probe first, **(a)** if honoured, else **(b)** |
| D-3 | Which Hive DeepSeek id? | `deepseek-ai/deepseek-v4.1-flash` (today's alias, absent from the catalog) vs `deepseek-ai/deepseek-v4.1-flash-1017` (listed). | probe first, **today's id if it PONGs**, else `-1017` |
| D-4 | Do `deep*`/`glm*` chains race the speculative hedge? | (a) **never** (explicit selection, same rule as max-think/hub aliases). (b) allow on hop 1. | **(a)** |
| D-5 | What happens to `cyberfrost` / `frost-general`? | (a) **keep passthrough until stage 7**, then retire or fold into the specialist hop. (b) map `cyberfrost` to the chain specialist hop now. | **(a)** |
| D-6 | Live-probe spend (stage 4) | 8 PONGs at `max_tokens<=256` on Hive + nano. | operator go-ahead |

## 5. Risks & rollback

| Risk | Mitigation |
|---|---|
| Extra spend: every refusal now costs up to 3 more calls | `CHAIN_MAX_HOPS=4`, per-stage `max_tokens` caps, `CHAIN_ROUTING=0` kill switch, `chain_stage_total` counters to see how often it fires |
| Latency: escalation adds TTFT on refusals only | hops are sequential by design; hop 1 keeps the max-think no-race rule so the first answer is not slowed by a second dispatch |
| Hive ignores the no-thinking knobs -> hop 2 still thinks (and can spend the whole budget) | probe in stage 4; fallback D-2(b) uses nano non-thinking deployments; `MAX_THINK_MIN_TOKENS` floor is NOT applied to hop 2 |
| Hive drops the plain deepseek id -> hop 1 400s (fail-fast = no escalation!) | probe in stage 4; pin the working id via `CHAIN_DEEP_PRIMARY_MODEL` env; a 404 proves the need for the `-1017` id |
| Apex model id/price changes (nano catalog is volatile) | id pinned in `CHAIN_APEX_MODEL` env, not code; stage 4 re-probes before cutover |
| Trees touched mid-refactor | stage 0 first; every stage gates on the full suite |
| Rollback | flip `CHAIN_ROUTING=0` (single env line / `launch_redhands_hub.ps1`), no code revert needed; legacy names were never removed |

## 6. New env surface (proposed)

| Var | Default | Meaning |
|---|---|---|
| `CHAIN_ROUTING` | `0` | master switch; `1` = chain dispatch for `deep*`/`glm*` |
| `CHAIN_SHADOW` | `0` | log-only mode (stage 5) |
| `CHAIN_MAX_HOPS` | `4` (`3` under D-1(a)) | hard cap per request |
| `CHAIN_STAGE_TIMEOUT_S` | `60` | per-hop open timeout |
| `CHAIN_APEX_API_URL` / `CHAIN_APEX_API_KEY` / `CHAIN_APEX_MODEL` | nano URL / `nano key env (retired)` / `z-ai/glm-5.3-flash-apex-abliterated` | last hop binding |
| `CHAIN_DEEP_PRIMARY_MODEL` / `CHAIN_GLM_PRIMARY_MODEL` | `deepseek-ai/deepseek-v4.1-flash` / `zai-org/glm-5.3-flash` | hop 1 ids (D-3) |
| `CHAIN_HOP2_PROVIDER` | `hive` | `hive` or `nano` for D-2(b) |

## 7. Files to touch

| File | Stage | Change |
|---|---|---|
| `proxy_gateway.py` | 0,2,3 | stage-0 fixes; `Settings` flags; chain dispatch + executor; `/v1/models`/`/healthz` echo |
| `chain_routing.py` (new) | 1 | chain data + resolver + knob builders |
| `providers.py` | 0,2 | stage-0 alias decision; prefix resolver + listing helper (hub matrix untouched until 7) |
| `billing.py` | 0 | `deduct()` fix |
| `evals/chain_route_test.py` (new) | 1 | resolver/knob/prefix matrix |
| `evals/chain_exec_test.py` (new) | 3 | stub escalation matrix |
| `evals/helpers.py` | 3 | scriptable hops (already supports per-URL scripts) |
| `tools/hive/verify_chain_live.py` (new) | 4 | live PONG matrix |
| `launch_redhands_hub.ps1` | 2,6 | pin `CHAIN_*` env (stage 6 flips `CHAIN_ROUTING=1`) |
| `docs/single-model-chain-plan.md` (this) | - | plan of record |
| `README.md`, `corrections-ledger.md` | 7 | document cutover + defect IDs |

## 8. Verification commands

```powershell
# offline suite (note: default python 3.14 has no pytest; use py -3.12)
py -3.12 -m pytest evals/ -q --ignore=evals/results        # gate: 312 passed / 3 skipped

# new suites
py -3.12 -m pytest evals/chain_route_test.py evals/chain_exec_test.py -q

# live probes (stage 4, opt-in)
$env:LIVE_STACK='1'; py -3.12 tools/hive/verify_chain_live.py
```

## 9. Sign-off

* Research: complete (§1, all live-probed today).
* Runtime code changed by this document: **none**.
* First implementation step on approval: **Stage 0** (restore green), then
  Stage 1 (chain_routing.py + tests) - both purely additive/repair, no client
  behaviour change, `CHAIN_ROUTING` stays `0` until stage 6.

