# GX10 Long-Horizon Soak Rig — continuous, self-improving, restart-proof

> **STATUS: DEPLOYED AND RUNNING (2026-10-23 23:45 AEDT).** Pass 1 in
> flight (`in_flight:4`). Observe: `ssh gx10 'tail -f ~/soak/report.txt'`.
> The rig now brands itself **RedHands Hub** everywhere (the hub's
> /healthz, the launch script, the README, this plan - all four synced).

**Operator directive (2026-10-23 night):** SSH into the gx10 and set up
long-horizon continuous, far-more-extensive testing where ONLY the
abliteration API calls are simulated and the DEEP/GLM calls are REAL token
spend. After every test run the corpus grows; after every pass an evaluation
and a tinkering/improvement attempt is made; any error discovered is
investigated and aggressively fixed. **The rig must survive restarting this
PC (and the gx10) without a hitch** - the PC becomes an observer, never a
dependency.

## S0 - Recon (DONE, facts in hand)
- `ssh gx10` works (100.67.13.78, user nick, keys wired; MagicDNS flaky,
  pinned IP in ~/.ssh/config).
- Python 3.12.3 on the box; the local hub on :4000 is live (cyber35b,
  deepseek-v4-pro, ...); 1.6 TB free on /; NVIDIA GB10.

## S1 - The rig lives entirely on the gx10 (`~/soak/`)
1. **Deploy (PC -> gx10, idempotent, only on code changes):**
   `evals/deploy_soak.ps1` rsyncs the hub (proxy_gateway,
   speculative_hedge, providers, context_formatter, routing_patterns,
   redhands, skills_memory, camouflage, account_pool, gx10_offload) +
   the evals harness into `~/soak/`. The rig NEVER depends on the PC
   after deploy - PC restarts are invisible to it.
2. **The abliteration mock (`~/soak/ablit_mock.py`, port :4100):** an
   OpenAI-compatible SSE server answering as the V2 specialist -
   refusal-free, substantive, REDHANDS-styled - with deliberate
   variety to exercise the machinery: randomized lengths, occasional
   `finish_reason:"length"` cuts (exercises S1 continuation), occasional
   `[[GW-SKILL]]` / shattered-marker echoes (exercises the scrubber),
   occasional slow/trickling streams (exercises timeouts and the grace
   chooser), occasional hedging opens (exercises refusal-silencing on
   takeover paths). ZERO abliteration spend; the FULL specialist path
   still gets tested.
3. **The hub on the gx10 (port :9100):** `~/soak/hub_env.sh` pins
   PRIMARY/worker = REAL Hive (DEEP/GLM, real keys on the box), and
   SPECIALIST/FALLBACK = `http://localhost:4100` (the mock). The 12
   chains resolve exactly as in production.

## S2 - The continuous loop (`~/soak/soak_loop.py`)
One PASS = the full cycle, repeated forever with a cool-down:

1. **RUN** the probe matrix against the local hub (:9100) with the
   CURRENT corpus; record per-request JSONL + `/healthz` counter deltas
   (the efficiency matrix methodology).
2. **EVALUATE:** per-chain efficacy, true-upstream efficiency (waste
   ratio, tok/correct), contribution split (helm/middle/specialist),
   marker leaks, refusals shipped, errors, deadlocks/timeouts.
3. **GROW the corpus:** every pass adds probes - (a) parameterized
   variants of the 28 seed classes (new numbers, subjects, formats,
   lengths), (b) failure-derived probes (re-ask the classes that
   failed last pass, with harder variants), (c) the corpus registry
   persists in `~/soak/corpus.json` and only ever grows.
4. **TINKER (one knob per pass, data-driven):** read the pass's metrics;
   adjust ONE knob toward the objective (efficacy up, waste down, middle
   contribution >= 30%, zero defects): RACE_GRACE_MS,
   RACE_PEER_MIN_CHARS / RACE_PEER_MAX_WAIT_MS, COMMIT_TOKENS,
   RACE_PEER_LEARNING, budgets. Every change is logged to
   `~/soak/tinker_log.jsonl` with the measured before/after; regression
   => auto-revert; the best-known config is kept in
   `~/soak/best_config.json` and re-applied on boot.
5. **THE FLAWLESS CHECK (the loop's reason to exist):** a pass is CLEAN
   only when BOTH hold - (a) ZERO defects (no error record, no marker
   leak, no refusal shipped, no stall/timeout), and (b) ZERO improvement
   opportunities: every objective metric at or past its target (efficacy
   >= 0.85 mean chain score, waste <= 5x on every chain, middle
   contribution >= 30% on hedge chains, TTFT medians inside the band),
   AND the tinker proposes NO knob change (no metric off-target), AND
   the corpus growth added no failure-derived probe (nothing failed to
   derive harder probes from). Anything short of clean feeds the next
   pass: defects get fixed, off-target metrics get a tinker, failures
   grow the corpus. The loop REFINES until a full pass finds nothing
   that can be improved and no errors - then it writes
   `~/soak/FLAWLESS.txt` (pass number, the evidence table, the final
   config, the corpus size) and drops to a low-rate sentinel (one pass
   per hour, watching for regressions; any regression un-declares and
   the full loop resumes).
6. **ERROR LOOP (aggressive):** any defect (error record, marker leak,
   refusal shipped, stall) dumps full diagnostics to
   `~/soak/defects/<ts>-<class>/` (request, stages, content, hub log
   tail, metric snapshot) + appends to `~/soak/defects/INDEX.md`.
   Known-safe auto-fixes apply immediately; unknown defects carry a
   repro snippet for the next operator session.
6. **BUDGET GUARD:** per-pass and per-day real-token caps enforced from
   the upstream-char counters; exceeding them pauses the loop (never a
   runaway) and writes `~/soak/BUDGET_PAUSE.txt`.
7. **REPORT:** every pass appends a one-page delta to
   `~/soak/report.txt` (pass number, corpus size, efficacy, waste,
   contribution split, defects, the tinker decision).

## S3 - Restart survivability (the hard requirement)
- **Two systemd USER services on the gx10:**
  `soak-hub.service` (uvicorn proxy_gateway:app on :9100 with hub_env,
  `Restart=always`) and `soak-loop.service` (the loop,
  `Restart=always`, `After=soak-hub.service`).
- `loginctl enable-linger nick` - user services run with NO ssh session.
- The gx10 reboots => systemd brings BOTH services back automatically;
  the loop resumes at the next pass with the persisted corpus and the
  best-known config. The PC reboots => nothing changes at all.
- **PC role = observer:** `evals/soak_report.ps1` (ssh + tail
  report.txt / defects INDEX) and `evals/pull_soak.ps1` (rsync results
  back, whenever the PC happens to be up).
- **Code updates:** rerun `deploy_soak.ps1` + `ssh gx10 systemctl
  --user restart soak-loop` only when the operator wants a new code
  revision under test.

## S4 - Verification (the flawless declaration)
- Pass 1 runs live while we watch; report format reviewed.
- The rig runs unattended and REFINES IN LOOP until **one full pass finds
  nothing that can be improved and no errors** (the flawless check in
  S2.5) - that pass writes `~/soak/FLAWLESS.txt` with the evidence
  table, the final config, and the corpus size, and the rig drops to the
  low-rate sentinel. Any later regression un-declares and the full loop
  resumes.
- A deliberate gx10 reboot test: services return, the loop resumes, no
  data loss. A deliberate PC shutdown test: nothing on the gx10 changes.

## S5 - Cost shape
- DEEP/GLM: REAL Hive tokens, budget-capped (the operator's accepted
  "token wasted testing" spend; the caps keep it bounded).
- Abliteration: ZERO (mocked).
- gx10 local models: free.
- The PC: zero runtime cost.
