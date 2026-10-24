# Stage 0 Plan — Correctness Polish (PROVEN)

**Status: DONE (2026-10-23)** · Parent: `docs/constellation-master-plan.md` (Phase 0)
· Loop: investigate → implement → test → refine, until flawless.

## Scope

Four post-mortem debts from the 2026-10-23 stream-death session, closed under
the plan's design laws L1-L6 (see the master plan).

## Items

### 0.1 Race continuation seed double-count
- **Defect:** the payload riding a BUFFERED length-finish line was tallied into
  `full_text` at arrival (main loop) AND re-added at the winner replay —
  the continuation seed contained it twice.
- **Fix:** `speculative_hedge.py` replay loop no longer adds `kept[1]`
  (buffered lines were already tallied; tail/continuation lines were not —
  their adds stay).
- **Proof:** `hop_status_test.py` pins
  `cont["messages"][-2]["content"].count("Deliberating") == 1`.

### 0.2 Zero-refusal gap on the race continuation tail
- **Defect:** the winner's continuation round streamed VERBATIM — a
  continuation answering with a refusal shipped as the race's final answer
  (observed live in the 2026-10-23 debug session).
- **Fix:** content-only refusal screen (`is_routable`, F1/B21-safe) in the
  continuation drain; on refusal: escalate to the terminal when wired, else
  the honest cut (the winner's clean partial + held finish). New counter
  `race_refusal_tail_total` (auto-surfaced via the `_RACE_OUTCOMES` bridge).
- **Proof:** `test_race_continuation_refusal_does_not_ship` (middle AND
  continuation refusals vanish; terminal answer ships; counter == 1).

### 0.3 Tag-form `system-reminder` artifact gap
- **Defect:** stage 3 only caught the colon form; the Anthropic-style TAG
  block sailed through `prune_artifacts` and `assert_clean`.
- **Fix:** paired regex `<system-reminder[^>]*>[\s\S]*?</system-reminder>`
  (wholesale block removal) + orphan markers `<system-reminder` /
  `</system-reminder` in `_LEAK_MARKERS` (the L3 bidirectional invariant).
- **Proof:** 4 new pins in `context_formatter_test.py` (paired, orphan
  opener, orphan closer, assert_clean).

### 0.4 S1 / tier1 contract documentation
- **Fix:** the S1-contract comment at all three `tier1_thinking_only` sites
  (a length cut continues UPSTREAM of the gate; the divert only sees genuine
  stop-finishes) + a new section in `refusal-interception/ARCHITECTURE.MD`.

## Validation record (the refine loop)

| Round | Suites | Result |
|---|---|---|
| 1 | hop_status, context_formatter, length_continue, chains_td, hedge×3, thinking_only | **70/70** |
| 2a | routing, stream_finalize, zero_refusal, presignal×2, edge, switch | **99** |
| 2b | offense_transition, camouflage, max_think, attack_gate, parity, specialist_config, state_hygiene, ablit_hide, rescue | **187** |
| 3 | assembly, specialist_system, e2e_gateway, context_handoff, constellation, conductor, fanout, stage0, callback, ablit_pool, account_pool, commitment, frost_alias, team | **169** |

**Total: 525 tests, 0 failures.** `py_compile` clean. Hub restarted
(PID 28156) with `race_refusal_tail_total` registered on `/metrics`.

## Files touched

`speculative_hedge.py` (0.1, 0.2, counter), `context_formatter.py` (0.3),
`proxy_gateway.py` (0.4 comments), `refusal-interception/ARCHITECTURE.MD`
(0.4), `evals/hop_status_test.py` (0.1+0.2 tests),
`evals/context_formatter_test.py` (0.3 tests).
