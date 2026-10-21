---
name: epic-plan
description: Use when planning or executing multi-phase implementation work at per-line edit precision, on ANY project or codebase (the "traycer epic plan" standard). Transforms a feature request into an Epic > Phase > Ticket plan with numbered sequential edits anchored to exact file:line, a mirrored dot-point edit checklist, an adversarial 10/10 line-by-line scrutiny pass before execution, review findings folded into tickets, and a verify-or-honestly-pivot execution loop that never fakes completion.
---

# Epic Plan — line-level planning + scrutiny + verify-or-pivot execution


## Core principle

A plan is only as good as its edit-level traceability: every edit numbered
and anchored to an exact file:line, mirrored in a checkbox checklist, and
executed under a loop that ends only when every checkpoint is verified
complete - or an honestly-documented superior alternative replaces it.
**Never fake completion; complete or justify.**

## Stage 1 - RESEARCH (facts before opinions)

- Read every edit surface at LINE level (exact start-end ranges), never
  whole-file skims. Record: anchors, signatures, insertion points,
  existing patterns to mirror (endpoints, fixtures, registries).
- Wide surface (>3 files)? Spawn parallel read-only scouts; verify their
  reports against your own targeted reads before trusting a line number.
- Output: a surface map - file:line -> what lives there -> where new
  code grafts onto it.

## Stage 2 - REVIEW (verify the "done")

- Re-verify every SUPPOSEDLY-complete claim: grep the codebase, read the
  cited lines, run the suite. A green suite proves tests pass - not that
  the right things are tested.
- Where shipped code could be better: improve, refine, or rewrite it.
  Each finding gets an F-ID (F1, F2, ...) and is FOLDED INTO A TICKET -
  findings never float free of the plan.
- Defects in live code ship FIRST (before new features).

## Stage 3 - PLAN (Epic > Phases > Tickets)

Every ticket carries FOUR mandatory parts:

1. PROSE SPEC - goal, mechanism, files touched, why this order.
2. SEQUENTIAL EDIT LIST - Edit #1, #2, #3... each entry:
   `Edit #N: <file> @ :<line-anchor> - <insert before|after|replace>
    <exact change> (because <dependency on edit #M>)`
   The order is dependency-driven: data structures before consumers,
   kill-switches before features, RED tests before implementation.
3. EDIT CHECKLIST - the SAME edits as terse checkboxes, one line each,
   near-equal COUNT to the edit list (the checklist IS the plan,
   compressed). Checked off only after per-edit verification.
4. GATE - RED (watch the new tests fail) -> implement -> GREEN ->
   full suite -> relaunch service -> health check -> metrics move.

## Stage 4 - THE 10/10 SCRUTINY PASS (after the full plan, before execution)

Once the complete sequential plan exists, re-read the ENTIRE plan line by
line as a hostile reviewer. Grade every line, edit spec, and checklist
row out of 10. Where it is not a 10, REWRITE it in place:

- Vague anchor ("locate by", "or its endpoint", "somewhere near",
  "the region that owns X") -> search the code, replace with the exact
  file:line. A vague anchor is a 0/10 anchor.
- Any edit that could be done two ways -> decide one way, state which.
- Any checklist row that cannot be objectively ticked -> rewrite it so a
  stranger could verify it.
- Any missing dependency in the edit order -> reorder now, not during
  execution.
- Any finding (F-ID) mentioned but not ticketed -> ticket it or drop
  the mention.
- Any test that would still pass if the feature broke -> tighten it.
- Any copy of the plan that exists only in prose (not in the edit list
  or checklist) -> it does not exist; add it or delete it.

REPEAT the pass until every line grades 10/10. The scrutiny pass is
adversarial: grading yourself generous is the failure mode. A plan that
survives it is execution-ready; a plan that has not had it is a draft.
Scrutiny findings are themselves graded and folded back in (the loop
applies to the plan, not just the code).

## Stage 5 - EXECUTION LOOP (verify-or-pivot)

For each sequential edit, in order:
- Make the edit. Verify it: re-read the region, run the ticket's tests,
  tick the checkbox. An edit is not done until its checkpoint is.
- After each ticket: run the full gate, then REVIEW THE WHOLE CHECKLIST
  for desync (drift between plan and reality accumulates silently).
- LOOP: while any checkpoint of the current edit sequence is incomplete
  -> revise the approach and continue. Do not skip forward past an
  unverified checkpoint.
- HONEST PIVOT: if a discovery proves - without a doubt, not a
  preference - that an alternative concept is far superior: STOP.
  Document the discovery, the superior alternative, and which
  checkpoints it replaces. Update the edit list + checklist. Continue
  under the new shape. A preference is NOT a discovery; silent
  watering-down of a checkpoint is NEVER allowed.

## Stage 6 - CLOSE-OUT

- Final full suite + live verification + docs/README/skill updates.
- Completion report: every checkpoint [x] or its honest-pivot note.

## Quick reference

| Artifact        | Requirement                                    |
|-----------------|------------------------------------------------|
| Surface map     | file:line -> what -> graft point                |
| Findings        | F-IDs, folded into tickets, live ones first     |
| Edit list       | numbered, anchored, dependency-ordered           |
| Checklist       | mirror of edit list, one checkbox per edit      |
| Scrutiny pass   | every line graded, sub-10s rewritten to 10/10    |
| Gate            | RED -> GREEN -> suite -> relaunch -> healthz     |
| Pivot rule      | documented discovery only, never preference      |

## Anti-patterns

- Vague tickets ("improve detection") with no edit anchors
- A checklist shorter than the plan it mirrors
- Marking a checkpoint complete from memory - verify every time
- Pivoting without a written discovery note
- Skipping RED: a test you never watched fail teaches nothing
- Findings reported but not ticketed (they evaporate)
- Skipping the scrutiny pass because the plan "feels done"
- Grading your own lines generous - scrutinize as a hostile reviewer


