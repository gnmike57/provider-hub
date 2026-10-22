# Machine integration record (what is pre-wired on this machine)

Every tool below was **actually configured and verified** on this Windows machine on 2026-10-15.
NanoGPT is wired in two ways per tool where supported:
1. **MCP tools** — the `@nanogpt/mcp` server (34 tools: chat, vision, images, video, 3D, audio,
   web search, scraping, social/maps, Hunter enrichment, catalogs).
2. **OpenAI-compatible provider** — model calls via `https://nano-gpt.com/api/v1`.

## Integration status

| Tool | MCP wired | Provider wired | Config file | Verified |
|---|---|---|---|---|
| **Codex CLI** | ✅ | — | `~/.codex/config.toml` | `codex mcp get nanogpt` → stdio, enabled |
| **Claude Code** | ✅ | — | `~/.claude.json` (`mcpServers`) | JSON valid, `nanogpt` present |
| **OpenCode** | ✅ | ✅ | `~/.config/opencode/opencode.json` + `~/.local/share/opencode/auth.json` | providers `nano-gpt` added (kept 4 existing), 6 starter models |
| **Cline** | ✅ | — | `%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` | JSON valid |
| **Roo Code** | ✅ | — | `%APPDATA%/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json` | JSON valid |
| **Kilo Code** | ✅ | — | `%APPDATA%/Code/User/globalStorage/kilocode.kilo-code/settings/mcp_settings.json` | JSON valid |
| **Cursor** | ✅ | — | `~/.cursor/mcp.json` | JSON valid |
| **Gemini CLI** | ✅ | — | `~/.gemini/settings.json` | JSON valid (`trust: true`) |
| **Grok CLI** | ✅ | ✅ | `~/.grok/config.json` | JSON valid |
| **Droid (Factory)** | ✅ | ✅ | `~/.factory/config.json` | JSON valid |
| **Command Code** | ✅ | ✅ | `~/.command/config.json` | JSON valid |
| **CodeBuddy** | ✅ | ✅ | `~/.codebuddy/config.json` | JSON valid |
| **Project root** | ✅ | — | `./.mcp.json` (any cwd-aware tool) | JSON valid |

**13 config files, 13/13 valid JSON, 13/13 contain the nanogpt MCP block.**

## Commands actually run

```bash
# MCP server (global install + on-demand via npx)
npm install -g @nanogpt/mcp

# Codex registration (Windows npx shim requires cmd /c)
codex mcp add nanogpt --env NANOGPT_API_KEY=K -- cmd /c "C:\Program Files\nodejs\npx.cmd" -y @nanogpt/mcp

# A2A Python dependencies
pip install "a2a-sdk[http-server]>=1,<2" openai uvicorn fastapi
```

## Verification results (live)

| Check | Result |
|---|---|
| MCP handshake via client-config command shape (`npx -y @nanogpt/mcp`) | ✅ `nanogpt-mcp v1.5.0`, protocol `2025-11-25` |
| MCP `tools/list` | ✅ **34 tools** |
| MCP `tools/call nanogpt_list_text_models` | ✅ "Found 651 text model(s)" |
| MCP `tools/call nanogpt_get_balance` | ✅ live balance returned |
| OpenAI-compatible provider path (`nano-gpt.com/api/v1`) | ✅ real chat completion returned |
| A2A starter (`setup/a2a_server_starter.py`) | ✅ imports, mounts 20 routes |
| All 13 configs JSON-valid | ✅ 13/13 |
| NanoGPT MCP present in all configs | ✅ 13/13 |

## Provider entry written (OpenCode + OpenAI-compatible tools)

```json
"nano-gpt": {
  "npm": "@ai-sdk/openai-compatible",
  "name": "NanoGPT",
  "options": { "baseURL": "https://nano-gpt.com/api/v1" },
  "models": {
    "anthropic/claude-sonnet-5.5": { "name": "Claude Sonnet 5.5" },
    "anthropic/claude-opus-5.5":   { "name": "Claude Opus 5.5" },
    "openai/gpt-6.1-sol":          { "name": "GPT 6.1 Sol" },
    "deepseek/deepseek-v4-pro":    { "name": "DeepSeek V4 Pro" },
    "google/gemini-flash-latest":  { "name": "Gemini Flash Latest" },
    "minimax/minimax-m2.7":        { "name": "MiniMax M2.7" }
  }
}
```
OpenCode `auth.json` entry: `{"nano-gpt": {"type": "api", "key": "..."}}`.
Existing providers in each file were **preserved** (e.g. OpenCode kept `cyberhub`, `gx10`,
`111-gx10`, `hive-ai`). Existing `model` selections were left untouched.

## MCP block written (all MCP-capable tools)

```json
"nanogpt": {
  "command": "cmd",
  "args": ["/c", "C:\\Program Files\\nodejs\\npx.cmd", "-y", "@nanogpt/mcp"],
  "env": { "NANOGPT_API_KEY": "..." }
}
```
(Non-Windows clients use `"command": "npx", "args": ["-y", "@nanogpt/mcp"]`.)

## Cline-specific note

The docs' Cline setup is **UI-based** (Settings → Custom Model → OpenAI Compatible →
Base URL `https://nano-gpt.com/api/v1/`). No CLI config file exists for the model provider, so
that step is manual. The MCP half is pre-wired in `cline_mcp_settings.json`. The docs also note a
legacy streaming tip: if `thinking` output doesn't show, switch Base URL to
`https://nano-gpt.com/api/v1legacy/`.

## Not configurable from here (external / UI-only)

| Tool | Why | What's needed |
|---|---|---|
| SillyTavern, RisuAI, OpenWebUI, TypingMind, LibreChat, JanitorAI | web UIs — connection settings live in their server/UI | paste Base URL `https://nano-gpt.com/api/v1/` + key in their UI |
| n8n | env-var / UI config of an n8n instance | set OpenAI node base URL to `https://nano-gpt.com/api/v1` |
| OpenHands, OpenClaw | not installed on this machine | install, then use the MCP block above |
| Fluent (macOS) | macOS-only app | n/a on Windows |
| Chrome extension | browser install | install from the web app |
| WebMCP | browser feature | WebMCP-capable browser on a NanoGPT chat page |
| OAuth PKCE / device login | needs a browser + account | `GET /auth.md` flows |
| Partner auth | needs a partner account | partner dashboard |

## Cline MCP set + a real Windows bug found & fixed (verified)

Cline now carries the **complete union** of MCP servers across all tools: `nanogpt` (34 tools),
`idea` + `rustrover` (HTTP IDE-bridge servers, ports 64342/64522).

Two genuine launch bugs were found by boot-testing the real command (not just writing the file):

1. **The docs' pinned path `C:\Program Files\nodejs\npx.cmd` does NOT exist** on WinGet-installed
   Node. Every config inherited that broken path. The real npx lives under
   `~\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS...\npx.cmd`.
2. **Bare `npx` fails without a shell** (`WinError 2`) — it is a `.cmd` shim. MCP clients spawn
   `command`+`args` with **no shell**, so `command: "npx"` does not boot.

**Fix applied to all 13 configs:** `command` = the **full resolved `npx.cmd` path**, `args` =
`["-y","@nanogpt/mcp"]`. Verified to boot via **direct argv** (the exact client spawn model):
`nanogpt-mcp v1.5.0`, 34 tools. Do **not** use `cmd /c` or bare `npx` on Windows.

## Security

The API key is stored in each tool's config (that is what "pre-wired" requires). The **skill folder
contains no real key** — verified by `sources/verify_skill.py` section 11. To de-wire:
`codex mcp remove nanogpt`, and remove the `nanogpt` entries from the files listed above.