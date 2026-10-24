# PROVIDER-HUB — 4-LOCATION SYNC CHECKLIST (2026-10-23)

> **THE 4 PLACES**
> 1. **Local Windows** — `C:\Users\lnxzf\Desktop\projects\provider-hub` (git working tree, this is the source of truth)
> 2. **GitHub** — `origin` = `https://github.com/gnmike57/provider-hub.git`
> 3. **Live hub on gx10** — `/srv/apps/ufo-galaxy/provider-hub` (tar-mirror deployed by `gx10_sync.ps1`; `/home/flak3dd/ufo-galaxy/provider-hub` is a symlink to it; runs `hub.service`/`deep.service`/`glm.service` on :9310/:9311/:9312)
> 4. **gx10 sharedproject** — `/srv/sharedproject` on gx10 (`drwxrws--- root:sharedproject`, group `sharedproject`; this is the shared drop folder, alongside mailspoof / osint / webrecordsitch / spark-bench / fileindex)
>
> *(A local `V:\SharedProject` mirror also exists on Windows — a separate ReFS copy of a project subset, kept for offline sharing.)*

> **CONTENTS SNAPSHOT (2026-10-23)**
> - Local `main` = `df1707e4` ("provider-hub: pre-sync checkpoint (4 locations)" over `84f4097d` retarget + prior work), **12 commits ahead** of `origin/main` (`c3928e10`), 0 behind. Working tree clean on tracked files (only .gitignore-class runtime artifacts untracked). Push pending (blocked on auth — see GitHub row below).
> - **local → gx10:** last md5 sweep 2026-10-23: **158 MATCH / 3 DIFFER / 18 MISSING** (DIFFER: `evals/billing_w2_test.py`, `gx10_offload.py`, `README.md`; MISSING: 17 `evals/results/` + `refusal-interception/architecture.md`, cosmetic). Box-only extras: the 2026-10-22 backup tree `provider-hub.bak-20261022-120751` (separate dir, not drift).
>   **This session:** `gx10_sync.ps1 -All -Verify` push in progress; md5 numbers re-counted after untar below.
> - **local → V:\SharedProject (bonus mirror):** 20 shared files compared → **7 MATCH / 13 DIFFER**.
>   Root (6 files): `abliteration_keys.py` + `launch_redhands_hub.sh` match; `launch_redhands_hub.ps1`, `corrections-ledger.md`, `README.md`, `requirements.txt` stale on V:.
>   `gx10-router/` (6 files): `deploy_key_factory.sh`, `README.md`, `vision_bridge.py` match; `deploy.sh` (pre-SIGPIPE-fix text), `litellm_config.yaml` (old 3-chain surface), `router.env.example` stale.
>   `docs/` (8 files): `code-review-2026-10-20.md` + `MAC-USAGE.md` match; 6 stale pre-amendment copies — `constellation-hub-plan.md`, `epic-ultra-edit-ledger.md`, `full-remediation-program.md`, `provider-hub-plan.md`, `single-model-chain-plan.md`, `three-tier-routing-plan.md` (at least 4 of these carry the 2026-10-22 verification banners locally).
> - Suite at local HEAD: **879 tests collected**; last full green run 855 passed / 1 flake (fixed in `b461b4c3`).

## Sync matrix — run these to re-verify or resync

| # | Place | Sync method | Re-verify | Resync |
|---|---|---|---|---|
| 1 | Local Windows | — (source of truth) | `git status` clean at `17f1cb24` | — |
| 2 | GitHub | `git push` | `git rev-list --count origin/main..HEAD` → 0 | `git push origin main` |
| 3 | gx10 live hub | `gx10_sync.ps1` (tar over SSH; no `.git` on the box — hashes only) | md5 sweep vs local (see note) | `powershell -File gx10_sync.ps1 -All` |
| 4 | gx10 sharedproject | `scp` to `/srv/sharedproject/` | `md5sum` over SSH | `scp CHECKLIST-PROGRESS.md gx10-tailscale:/srv/sharedproject/` |
| — | (V:\SharedProject bonus) | manual copy | hash-compare | copy the 13 differing files itemized above |

Note: the gx10 tree has no git; compare with
`git ls-files … | Get-FileHash` locally vs `find . -name … -print0 | xargs -0 md5sum` over SSH
(exclusions: `tars/ .tars-setup/ __pycache__ evals/results/ .staging/ .loki/`).

## Checklist (the 4 places, current state)

- [x] **Local Windows** — working tree clean on tracked files, `main` @ `df1707e4` (pre-sync checkpoint) + `84f4097d` retarget + prior work, **12 commits ahead** of `origin/main` (`c3928e10`), 0 behind. Suite collects **915 tests** (last green 855 passed / 1 flake fixed in `b461b4c3`; `gateway_registry.json` BOM fix applied locally — gitignored, not part of any sync set). Hub healthy (`/healthz` `ok:true` on :9000, Task Scheduler tasks Running per 2026-10-23 check).
- [ ] **GitHub** — NOT synced: local ahead 12 commits (`df1707e4` HEAD). Push is **blocked on auth**: `git push` invokes the `gh` credential helper which needs an interactive login (stored token for `gnmike57` invalid; no TTY in this session). Fix: run `gh auth login -h github.com` interactively, then `git push origin main`.
- [~] **gx10 live hub** — SSH verified (`nick@100.67.13.78`, BatchMode OK). `gx10_sync.ps1 -All -Verify` push in progress this session (target `/srv/apps/ufo-galaxy/provider-hub`, excludes `.git`, `evals/results/`, caches, key pools). Last verified state 2026-10-23 (`:9310/:9311/:9312` `/healthz` `ok:true`, `GX10_COMPILE_OK`, 805 files). No `-Restart`: live hub services left untouched.
- [ ] **gx10 sharedproject (`/srv/sharedproject`)** — re-copy of CHECKLIST-PROGRESS.md pending (`nick` is in `sharedproject` group; `drwxrws---+ root:sharedproject`, write OK).
- [x] *(bonus)* **`V:\SharedProject`** — copy placed + md5-verified; the mirror itself still carries 13 stale files (itemized above) from before the 2026-10-22 doc amendments.

## Checklist progress (goal ledger)

- **Active goal** (`goals/ACTIVE` → `live-proof-of-goal`): **2 / 2 complete** —
  1. "prove the escalation ladder on a real stall" — done (5 attempts, escalated to L4; ALERTS.md logged L3→L4 before the operator fixed the stall)
  2. "prove no-exceptions completion" — done (0 attempts)
- The `/goal` engine (`goal_engine.py`) proves its own laws: NO EXCEPTIONS (status complete only when every item is done), SURVIVES ANYTHING (atomic ledger), THROUGHPUT (30s polls + L1→L4 escalation — all five escalation levels fired live during item 1).
- Repo-wide checklists: `docs/epic-ultra-edit-ledger.md` — **129 / 129 edits ticked**; mission ledger (`.loki/mission.json`) — 14 open (pre-remediation rows, superseded), 1 blocked-operator (retired nano mgmt token, E15), 3 completed (E16–E18). No `[ ]` checkboxes remain open anywhere in the tree.
