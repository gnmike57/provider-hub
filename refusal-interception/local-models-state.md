# Local model state — GX10 (NVIDIA GB10 DGX Spark)

Snapshot: **2026-10-05** · host `gx10` · LAN `192.168.4.103` · tailnet `gx10.tail930ca4.ts.net`

---

## 1. What is serving right now

| Endpoint | Service | Model(s) | Status |
|---|---|---|---|
| `http://127.0.0.1:8900/v1` | `cyberfrost.service` (TabbyAPI + exllamav3 fork `047ce72`) | `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw` | **active**, 85.6 GB VRAM, Restart=always |
| `http://127.0.0.1:4000/v1` | `llm-hub` (flak3dd user unit, `/srv/apps/ufo-galaxy/llm_hub.py`) | local probe + 18 Featherless cloud aliases | **active** (watchdog-healed) |
| `http://0.0.0.0:11434` | `ollama serve` (user flak3dd) | Llama-3.3-70B-abliterated Q4_K_M, Nemotron-3-Nano-30B PRISM IQ4_XS | up, nothing loaded |
| `http://cyber.local:4000/v1` | Caddy (`abliterated-proxy`) -> hub | alias `cyber`, `cyberfrost`, `cyber.local` | works |

The **hub on :4000 is the front door** — everything (qwen.local, venus.local, defiant.local,
fast.local, stack.local, unsloth.local, abliterated.local) reverse-proxies through it.

**CYBER-FROST notes:** thinking is always on; it emits `delta.reasoning_content`
(ExLlamaV3 convention, *not* vLLM's `delta.reasoning`). Its DEPLOY.md warns that low
temperatures collapse speculative-draft acceptance — **use temperature 1.0**, not 0.1/0.0.

---

## 2. What is NOT running (and why)

The vLLM qwen stack and the :8080 gateway were **deliberately retired on 2026-10-04**
(recorded in the live Caddy `/api/system/status` payload and `/opt/SYSTEM.md`).

| Port | Former role | State |
|---|---|---|
| 8000 | vLLM qwen25-vl-7b | retired |
| 8002 | vLLM ui-venus | retired |
| 8004 / 8005 | vLLM qwen stack | retired |
| 8006 | vLLM qwen36-35b-a3b | retired; **port reassigned to the Windows VM** |
| 8080 | spark-gateway | retired |

---

## 3. Fixes applied this session

| # | Problem | Fix |
|---|---|---|
| 1 | Hub probed retired ports incl. **:8006**, now owned by the `windows-sandbox` VM (dockurr/windows web console) — stale probes against an unrelated service | `LLM_HUB_UPSTREAMS=8900` in `/home/flak3dd/.config/llm-hub.env` (backed up); hub restarted, catalog verified (19 ids) |
| 2 | Retired vLLM profile still squatted on :8006, a latent collision with the Windows VM (`restart: unless-stopped`) | `/srv/models/profiles/qwen36-35b-a3b.env` `PORT=8006 -> 8007` (backed up) |
| 3 | **Real defect:** gateway + hedge only recognised `delta.reasoning` (vLLM), so the live engine's `delta.reasoning_content` chunks were *held* instead of forwarded — destroying TTFT on thinking models | Both modules now accept `delta.reasoning` **or** `delta.reasoning_content` |
| 4 | Refusal-interception suite targeted the retired `:8000` | Repointed to the hub `:4000` + `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw`; temperature default 1.0 |

**Result:** live suite **10/10**, Tinfoil end-to-end **8/8**, full run `ALL SUITES PASSED`.

---

## 4. Port map (profiles)

```
8000  qwen25-vl-7b (retired)     8003  omniparser        8900  CYBER-FROST  [LIVE]
8001  qwen38-27b-train           8005  qwen3-0.6b        4000  llm-hub      [LIVE]
8002  ui-venus (retired)         8007  qwen36-35b-a3b    8080  spark-gateway (retired)
```

---

## 5. How to call it

```bash
curl -s http://127.0.0.1:4000/v1/models                      # live catalog (local + cloud)
curl -s http://127.0.0.1:4000/health                          # hub health
curl -s http://cyber.local:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"cyber","messages":[{"role":"user","content":"hi"}],"temperature":1.0}'
```

Local ids: `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw` (aliases `cyber`, `cyberfrost`, `cyber.local`).
Cloud aliases (18): `coder32b-abl`, `cyber35b`, `deepseek-v4-pro`, `gemma3-27b-heretic-vl`,
`gpt-oss-120b`, `heretic70b`, `k2-375b`, `qwen2.4t`, `qwen3-coder-480b`,
`qwen3.5-27b-claude-os`, `qwen3.6-35b-a3b`, `qwen3.8-flash-next`, `qwen397b`, `unc70b`, `unc72b` …

---

## 6. Open risks

1. **`FEATHERLESS_API_KEY` sits in plaintext** in `/home/flak3dd/.config/llm-hub.env`
   (mode readable by the service user). Consider a secrets file + `EnvironmentFile` perms tightening.
2. **`windows-sandbox`** (`dockurr/windows`) maps `8006:8006` + `3389`. If it returns, it will
   reclaim 8006 — profiles no longer conflict, but Caddy's `windows.local -> 8006` is the only
   intended consumer.
3. **Stale profiles**: `qwen25-vl-7b` (8000), `ui-venus` (8002), `spark-gateway` (8080) still
   reference retired engines; `abliterated-proxy` routes to them. Harmless while the stack is off.
4. **Auto-healing is real but coarse**: `gx10-watchdog` restarted the hub mid-session. If a
   route 502s, check `systemctl --user status llm-hub` (as flak3dd) before debugging Caddy.

---

## 7. Shared-space consolidation (2026-10-05)

All shared application code now lives in the **neutral `/srv/apps`** area (root:models,
setgid) — matching the existing `/srv/models` and `/srv/unsloth` convention. Nothing
shared remains under a user home.

| Old path (now a symlink)             | Neutral location                    |
|--------------------------------------|-------------------------------------|
| /home/flak3dd/ufo-galaxy             | /srv/apps/ufo-galaxy                |
| /home/flak3dd/ufo-watchdog           | /srv/apps/ufo-watchdog              |
| /home/flak3dd/OmniParser             | /srv/apps/OmniParser                |
| /home/flak3dd/ufo-tg-runner          | /srv/apps/ufo-tg-runner             |
| /home/nick/src/*  (all entries)      | /srv/apps/*                         |
| /home/nick/qwen38-exl3               | /srv/apps/qwen38-exl3               |
| /home/nick/abliterated-proxy         | /srv/apps/abliterated-proxy         |

**LLM hub:** `/srv/apps/ufo-galaxy/llm_hub.py` (+ `llm_hub_models.json` beside it),
serving `http://127.0.0.1:4000/v1` via the flak3dd user unit `llm-hub.service`.

**CYBER-FROST specialist:** app + venv at `/srv/apps/qwen38-exl3`, config at
`/srv/apps/qwen38-exl3/state/config.yml`, serving `:8900` via `cyberfrost.service`
(editable-install `.pth` and `model_dir` both repointed).

24 references rewritten across 16 files (12 user units + drop-ins, `cyberfrost.service`,
`/opt/SYSTEM.md`, `/opt/gx10_checkpoint.sh`, `/opt/gx10_watchdog.sh`,
`/opt/gx10_sync_daemon.py`, `/opt/gx10_restore.sh`, and the checkpoint restore mirror).
Symlinks left at every old path so venv shebangs and docker compose project dirs keep
working.

**Verified:** hub `registry=/srv/apps/ufo-galaxy/llm_hub_models.json` + 19 model ids;
CYBER-FROST reloaded at 85.7 GB VRAM with Mixed-K kernels engaged; `cyber.local:4000`
resolves; `abliterated-proxy` container recreated on the neutral mount; ufo-galaxy-server/
client/linux-mcp/tunnel all active; stale-reference sweep = 0; live suite **10 passed**.

### Operational note — restarting CYBER-FROST

Do **not** `systemctl restart cyberfrost` while the old instance still holds VRAM. The unit
is `Restart=always`; a failed start raises `Insufficient VRAM in split for model and cache`
and then loops, each retry racing the previous teardown. Correct sequence:

```bash
sudo systemctl stop cyberfrost.service
while [ "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)" != 0 ]; do sleep 5; done
sudo systemctl start cyberfrost.service      # expect ~85.7 GB VRAM + Mixed-K kernel lines
```

### Deliberately NOT moved

`/home/flak3dd/windows-sandbox` — belongs to flak3dd alone (dockurr/windows compose
project containing a VM disk image).
