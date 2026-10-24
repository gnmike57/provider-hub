# Constellation Balance Plan — all parts contributing (2026-10-23)

**Operator directive:** "deepseek taking over and glm taking over happens as
much as possible because all parts should be contributing equal or as much as
possible" — review all 12 chains' fallback / return-back-up-the-chain
logic, find where DEEP/GLM are wasted and the specialist over-burdened.

## 1. The measured truth (336-request matrix, contribution audit)

Who actually answered, per chain (`evals/contribution_audit.py` +
`contribution_models.py` on the final run):

| Chain | Offload (free local) | Helm | Middle (DEEP/GLM) | Specialist V2 | Verdict |
|---|---|---|---|---|---|
| 1 GLMMAX>DEEP | 46% | 29% | **14%** | 11% | middle = failure-only |
| 2 DEEPMAX>GLM | 57% | 21% | **18%** | 4% | middle = failure-only |
| 3 SUB-GLM/DEEP | — | 93% (V2) | **~0%** | 7% | raced middle NEVER wins |
| 4 GLMMAX>ABLIT-UNC | 39% | 29% | **7%** | 25% | |
| 5 RACE DEEPMAX/GLMMAX | — | 89% (glm-fast) | 7% (deep) | 4% | fast lane dominates |
| 6 CONDUCTOR | — | plan+assemble | fan-out DEEP ✓ | nasty-hop ✓ | **balanced by design** |
| 7 GLM-PROBE | — | 4% | **93%** (probe) | 4% | **the balanced exemplar** |
| 8 DEEPMAX>ABLIT-UNC | 39% | 39% | **0%** | 21% | middle idle |
| 9 SUB-DEEP/GLM | — | 96% (V2) | **~0%** | 4% | raced middle NEVER wins |
| 10 DEEP-PROBE | — | 32% | **61%** (probe) | 4% | balanced |
| 11 RACE GLMMAX/GLM | — | 96% (glm-fast) | — | 4% | one-brain race |
| 12 RACE DEEPMAX/DEEP | — | 100% (deep-fast) | — | 0% | one-brain race |

## 2. Diagnosis — the operator's hypothesis is CONFIRMED, precisely

1. **The hedge's middle races in SHADOW and its tokens are DISCARDED.**
   `speculative_hedge.stream()` opens the sovereign (helm) AND the worker
   (middle) in parallel on EVERY request, but the worker's output only ships
   when the sovereign refuses / times out / empties. On chains 1/2/4/8 the
   DEEP/GLM middle generates a full parallel answer per request and ships
   **7–18%** of the time — ~85% of its tokens are literally wasted. The
   "glm/deepseek taking over..." footnote (the operator's observable) fires
   only on sovereign FAILURE.
2. **The SUB chains (3/9) are the worst offenders**: the V2 helm almost
   never fails, so the raced GLM/DEEP middle contributes ~0%. One brain
   (V2) does ~100% of chains 3 and 9.
3. **The specialist is NOT over-burdened overall** (4–25%, and the r_*
   probes legitimately need it) — the imbalance is the MIDDLE being
   under-used, not the V2 over-used. Exception: chains 4/8 (25%/21%) where
   the ABLIT-UNC middle fails more and spills to the V2.
4. **The balanced patterns already exist in-house**: the PROBE chains
   (cheap middle answers 61–93% directly) and the CONDUCTOR (fan-out to
   DEEP sub-agents, V2 only for the nasty hop). And the RACE chains proved
   the mechanics: both candidates stream FOR REAL, first clean+substantive
   commit wins, loser cancelled, both-refusing escalates to the V2.
5. **The GX10 offload** (free local box) legitimately eats 39–57% of the
   3-hop chains' simple asks — keep it: it is the cheapest contributor and
   already the "everyone contributes" spirit.

## 3. Research grounding

- **FrugalGPT** (Chen, Zaharia, Zou, 2023 — arXiv:2305.05176): the LLM
  cascade — cheap model first, escalate only when a quality gate fails;
  up to **98% cost reduction** at matched accuracy. Our constellation is
  already the *parallel* (speculative) form: both lanes generate at once
  and the first CLEAN answer commits. A sequential cascade would REDUCE
  middle contribution (the middle only answers when the helm is suspected
  weak); the operator's equal-contribution goal needs the RACE, not the
  cascade.
- Follow-on routing work (RouteLLM, Hybrid-LLM) confirms the same shape:
  a learned gate decides cheap-vs-expensive. Our gate is better for this
  goal: commit-on-substantive-cleanness is content-driven, needs no
  training, and makes BOTH lanes always contribute.

## 4. The plan

### BR-1 — HEDGE_RACE_MODE: the hedge becomes a commit-race (the big one)
Convert `speculative_hedge.stream()`'s sovereign/worker shadow-race into
true `race_stream` semantics behind a knob (env `HEDGE_RACE_MODE`, default
1; kill switch =0 restores the shadow-race):

- Both branches stream for real (they already do — nothing is wasted on
  open).
- The FIRST branch to deliver a clean+substantive window COMMITS and wins
  (reuse the race rules: F1/B21 refusal screening, reasoning counts toward
  commit, cancel-on-commit closes the loser, empty-sovereign rule, etc.).
- BOTH refusing/timeout → the specialist escalation, unchanged (L1 law).
- The worker's win yields the takeover footnote on every request it wins —
  the operator's "glm/deepseek taking over as much as possible" becomes the
  normal path, not the failure path.
- Rollout: chains 1, 2, 4, 8 (3-hop) + 3, 9 (SUB — the V2 vs GLM/DEEP become
  real three-way contributors). The offload gate stays IN FRONT (free lane
  first).

Expected distribution after BR-1 (based on the race chains' measured
behavior): middle 40–60% of non-offload requests (from 7–18%), helm
30–50%, specialist ≤15% (refusals only).

### BR-2 — Observability: contribution metrics + audit tooling
- `middle_takeover_total` / `helm_commit_total` metrics + the takeover
  footnote counter per family (glm/deep/v2) in `/healthz`.
- `evals/contribution_audit.py` + `contribution_models.py` promoted to
  keepers (they produced the table above); wire the matrix summary to print
  the contribution row per chain.

### BR-3 — Verification (the balance bar)
Re-run the 336-request matrix; the targets:
- Every DEEP/GLM middle ≥ 30% contribution on its chain (from ~0–18%).
- Specialist ≤ 25% everywhere (it stays the nasty-work brain).
- Zero quality regression: per-chain correct within −1 of the current
  19–24/28 band; zero marker leaks; zero refusal shipments.

### BR-4 (optional, data first) — self-race lane balance
The one-brain self-races (11/12) see the no-reasoning lane win 96–100%.
If BR-3 shows quality unchanged, accept it (fast lane is the right answer
for simple asks). If quality drops on hard asks, bias the race: the
max-think lane opens first (head start) or the fast lane's commit window
requires +10 substantiveness tokens. Decide on matrix data, not taste.

## 6. Delivered with the plan (2026-10-23, same evening)

- **REDHANDS ON EVERY SPECIALIST TAKEOVER** (operator directive, same day):
  `_terminal_system_prompt` now runs the REDHANDS laws whenever the
  specialist takes over on ANY chain — refusal diverts, sticky/continue/
  forced legs, race escalations. Kill switch `REDSHANDS_AUTO_TAKEOVER=0`.
  Pins: `evals/redhands_auto_test.py` (takeover, kill switch, race
  escalation).
- **True-upstream spend accounting**: `upstream_chars_total` +
  `hedge_upstream_chars_total` metrics count every generated char the hub
  receives (winners, shadow-race losers, escalations, continuations,
  probes, verifies) — the waste in section 2 is now MEASURABLE live.
- **THE COMPLETE TOKEN EFFICIENCY + EFFICACY MATRIX**
  (`evals/token_efficiency_matrix.py`): per chain, sequentially (clean
  attribution), the full 28-probe registry with /healthz counter deltas:
  efficacy (correct/28) x upstream tokens/request x shipped tokens/request
  x waste ratio x tokens-per-correct-answer x ttft/tok-s. Results land in
  `evals/results/token_efficiency_matrix.jsonl` +
  `token_efficiency_summary.json` — the BEFORE baseline for BR-1.

## 7. RACE v2 + the efficiency matrix delivered (same night, operator directive)

**The BEFORE matrix** (`evals/token_efficiency_matrix.py`, 336 requests,
per-chain `/healthz` counter deltas; full table recomputable via the log):

| chain | eff | up/req | ship/req | waste | tok/ok |
|---|---|---|---|---|---|
| GLMMAX>DEEP | .72 | 781 | 91 | 8.6x | 1079 |
| DEEPMAX>GLM | .82 | 1367 | 114 | 12.0x | 1664 |
| SUB-GLM/DEEP | .79 | 633 | 95 | 6.7x | 806 |
| GLMMAX>ABLIT-UNC | .64 | 610 | 94 | 6.5x | 948 |
| RACE DEEPMAX/GLMMAX | .89 | 1391 | 111 | 12.6x | 1558 |
| CONDUCTOR | .82 | 247 | 245 | **1.0x** | **300** |
| GLM-PROBE | .79 | 545 | 231 | 2.4x | 694 |
| DEEPMAX>ABLIT-UNC | .79 | 2224 | 95 | **23.4x** | 2830 |
| SUB-DEEP/GLM | .86 | 75 | 113 | **0.7x** | **87** |
| DEEP-PROBE | .89 | 448 | 107 | 4.2x | 502 |
| RACE GLMMAX/GLM | .82 | 720 | 92 | 7.8x | 877 |
| RACE DEEPMAX/DEEP | .82 | 623 | 136 | 4.6x | 759 |

The waste column is the shadow-race + escalation overhead made visible
(23.4x on DEEPMAX>ABLIT-UNC: 2224 true tokens to ship 95).

**RACE v2 (operator directive, same night):**
1. **The improved FINAL-RESPONSE chooser** - the first clean commit opens a
   grace window (`RACE_GRACE_MS`, default 2000); every candidate that
   commits inside it collects, and the best answer wins (substantiveness +
   a 500-point exhausted-clean completion bonus). A complete answer settles
   the race instantly; single-committer races stay fast-lane.
2. **LIVE PEER-LEARNING** - candidate 2 opens AFTER candidate 1 has a clean
   partial (`RACE_PEER_MIN_CHARS` 120 / `RACE_PEER_MAX_WAIT_MS` 2500), WITH
   the peer's draft injected before the client's ask ("learn from it,
   correct anything wrong, give your OWN complete answer"). Continuation
   seeds carry the other candidate's clean partial too (cross-learning).
3. **Refusal-silencing** - a candidate whose window anchors a refusal
   (`is_routable`) OR reads watered-down ("possibly refusing",
   `zero_refusal_violation` = partial) is SILENCED for the remainder of
   that race: dead, never a committer, never a peer draft.
   `race_silenced_total` counter.
4. **HEDGE_RACE_MODE (BR-1)** - the hedge's shadow-race becomes a true
   commit-race (delegates to the same race machinery): the DEEP/GLM middle
   contributes on every request instead of only on failure. Kill switch
   `HEDGE_RACE_MODE=0`.

New counters (surfaced via /healthz): `peer_seeded`, `silenced`,
`grace_decided`, `fast_lane`, `race_marker_escape_total`.

## 5. Risks and guards
- **Cost**: racing both lanes burns both tokens per request (already true
  today in the shadow-race — the waste just becomes useful). Hive is
  flat-billed; the real cost is rate-limit pressure — the pool already
  proved 336-request bursts fine.
- **Quality**: the fast lane could win asks that needed deliberation —
  BR-3's quality bar + BR-4's tunable bias.
- **Kill switches**: `HEDGE_RACE_MODE=0` restores the shadow-race; the
  existing `RACE_CHAIN_ENABLED` / `SUSTAINED_CHAIN_ENABLED` /
  `CONDUCTOR_CHAIN_ENABLED` per-class switches stay.

