# NanoGPT key system (Windows)

`nanogpt-key.ps1` is the bridge between NanoGPT's **management plane** and its
**inference plane**, and it is what makes sure a normal `sk-nano-…` inference
API key lives in the **Windows (HKCU) environment** so every tool picks it up.

## The two credential planes (never mix them)

| Plane | Credential | talks to | can do | cannot do |
|---|---|---|---|---|
| Management | `sk-nano-mgmt-<uuid>.<secret>` | `https://nano-gpt.com/api/management/v1` | list / read / create / update / **revoke** inference keys | run models, spend balance |
| Inference | `sk-nano-<uuid>` | `https://api.nano-gpt.com` | run models, spend balance | call the Management API |

The management token is the **root**: it can mint, rotate, and delete the
normal inference keys that everything else uses.

- Management token: `NANOGPT_MGMT_API_KEY` (HKCU, scopes `api_keys:read` + `api_keys:write`)
- Inference key: `NANOGPT_API_KEY` (and `NANOGPT_API_KEY_HUB`) — written here by `sync`

Create the management token once at
<https://nano-gpt.com/settings#management-api-tokens> and store it as a
**user** environment variable:

```powershell
[Environment]::SetEnvironmentVariable(
    'NANOGPT_MGMT_API_KEY', 'sk-nano-mgmt-<uuid>.<secret>', 'User')
```

## Usage

```powershell
# 1. Report state (changes nothing)
powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 status

# 2. Make sure NANOGPT_API_KEY (+ _HUB) in HKCU holds a valid inference key,
#    and align .mcp.json with it. Idempotent — safe to re-run.
powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 sync

# 3. Mint a brand-new key, persist it, and (with -RevokeOld -Yes) delete the old one
powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 rotate -RevokeOld -Yes

# 4. Revoke a specific managed key by id (refuses without -Yes; refuses to
#    delete the key the environment currently uses unless -Force)
powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 revoke -KeyId 245159 -Yes
```

### Useful flags

| Flag | Effect |
|---|---|
| `-KeyName <name>` | Name given to keys created by `sync`/`rotate` (default `nanogpt-env`) |
| `-TargetEnvVars A,B` | Env vars written with the inference key (default `NANOGPT_API_KEY,NANOGPT_API_KEY_HUB`) |
| `-ExportProviderHub` | Also set `REASONER_API_KEY` + `SPECIALIST_API_KEY` (provider-hub tier bindings) |
| `-McpJson <path>` / `-SkipMcpJson` | Control the MCP config alignment |
| `-Force` | `sync`: mint even if a valid key exists. `revoke`: delete the live key anyway |
| `-ManagementKey <token>` | Pass the management token directly (default: read `NANOGPT_MGMT_API_KEY`) |

## Windows gotcha

`SetEnvironmentVariable(...,'User')` writes HKCU and broadcasts
`WM_SETTINGCHANGE`, but **only processes started afterwards** see the new
value. After `sync`/`rotate`, **restart your terminal and any IDE MCP
servers** — already-running shells keep the stale key.

## Hardening built in

- **Plane separation enforced locally** — the script validates the management
  token shape (`sk-nano-mgmt-…`) and refuses a plain inference key, and vice
  versa when writing `.mcp.json`.
- **HTTPS-only** — refuses to send the token over a non-HTTPS URL.
- **Header-only auth** — the token is never placed in a URL.
- **Secrets masked** — console output shows only `prefix…last4`.
- **Atomic, backed-up `.mcp.json` writes** — `.bak` + `.tmp` + `File.Replace`,
  and the file is only touched if it parses as JSON.
- **Idempotent creation** — `sync` uses a stable `Idempotency-Key` per key
  name so retries replay instead of minting duplicates; `rotate` uses a fresh
  GUID so it always produces a new key.
- **Persist-before-revoke** — `rotate` writes HKCU before deleting the old key.
- **Live-key guard** — `revoke` refuses to delete the key the environment
  currently depends on unless `-Force`.
- **Input validation** — key ids are numeric (no path traversal), env var
  names are validated, key names follow the API's 1–120 char rule.

## Sources

- <https://docs.nano-gpt.com/api-reference/management-api>
- <https://nano-gpt.com/management-openapi.json>
- <https://docs.nano-gpt.com/api-reference/authentication>
