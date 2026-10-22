---
name: goal
description: Use when the operator demands an UNDEFEATABLE checklist completion - a goal that will not stop until EVERY item is done, no exceptions, survives session death/crashes/reboots, polls every 30 seconds for THROUGHPUT (real progress heartbeats), and escalates through a multi-layer system (L1 nudge, L2 replan, L3 fresh sub-agent, L4 operator-alert-and-continue) whenever throughput stalls. Backed by goal_engine.py's atomic on-disk ledger and the Goal Watchdog scheduled task.
---

# /goal — the undefeatable checklist

## The contract (operator directive 2026-10-23)

1. **NO EXCEPTIONS**: the goal is complete only when EVERY checklist item
   is `done`. Nothing else ends it - not errors, not stalls, not restarts.
2. **SURVIVES ANYTHING**: the ledger lives at `goals/<slug>/state.json`
   (atomic writes, cross-process locks). A crashed session, a reboot, a
   killed process - any new session resumes exactly where it left off.
3. **THROUGHPUT, polled every 30s** (`GOAL_TICK_S`): every real step you
   take MUST call `goal progress` - that is the heartbeat. No heartbeat
   within the window is a STALL.
4. **MULTI-LAYER ESCALATION when there is no throughput** (the ladder
   never stops the goal, it only escalates):
   - **L1 NUDGE** — re-read the item, resume immediately.
   - **L2 REPLAN** — decompose the item into smaller concrete sub-steps.
   - **L3 SPAWN** — hand the item to a FRESH sub-agent with full context
     (the stall is recorded in `goals/<slug>/ALERTS.md`).
   - **L4 ALERT+CONTINUE** — operator alert recorded; work the NEXT pending
     item and re-attempt the stuck one next cycle. The goal does NOT stop.
   - Any progress event resets the ladder to L0.

## Invoking

```
/goal <title> --checklist <file.md>     # markdown: '- [ ] x' / '1. x' rows
/goal <title> --item "first" --item "second"   # inline items
```

Engine (run from the repo root, `py -3.12 goal_engine.py …`):

| Command | When |
|---|---|
| `init --title T --checklist F` | create the goal, make it ACTIVE |
| `next` | the item to work right now + escalation state |
| `progress --note "what you just did"` | **every real step** - the heartbeat |
| `done <id>` | item verified complete (only with evidence) |
| `tick` | ONE 30s throughput evaluation + directive |
| `status` / `list` | where things stand |
| `watchdog` | the survivor loop (single-instance) |
| `watchdog-auto` | scheduled-task entry (idempotent) |

## THE LOOP (how you work a goal)

1. `init` (or find it already running: `list` → it resumes; NEVER re-init
   an existing goal - continue its ledger).
2. Start the survivor: run `install_goal_watchdog.ps1` once per machine
   (registers the "Goal Watchdog" task: logon + every-minute triggers that
   keep the 30s poller alive through session death AND reboots).
3. Repeat until `status` says `complete`:
   a. `next` → the current item.
   b. DO THE WORK. Every meaningful step (edit, test run, verification,
      read that changed your plan) → `progress --note "..."`. If a step
      takes longer than ~30s of wall time, call `progress` again midway -
      throughput must be visible.
   c. Item verifiably done (evidence in hand: green test, verified file,
      live probe) → `done <id>`.
   d. Between items, or whenever you feel blocked, read the watchdog's
      directive (`tick` or `goals/<slug>/watchdog.log` + `ALERTS.md`) and
      OBEY the escalation action - it is the throughput contract.
4. A stall is never a stop: at L3 spawn a fresh sub-agent on the item; at
   L4 record the alert and keep working the rest of the list.

## Survival semantics (for a NEW session finding a running goal)

`goal list` → any `running` goal with ` <- ACTIVE`: read its state, run
`next`, and re-enter THE LOOP. The ledger is the truth; never trust memory.

## Laws for marking `done`

An item is `done` only with EVIDENCE (a passing test, a verified file, a
live probe) - the same bar as this repo's verify-or-pivot discipline. When
unsure, `progress --note "..."` and keep working; never mark done to make
the list look better - the engine will outlive the lie anyway.
