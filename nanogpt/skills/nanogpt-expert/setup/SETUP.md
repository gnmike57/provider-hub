# Installation & configuration (everything that needs a dependency)

Everything below was **actually installed and run on this machine**. Version pins reflect what worked.

## 0. Prerequisites (already present here)
| Tool | Version here | Needed for |
|---|---|---|
| Node.js + npm/npx | v24.19.0 / 11.17.0 | MCP server (`@nanogpt/mcp`) |
| Python | 3.12.10 | A2A server, OpenAI client |
| pip | 26.2.1 | Python deps |
| git | 2.55.0 | optional |

## 1. NanoGPT MCP server (primary agent surface)
```bash
# Option A: run on demand (no install) — npx downloads it
npx -y @nanogpt/mcp

# Option B: install globally (done on this machine)
npm install -g @nanogpt/mcp
```
Verified result: `npm install -g @nanogpt/mcp` → 98 packages.

### Register with Codex (done here, Windows)
```bash
codex mcp add nanogpt --env NANOGPT_API_KEY=YOUR_KEY -- cmd /c "C:\Program Files\nodejs\npx.cmd" -y @nanogpt/mcp
codex mcp get nanogpt     # verify
```
**Windows gotcha:** `npx` is a `.cmd` shim, so it must run through `cmd /c "...\npx.cmd"`.
Registered here and confirmed via `codex mcp get nanogpt` (transport `stdio`).

### Register with Claude Code
```bash
# macOS/Linux
claude mcp add nanogpt --scope user --env NANOGPT_API_KEY=YOUR_KEY -- npx -y @nanogpt/mcp
# native Windows
claude mcp add nanogpt --scope user --env NANOGPT_API_KEY=YOUR_KEY -- cmd /c "C:\Program Files\nodejs\npx.cmd" -y @nanogpt/mcp
```

### JSON-configured clients (Cline, Cursor, Claude Desktop)
Copy `mcp.client.json` into your client's MCP config (`.mcp.json` / settings), set the key.
```json
{ "mcpServers": { "nanogpt": {
  "command": "npx", "args": ["-y", "@nanogpt/mcp"],
  "env": { "NANOGPT_API_KEY": "YOUR_NANOGPT_API_KEY" } } } }
```

**Security note (CONFIRMED on this machine):** `codex mcp add` wrote the key in **plaintext** to
`~/.codex/config.toml` (the `NANOGPT_API_KEY` line). The skill folder itself stores **no** real key.
Rotate the key and/or run `codex mcp remove nanogpt` if you do not want it persisted on disk.
If that's a concern, put the key in an env var your shell loads and re-add, or rotate the key after.

## 2. MCP env vars (pre-config)
| Variable | Purpose | Default |
|---|---|---|
| `NANOGPT_API_KEY` | **required** | — |
| `NANOGPT_BASE_URL` | API base | `https://nano-gpt.com` |
| `NANOGPT_AUTH_MODE` | `bearer`/`x-api-key`/`both` | `bearer` |
| `NANOGPT_LOG_LEVEL` | `debug`/`info`/`warn`/`error` | `info` |
| `NANOGPT_TIMEOUT_MS` | timeout | `120000` |
| `NANOGPT_MAX_RETRIES` | retries | `0` |
| `NANOGPT_DEFAULT_MODEL` | chat default | — |
See `env.example`.

## 3. A2A server (Python)
```bash
pip install "a2a-sdk[http-server]>=1,<2" openai uvicorn fastapi
# or: pip install -r setup/requirements.txt
export NANOGPT_API_KEY=YOUR_KEY
uvicorn a2a_server_starter:app --host 127.0.0.1 --port 8000
```
Verified here: `a2a-sdk 1.2.2` installed and `setup/a2a_server_starter.py` imports and builds a
FastAPI app with 20 routes (`/.well-known/agent-card.json`, `/message:send`, `/tasks/*`, …).

### a2a-sdk 1.2.2 API — the published docs snippet is WRONG for this version
The `/integrations/a2a` guide uses a different SDK surface. Real 1.2.2 layout (verified by import):
- **Types are protobuf, not pydantic.** `AgentCard.DESCRIPTOR.fields`, not `model_fields`.
- **No `a2a.server.apps.A2AStarletteApplication`.** Use
  `a2a.server.routes.fastapi_routes.add_a2a_routes_to_fastapi` with route factories:
  ```python
  from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
  add_a2a_routes_to_fastapi(
      app,
      agent_card_routes=create_agent_card_routes(agent_card),
      jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
      rest_routes=create_rest_routes(handler),
  )
  ```
- **`DefaultRequestHandler` (= `DefaultRequestHandlerV2`) requires `agent_card=`**:
  `DefaultRequestHandler(agent_executor=..., task_store=InMemoryTaskStore(), agent_card=agent_card)`.
- **Errors:** no `a2a.utils.errors.ServerError`. Use `A2AError` base / `InternalError`.
- **Enums:** `Message` role is `ROLE_USER`/`ROLE_AGENT` (ints 1/2); `TaskState` is
  `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, etc. (not `TaskState.completed`).
- **AgentCard fields:** `supported_interfaces=[AgentInterface(url=..., protocol_binding=...,
  protocol_version=...)]` — not `url=`/`preferred_transport=`/`supports_authenticated_extended_card=`.
- `AgentCapabilities` fields: `streaming`, `push_notifications`, `extensions`, `extended_agent_card`
  (no `state_transition_history`).
`setup/a2a_server_starter.py` is written against the **real** API and is import-verified.

## 4. OpenAI client (used by both A2A starter and ad-hoc scripts)
`openai`, `requests`, `httpx`, `uvicorn` were already installed. `pip install openai` if missing.

## 5. Verification performed
- **MCP live:** spawned `@nanogpt/mcp` and completed a real MCP `initialize` + `tools/list` +
  `tools/call`. Server `nanogpt-mcp v1.5.0`, protocol `2025-11-25`, **34 tools**, and
  `nanogpt_get_balance` returned a live balance.
- **A2A import:** `setup/a2a_server_starter.py` imports and mounts 20 routes.

## 6. Things that are NOT installable here (external)
- **WebMCP** — browser feature; needs a WebMCP-capable browser on a NanoGPT chat page.
- **OAuth PKCE / device login** — need a browser redirect and your NanoGPT account.
- **Browser extension / Chrome extension** — install from the web app.
- **Partner auth** — requires a partner account.

## 7. Install the skill into Cline (discovery path)

The skill source of truth is `skills/nanogpt-expert/`. Cline only discovers skills that live under a
`.cline/skills/<name>/` directory, so this project exposes it there via a **directory junction**
(no copy — one source of truth, no drift):

```powershell
# from the project root (C:\Users\lnxzf\Desktop\projects\nanogpt)
New-Item -ItemType Junction -Path .cline\skills\nanogpt-expert -Target (Resolve-Path .\skills\nanogpt-expert)
```

Verified: `.cline\skills\nanogpt-expert` resolves to `skills\nanogpt-expert`, and the skill loads by
name (`nanogpt-expert`) in Cline. A plain copy also works but duplicates ~3.6 MB and can silently
drift out of sync — prefer the junction.

## 8. Install command cheat-sheet
```bash
npm install -g @nanogpt/mcp                                  # MCP server
pip install "a2a-sdk[http-server]>=1,<2" openai uvicorn fastapi   # A2A server
codex mcp add nanogpt --env NANOGPT_API_KEY=K -- cmd /c "C:\Program Files\nodejs\npx.cmd" -y @nanogpt/mcp
claude mcp add nanogpt --scope user --env NANOGPT_API_KEY=K -- npx -y @nanogpt/mcp
uvicorn a2a_server_starter:app --port 8000                    # run A2A server
```