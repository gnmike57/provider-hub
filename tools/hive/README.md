# Hive (thehive.ai) as a provider

Verified 2026-10-07 against the live API. This is the recipe for using Hive's
self-hosted LLMs as a **primary** (or as a harness provider).

## The verified recipe

| Setting | Value |
| --- | --- |
| Base URL | `https://api-cdn.thehive.ai/api/v3` (VA1 region: `https://api-va1.thehive.ai/api/v3`) |
| Endpoint | `POST /chat/completions` |
| Auth | `Authorization: Bearer <HIVE_SECRET_KEY>` - the **SECRET** key |
| Models | `deepseek-ai/deepseek-v4.1-flash`, `zai-org/glm-5.3-flash` |
| Shape | OpenAI chat-completions; SSE streaming; `reasoning_content` in deltas; tool calling per model |
| Limits | 5 req/s default; 405 when the org balance is empty |

Wrong values that look plausible (all three were in the retired `theinvite`
configs): base `https://api.thehive.ai/v1` (404), the **access** key (401), and
model `thehive-chat` (does not exist). `/v1/models` does not exist either -
probe `/chat/completions` instead.

## Files

| File | Purpose |
| --- | --- |
| `setup_cline_opencode.py` | writes the Hive provider into the Cline CLI provider store and the opencode config (idempotent; reads the key from `ufo.env`, never prints it) |
| `opencode_v2_schema.py` | rewrites `~/.config/opencode/opencode.json` in opencode v2's normalised schema (`providers`/`package`/`settings`), keeping the local hub providers |
| `gx10_selftest.sh` | run on the box: plain + streaming call for both models, reading the key from `~/ufo-galaxy/hive_cleanpass/ufo.env` |

```powershell
python tools/hive/setup_cline_opencode.py
Get-Content tools/hive/gx10_selftest.sh -Raw | ssh flak3dd@gx10-tailscale 'bash -s'   # needs LF line endings
```

## Harness caveats found while wiring this (not Hive bugs)

* **Cline CLI 3.0.65**: headless `cline "<prompt>"` fails for *every* provider
  with `hook dispatch failed: session.hook requires a valid hook event
  payload` (reproduced with no provider flags, no hooks dir, no hook setting).
  The `hive` provider is configured and selectable from the app/TUI; only the
  headless path is broken.
* **opencode 2.0.10 / 2.0.24**: providers written in `opencode.json` yield
  `provider.no-route` - including pre-existing custom providers such as
  `111-gx10`, so this is not Hive-specific - and a run without `-m` falls back
  to the OpenCode Console/OpenRouter catalogue (returned a 402 quota error).
  opencode's own docs say providers are added with the interactive `/connect`
  command (credentials land in `~/.local/share/opencode/auth.json`), then
  `/models` to pick one. Config is written and correct; the interaction step
  needs a keyboard.
* **gx10 DNS**: `/etc/resolv.conf` points at the systemd-resolved stub
  `127.0.0.53`, and `systemd-resolved` was `failed` - every DNS lookup on the
  box died (`curl` -> `000` while `https://1.1.1.1` worked). Fixed with
  `sudo systemctl reset-failed systemd-resolved && sudo systemctl restart
  systemd-resolved`; no `/etc/hosts` pin was needed. A pin to
  `18.64.50.114` (CloudFront) is the fallback if it regresses.

## Rotate before sharing

The secret key was printed in plaintext during setup, so rotate it at
<https://thehive.ai/explore?api_keys=1> and re-run
`setup_cline_opencode.py` plus the `ufo.env` / gx10 updates.
