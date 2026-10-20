# tars-hybrid-router (gx10, port 4001)

LiteLLM proxy that puts **abliterated-model-large-v2 (GLM-5.3, text-only,
1M ctx) behind EVERY TARS surface** - the operator directive is
"V2 LARGE MODEL FOR ALL":

| Surface | Model it requests | How vision is served |
|---|---|---|
| Agent TARS CLI (dom mode) | `abliterated-model-large-v2` | DOM text snapshots - no images needed |
| Agent TARS CLI (hybrid mode) | `abliterated-model-large-v2` | bridge captions screenshots |
| UI-TARS Desktop (Browser Operator) | `abliterated-model-large-v2` | bridge captions screenshots |
| Planner / any other client | `abliterated-model-large-v2` (alias `tars-hybrid`) | bridge if images present |

## Why a bridge

`abliterated-model-large-v2` on api.abliteration.ai is **text-only**: any
request carrying image content returns HTTP 400. UI-TARS Desktop (and Agent
TARS hybrid mode) send base64 screenshots every step. `vision_bridge.py`
(a LiteLLM `async_pre_call_hook` callback) rewrites image parts into
structured text captions - with element coordinates normalized 0-1000 - so
the text-only flagship still emits clickable actions:

    screenshot -> vision sensor caption (structured text + coords) -> V2 large

The **vision sensor is not the brain**. Sensor chain (first success wins):
1. local: `gemma3-27b-heretic-vl` on the gx10 llm-hub (`127.0.0.1:4000`,
   no auth) - keeps ALL Abliteration.ai spend on V2 large.
2. remote: `abliterated-model` on api.abliteration.ai - only if the local
   sensor is down.

## Endpoints

- From the gx10 itself: `http://127.0.0.1:4001/v1`
- From the tailnet: `http://gx10.ayu-sidewinder.ts.net:4001/v1`
  (also `http://100.67.13.78:4001/v1`)
- LAN alias (Caddy): `http://tars.local/v1` (if the Caddy block was added)

`/v1/chat/completions`, `/v1/responses`, `/v1/models`, `/health/liveliness`.
Models: `abliterated-model-large-v2`, `tars-hybrid` (alias),
`abliterated-model` (multimodal passthrough, debugging only).
Auth: the LiteLLM master key **equals the `ak_` Abliteration.ai key** every
client already sends (VLM API KEY / model.apiKey) - one secret everywhere.

**Port note:** the operator runbook says 4000, but on the gx10 port 4000 is
the existing local model hub (`llm-hub.service`); the router takes **4001**.

## Files

| File | Purpose |
|---|---|
| `litellm_config.yaml` | model list + callback registration |
| `vision_bridge.py` | the modality bridge callback |
| `router.env` | API key + bridge knobs (chmod 600) |
| `litellm-router.service` | systemd user unit (source of truth) |
| `deploy.sh` / `install-service.sh` / `verify.sh` | lifecycle |

## Operations

```bash
systemctl --user status litellm-router        # health
systemctl --user restart litellm-router       # restart
journalctl --user -u litellm-router -f        # logs (bridge lines: [vision-bridge HH:MM:SS])
bash /home/nick/tars-litellm-router/verify.sh # full verification
```

Runs as a **systemd user service** with `linger` already enabled for `nick`
(`loginctl show-user nick -p Linger` -> `Linger=yes`), so it survives logout
and starts at boot without a login session. Sandbox: `NoNewPrivileges`,
`ProtectSystem=full`, `ProtectHome=read-write`, `Restart=always`.

## Key rotation

`router.env` holds the `ak_...` Abliteration.ai key. After rotating the key
in the Abliteration.ai Console, update `router.env` and
`systemctl --user restart litellm-router`. The key is also in the Windows
TARS configs (provider-hub/tars/) - rotate those too.
