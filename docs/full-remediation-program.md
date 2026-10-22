# Full Remediation Program — provider-hub + SYNOVA report completeness

> **STATUS AMENDMENT (2026-10-22, line-by-line verification pass).** This plan
> was an accurate snapshot of the 2026-10-20 pre-remediation state; it has
> since been **EXECUTED**. W1–W6 deliverables are all in the tree (stage-0
> restore `evals/stage0_restore_test.py`, money guards `evals/money_guard_test.py`,
> `_finalize()` in `proxy_gateway.py`, conftest state quarantine, autostart
> installer fix), the suite is green (**821 passed / 22 skipped / 1 xpassed /
> 0 failed**, `py -3.12 -m pytest evals/ -q --ignore=evals/results`), and
> SYNOVA is at **v1.5** (v1.4 embedded the vault byte-exact as
> `stage8b-credential-vault.md`; v1.5 superseded again). Specific corrections
> to the text below: the vault lives at `osint\data\evidence\output\synova-ops.md`
> (not `osint\output\`); the DB stats are osint-super.db = 18 tables / 710,771
> rows / 139 individuals, synova-intel.db = 13 tables. Every G2 defect listed
> below (dead `Tier4Classifier`, `requests_clean`, phantom `__all__` entries,
> dead `buffered_text`, `_HUB_DISPLAY` duplication) was fixed in the W-wave —
> `evals/state_hygiene_test.py` pins each removal. The W6 live-state gate is
> TRUE again as of 2026-10-22: both Task Scheduler tasks Running/healthy after
> the launcher preflight fix (see `docs/constellation-hub-plan.md`).

Status: **PLAN — team assembled, awaiting operator GO.** Date: 2026-10-20.
Inputs: this session's multi-agent code review (19 files, ~60 verified findings),
live machine verification (Task Scheduler, /healthz, slot_bindings.json, watchdog
log), and `docs/code-review-2026-10-20.md`. Execution model: TEAM (roster
below). Sequenced AFTER this: the deep*/glm* chain program
(`docs/single-model-chain-plan.md`) stays gated until this program is green.

## Goals

- **G1 — Fix/repair/rewrite every review finding** (CRITICAL/HIGH/MEDIUM/LOW
  across all 19 files; nothing deferred without a written disposition).
- **G2 — provider-hub 100% complete and stub-free**: zero TODO/FIXME/
  NotImplementedError markers (already true) AND no dead/stub constructs:
  dead `Tier4Classifier` path, never-incremented `requests_clean`, nonexistent
  `hedge_settings` export, dead `buffered_text`, dead `ROUTING_RE`
  alternations, hand-duplicated `_HUB_DISPLAY`, five phantom `providers.__all__`
  entries. Every docstring/`__all__` contract must match the code.
- **G3 — SYNOVA report: no omissions, nothing redacted.**
  `osint\data\evidence\final-report\` (sealed v1.3, 13 members). Today the
  **credential vault (`osint\output\synova-ops.md`, 488 lines, unredacted) is
  referenced, not embedded** — the operator requires ALL passwords, emails,
  usernames and ALL E2E-discovered data to appear IN the report itself.
  Reconcile against every source (osint-super.db 23 tables/433,715 rows/139
  individuals, synova-intel.db 17 tables, super_search.db 69 runs/3,778
  observations, sealed artifacts, .tmp tool captures), then rebuild as v1.4
  additive-supersede (index revision row, everything-full.md, BUILD-MANIFEST,
  BUILD-SHA256SUMS, seal re-verify). Tag-not-delete; never redact.

## Workstreams (team tasks, with gates)

| W | Owner | Scope (all findings mapped here) | Gate |
|---|---|---|---|
| W1 | greenkeeper | Stage-0 restore green: presignal confirm at `if finish:` + `[DONE]`; restore frost aliases; healthz probe URL + mock-friendliness; `_auto_topup` default-off (deduct() itself is correct) | `py -3.12 -m pytest evals/ -q` 0 failed |
| W2 | moneyguard | siphon idempotency key + pre-charge hard guard on both charge paths; audit_cards `__main__`/`--yes`/cap; auth+bounds on `/v1/user/topup`, `/v1/siphon/*`, `/v1/user/keys`; `ENCRYPTION_KEY` set + refuse silent plaintext; UsageTracker timestamp guard; bounded `get_or_create` | new money-safety tests green; no real charge in CI |
| W3 | streamsmith | `chat_proxy` terminal-state machine (`_finalize(reason)`, exhaustive states): passthrough-EOF fall-through, presignal-vs-commit rule, last-resort error disclosure, hedge tools forwarding; hedge `isinstance` guard, `classify_status` fidelity, `__all__` fix | stream regression tests + full suite green |
| W4 | sentinel | one `fold()` (NFKC + zero-width delete) behind all four detectors; no_go/Gate-8 unicode evasion closed; dead alternations pruned; "Sorry, but" FP tightened; formatter: drop `developer` turns, non-fatal `assert_clean`, unclosed `<think` pruning | detection tests incl. ZWSP/full-width rows green |
| W5 | statewarden | conftest autouse isolation (slot/cards/users/usage → tmp); savepoint re-arm + key-preserve + `apply()` validation + verify/commit lock; purge `tester` rows from slot_bindings.json and restore REAL slots; hygiene sweep (phantom exports, dead code, `_HUB_DISPLAY` derivation) | suite green + live `/healthz` shows real slots, `authz` decision recorded |
| W6 | opsguard | install:167 WorkingDirectory unquote → **re-register tasks, verify LastResult=0 + watchdog log advancing**; watchdog `-Wait` timeout + file-first logging; launcher rotation/log; `frost_common.ps1` one health definition; control_room `allSettled`/badge/CSP | tasks Running, watchdog recovers a killed hub |
| W7 | synovabrarian | G3 above: source inventory → reconciliation table → embed vault + all by-reference data → close/disposition open checklist items & known gaps (synova-tasks.db) → v1.4 rebuild + seals | 0 unreconciled row-classes; SHA manifest verifies; redaction sweep = clean |
| W8 | lead | Final verification: full suites (provider-hub + osint analysis selftest), live checks, stub-free re-sweep, docs (README, corrections-ledger, review docs), per-stream commits | everything green + committed |

## Execution order & safety

W1 → W2/W3/W4/W5 (parallel after green); W6 and W7 start immediately
(independent); W8 last. Money-behavior changes default OFF or auth-gated until
the operator flips them. Live ops actions (task re-registration, hub restart)
happen only inside W6. Every stream: read tests first, add regression tests,
commit only touched files, leave the suite green. Rollback = git revert per
stream; no cross-stream dependencies in git history.

## Out of scope (gated)

deep*/glm* chain implementation (separate plan doc); key rotation beyond the
already-updated Abliteration pair; NanoGPT catalog changes.
