> **SUPERSEDED (2026-10-23):** the CYBER-FROST layout described below was
> deleted this day - the EXL3 weights, `cyberfrost.service`/`:8900` and the
> Featherless cloud lane are all gone (stale key, not to be enabled). Per the
> 2026-10-21 constellation directive the worker slot targets the constellation's
> UNCENSORED TERMINAL, Abliteration.ai `abliterated-model-large-v2` (the live hub
> is the deepseek / glm / abliteration constellation on `:9310`/`:9311`/`:9312`;
> the gx10 `:4000` llm-hub is a legacy catalog, not the hub).
> Kept as a historical record of the staged phase.


# Phase 1 (V2 brain) - STAGED 2026-10-20, Phase 3 (24/7 chassis) - LIVE

> **STATUS AMENDMENT (2026-10-22, line-by-line verification pass).** Superseded
> by the 2026-10-21 constellation directive (`docs/constellation-hub-plan.md`):
> the hub on :9000 is the CONSTELLATION hub (abliteration terminal + Hive
> helms, CONSTELLATION_ONLY=1), not the Hive/CYBER-FROST layout below, and
> `slot_bindings.json` was purged + rebuilt with the real topology by the W5
> wave. The "What is LIVE" health claim is TRUE again as of 2026-10-22 (hub
> healthy on :9000 via the SYSTEM scheduled task, after the
> `launch_frost_hub.ps1` preflight fix + Machine-scope secret seeding). The
> `v2-first` preset note below is historical: `constellations.json` (the
> constellation's own preset file) supersedes that reading.

Gate: POST https://api.abliteration.ai/v1/chat/completions with the ak_ chat key
still returns **402 insufficient_credits** (org payment_required). Per plan: stage
Phase 1, keep the LIVE hub on Hive/CYBER-FROST, make Phase 3 live.

## What is LIVE right now

- Hub :9000 serves **primary=Hive zai-org/glm-5.3-flash, worker+scout=CYBER-FROST
  @100.67.13.78:4000** (slot_bindings.json boot-restore; file byte-identical to its
  .bak-20261020-204029 backup). Verified: /healthz ok:true + a completion through
  the hub returned "PONG".
- UFO 24/7 chassis: scheduled task **UFO-FleetDaemon** (fleet/daemon_runner.py =
  UFOEventDaemon + SystemGuardian + webhook) is Running and answers
  `GET http://127.0.0.1:8765/health` with ok:true. FLEET_DAEMON.ENABLED=true in
  ufo config system.yaml; TELEMETRY.DAILY_BUDGET_USD raised 50 -> 100 (lockout and
  DLQ intact). POST /trigger accepts webhook/scheduled(cron)/manual/file_drop.
- HKCU env (User scope; takes effect for NEW processes only, the running hub is
  unaffected - it pins its own env at launch):
  - SPECIALIST_API_URL=https://api.abliteration.ai/v1/chat/completions
  - SPECIALIST_MODEL=abliterated-model-large-v2
  - SPECIALIST_API_KEY=<ak_ chat key>
  - WORKER_API_URL=http://100.67.13.78:4000/v1/chat/completions (free local fallback)
  - WORKER_MODEL=CYBER-FROST-3.8-EXL3-SAGE-3.87bpw
  - ABLITERATION_API_KEY repaired to the current chat key (was a stale ak_ value the
    gx10:4001 relay rejects - found while debugging the auto-probe).
- `v2-first` constellation preset is visible in GET /v1/constellations (dormant
  until POST /v1/constellations/apply {"name":"v2-first"}).
- UFO v2large profile wired and resolvable, NOT selected (backend_state.json still
  {"selected":"auto"}). `python scripts/switch_backend.py v2large` activates it.

## What is STAGED (files written, inert until activation)

1. gateway_registry.json: "ablit" provider (api.abliteration.ai/v1 + ak_ chat key,
   self-mapped abliterated-model-large-v2) and defaults.primary=ablit
   (worker stays cyberhub). The running hub only consults the registry for
   /v1/switch + model lists, so this is inert for live traffic; on any restart the
   slot_bindings.json boot-restore still wins (Hive).
   NOTE: self-map entries were also added for cyberhub's CYBER-FROST name so the
   v2-first preset can resolve provider+model (registry resolution requires the
   model to be exposed by the provider).
2. launch_frost_hub.ps1: PRIMARY_API_URL/KEY/MODEL and SPECIALIST_API_URL/KEY/MODEL
   now Abliteration-direct (retired-provider hop + sk-nano dropped), HEDGE_MAX_TOKENS
   4000->8192, SPECIALIST_MAX_TOKENS 4096->16384. Only takes effect at the next hub
   LAUNCH - and even then boot-restore overrides these pins while slot_bindings.json
   still ends on the Hive snapshot. Edge: if slot_bindings.json were missing at
   boot, the env pins (V2) would win and the hub would 402 - keep the file intact.
3. slot_bindings.staged-v2.json: the V2 3-slot snapshot (helm+specialist =
   V2-direct w/ ak_ key, scout = local CYBER-FROST, key "") with ts=0 placeholder
   (BindingHistory drops entries older than 7d, so activation must stamp a fresh ts).
   slot_bindings.json itself is UNTOUCHED.
4. constellations.json: "v2-first" preset (see above).
5. ufo: profiles/agents_v2large.yaml (gx10:4001 relay, 16K tokens, visual
   HOST/APP/BACKUP, text-only EVALUATION), ufo.env ABLITERATION_API_KEY,
   scripts/switch_backend.py 'v2large' mode (key-bearing gx10:4001 probe before
   selecting), llm/config_helper.py: 'v2large' allowed selection + profile mapping,
   and the auto-probe fixed from stale 127.0.0.1:4000/8000 to the gx10:4001 relay.

## ACTIVATION (when the Abliteration org is out of payment_required)

    # 1. Hub brain (one command; gates on a live 200 completion first):
    powershell -File C:\Users\lnxzf\Desktop\projects\provider-hub\activate_v2_primary.ps1
    #    - appends the staged snapshot to slot_bindings.json with a fresh ts,
    #    - restarts the hub via launch_frost_hub.ps1 -Force,
    #    - verifies /healthz shows ablit on primary+worker.
    # Rollback: POST /v1/switch {"target":"primary","rollback":true}
    #           (or delete the last slot_bindings.json line + relaunch -Force).
    #
    # 2. Optional instant flip without restart (alternative to 1):
    #    POST /v1/constellations/apply {"name":"v2-first"}
    #
    # 3. UFO brain:
    cd C:\Users\lnxzf\Desktop\projects\ufo\ufo
    .venv\Scripts\python.exe scripts\switch_backend.py v2large   # probes gx10:4001 first
    .venv\Scripts\python.exe scripts\switch_backend.py status

## Money safety

siphon.py / billing.py untouched and dormant; no charging endpoints called; the only
upstream calls made were free /v1/models probes, the 402 gate check, and one
16-token Hive completion through the live hub (normal traffic, "PONG").

Backups of every edited file: <name>.bak-20261020-204029 (both repos).
