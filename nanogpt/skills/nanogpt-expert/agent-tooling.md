# NanoGPT Agent coverage (MCP, WebMCP, A2A, tool search, adapters)

> Sources: `sources/harness__agents.html`, `sources/harness__mcp.html`, `sources/harness__a2a.html`,
> `sources/auth.md`, `sources/manifests/agent-capabilities.json` (version 2026-10-10),
> `sources/docs/api-reference__miscellaneous__mcp-server.md`, `sources/docs/integrations__mcp.md`,
> `sources/docs/integrations__cli-login.md`, `sources/docs/api-reference__miscellaneous__partner-auth.md`.
>
> Standard of truth: **MCP is the default agent surface.** API-only routes remain usable from any
> OpenAI-compatible client (agent-capabilities.json `standards.primary = "MCP"`).

## 1. The agent surface at a glance

| Layer | What it is | Source of truth |
|---|---|---|
| **MCP** | `@nanogpt/mcp` — 30+ tools for models, media, search, scrapers, enrichment | `GET /mcp` |
| **OpenAI-compatible** | chat / responses / images / audio / embeddings / models | `GET /api` |
| **auth.md discovery** | machine-readable auth + scopes from a root Markdown file | `GET /auth.md` |
| **A2A** | NanoGPT is the *model provider* for YOUR external A2A server | `GET /integrations/a2a` |
| **WebMCP** | in-browser structured tools on NanoGPT chat pages | `GET /agents` |
| **Hosted tool search** | Responses-only hosted tool-search pilot | agent-capabilities.json |

## 2. MCP — primary integration path

Package `@nanogpt/mcp`, run with `npx -y @nanogpt/mcp`, protocol target **2025-11-25**.
Source: `github.com/Nano-GPT-com/nanogpt-mcp`.

### Install
```bash
# Claude Code (macOS/Linux)
claude mcp add nanogpt --scope user \
  --env NANOGPT_API_KEY=YOUR_API_KEY -- npx -y @nanogpt/mcp

# Claude Code (native Windows - npx is a .cmd shim, launch via cmd /c)
claude mcp add nanogpt --scope user --env NANOGPT_API_KEY=YOUR_API_KEY -- \
  cmd /c "C:\Program Files\nodejs\npx.cmd" -y @nanogpt/mcp

# Codex
codex mcp add nanogpt --env NANOGPT_API_KEY=YOUR_API_KEY -- npx -y @nanogpt/mcp
```

JSON-configured clients (Claude Desktop, Cline, Cursor):
```json
{
  "mcpServers": {
    "nanogpt": {
      "command": "npx",
      "args": ["-y", "@nanogpt/mcp"],
      "env": { "NANOGPT_API_KEY": "your_api_key_here" }
    }
  }
}

### MCP tools (31 in the manifest; server exposes extras)
| Area | Tools |
|---|---|
| Account | `nanogpt_get_balance` |
| Text | `nanogpt_chat`, `nanogpt_vision`, `nanogpt_embeddings`, `nanogpt_ai_detection` |
| Images | `nanogpt_image_generate`, `nanogpt_image_edit`, `nanogpt_ai_qr` |
| Video | `nanogpt_video_generate` |
| 3D | `nanogpt_3d_generate` |
| Audio | `nanogpt_text_to_speech`, `nanogpt_music_generate`, `nanogpt_audio_transcribe` |
| Web & research | `nanogpt_web_search`, `nanogpt_scrape_urls`, `nanogpt_firecrawl`, `nanogpt_youtube_transcribe`, `nanogpt_x_research`, `nanogpt_hunter` |
| Social & maps | `nanogpt_reddit`, `nanogpt_google_maps_scrape`, `nanogpt_google_maps_reviews_scrape`, `nanogpt_facebook_ads`, `nanogpt_facebook_posts_scrape`, `nanogpt_instagram_profile`, `nanogpt_instagram_posts_scrape`, `nanogpt_instagram_reels`, `nanogpt_linkedin_profile`, `nanogpt_tiktok_scrape` |
| Catalogs (free) | `nanogpt_list_text_models`, `nanogpt_list_image_models`, `nanogpt_list_video_models`, `nanogpt_list_3d_models`, `nanogpt_list_audio_models` |

Manifest MCP status: 30 `available`, 1 planned (`nanogpt_responses`, "MCP next"). Anthropic
`/api/v1/messages`, Moderation, and Feedback are **API only** (no MCP tool).

### Key tool parameters (MCP tool reference)
- **`nanogpt_chat`**: `messages` (required), `model?`, `temperature?` (0-2), `max_tokens?`.
- **`nanogpt_get_balance`**: no params → `usd_balance`, `nano_balance`, `nanoDepositAddress`.
- **`nanogpt_image_generate`**: `prompt` (required), `model?`, `n?` (1-10), `size?`, `quality?`.
- **`nanogpt_web_search`**: `query` (required), `depth?` (`standard`/`deep`), `outputType?`
  (`searchResults`/`sourcedAnswer`/`structured`), `includeImages?`, `fromDate?`/`toDate?` (YYYY-MM-DD).
- **`nanogpt_vision`**: `messages` (required) with text + image blocks
  (`{"type":"image","source":{"type":"url","url":...}}`), `model?`, `temperature?`, `max_tokens?`.
- **`nanogpt_scrape_urls`**: `urls` (required, **max 5**), `mode?` (`scrape-page`/`conversation`), `stealthMode?`.
- **`nanogpt_video_generate`** / **`nanogpt_3d_generate`** (async): `operation?` = `submit` (default) |
  `submit_and_poll` | `poll` | `status`; `model` (required to submit); `prompt?`; `imageUrl?`/`imageDataUrl?`;
  `duration?`, `resolution?`, `aspect_ratio?`; `runId` (for `poll`/`status`); `timeout_ms?` (default **50000**).

### MCP resources
- `nanogpt://raw/{id}` — raw JSON of a previous API call.
- `nanogpt://image/{id}` — image generated this session.
- `nanogpt://media/{id}` — audio/other media this session.

### Async media job rules (video & 3D) — important
- Jobs take 30s to several minutes. `submit_and_poll` waits up to `timeout_ms` (default 50s).
- If still running you get `runId` → call again with `operation:"poll"`, or `"status"` for one check.
- **Many MCP clients cut tool calls at 60s** — keep `timeout_ms` below the client timeout, then `poll`.
- **A job is charged on submit. Poll; never re-submit** (re-submitting double-charges).

### MCP error handling
| Error | Cause | Fix |
|---|---|---|
| Invalid API key | auth failed | check `NANOGPT_API_KEY` + launch command (Windows `cmd /c`) |
| Insufficient balance | low balance | top up at nano-gpt.com |
| Rate limited | too many requests | wait and retry |
| Timeout | request too long | simplify, or raise `NANOGPT_TIMEOUT_MS` |
```

### Environment variables
| Variable | Description | Default |

## 2b. Install & verified setup

See **setup/SETUP.md** for exact install commands, versions, and everything that was installed and
run on this machine (MCP server + Codex registration, A2A Python deps). Runnable artifacts live in
setup/: 2a_server_starter.py (import-verified), mcp.client.json, 
equirements.txt, env.example.

**a2a-sdk 1.2.2 corrections (the published A2A guide targets a different SDK surface):** types are
protobuf not pydantic; use dd_a2a_routes_to_fastapi + route factories (no A2AStarletteApplication);
DefaultRequestHandler requires gent_card=; errors are A2AError/InternalError (no ServerError);
AgentCard uses supported_interfaces=[AgentInterface(...)]. Details in setup/SETUP.md section 3.

## 3. A2A (Agent2Agent) — you are the A2A server

**NanoGPT is NOT a native A2A server.** It publishes no Agent Card and accepts no A2A messages
(`standards.a2a.nativeServer = false`). The pattern: build an external A2A server that calls NanoGPT
as its OpenAI-compatible model provider. Protocol target **1.0** (1.x official Python SDK).
Guide: `https://nano-gpt.com/integrations/a2a`. This covers the A2A protocol (formerly IBM/BeeAI
ACP) — **not** the separate Agent Client Protocol used by coding editors.

Where NanoGPT fits:
1. **A2A client** discovers your Agent Card, invokes `SendMessage` over JSON-RPC or
   `POST /message:send` over HTTP+JSON.
2. **Your A2A server** validates the request and runs your agent logic.
3. **NanoGPT API** provides model inference (`https://nano-gpt.com/api/v1`).

MCP vs A2A: **MCP** when an agent needs NanoGPT tools; **A2A** when independently deployed agents
need to discover one another and delegate tasks.

Minimal model adapter (from the guide):
```python
import os
from openai import AsyncOpenAI
nanogpt = AsyncOpenAI(
    api_key=os.environ["NANOGPT_API_KEY"],
    base_url="https://nano-gpt.com/api/v1",
)
async def generate_reply(prompt: str) -> str:
    response = await nanogpt.chat.completions.create(
        model="claw-medium",   # stable alias for agent workloads
        messages=[
            {"role": "system", "content": "You are a focused remote agent."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""
```
Install: `python -m pip install openai "a2a-sdk[http-server]>=1,<2" uvicorn` with `NANOGPT_API_KEY`
in the server env. **Never put the API key in the Agent Card or send it to an A2A caller.**

Publish the Agent Card at `/.well-known/agent-card.json` **on your domain** (it describes your agent,
not NanoGPT). For A2A 1.0 declare `supportedInterfaces` (URL, protocol binding, protocol version per
interface). Advertise only what you actually implement.

Production checklist (from the guide): authenticate A2A callers separately from the NanoGPT key;
per-caller quotas/spend limits before billable work; propagate cancellation + whole-task timeouts;
make task creation idempotent (retries must not double-bill); persist task state for poll/reconnect/
webhooks; bounded errors that don't leak prompts/credentials/provider details; test the Agent Card
and task lifecycle against an independent A2A client.

## 4. WebMCP — in-browser structured tools

Browsers with WebMCP support discover NanoGPT tools directly from an open chat page.
**Progressive enhancement:** unsupported browsers get no extra UI/API requests and do not load the
tool definitions.

| Tool | Does |
|---|---|
| `get_chat_state` | Read selected model, chat mode, and whether a draft exists — **without reading its text**. |
| `find_text_models` | Search the public NanoGPT text-model catalog by model ID. |
| `draft_chat_message` | Prepare text in the composer — **never sends it or starts a paid request**. |

Monitoring is **anonymous and aggregate only**: capable-browser reach, tool-registration success/
failure, and invocation lifecycle results. NanoGPT does **not** record WebMCP arguments, outputs,
prompt text, conversation IDs, agent names, registration errors, or session IDs. WebMCP has no
callback for mere tool-list inspection, so capable reach is reported separately from invocations.

## 5. Hosted tool search (Responses-only pilot)

From `agent-capabilities.json.toolSearch`:
- status `pilot`, endpoint **`/api/v1/responses` only**.
- canonical type `nanogpt:tool_search`; accepted aliases `nanogpt:tool_search`, `tool_search`.
- mark function tools with `defer_loading: true` (`deferredField`) to defer them.
- supported: `responses`. **Incompatible: `chat_completions`, `messages`.**
- `backgroundSupported: false`; `defaultMaxResults: 5`, `maximumMaxResults: 50`.
- billing: no separate NanoGPT search fee; provider input/output and hosted-tool charges (if any)
  remain billable.

## 6. Harness adapters (from the /agents pack)

| Adapter | Type | Setup |
|---|---|---|
| auth.md discovery | toolset | Fetch `https://nano-gpt.com/auth.md`, then OAuth PKCE, existing API key, or browser-approved device login. |
| MCP clients | mcp_client | `npx -y @nanogpt/mcp` with `NANOGPT_API_KEY` in the MCP server env. |
| OpenClaw | skill | baseUrl `https://nano-gpt.com/api/v1` + add the NanoGPT MCP server to tool config. |
| Hermes | toolset | OpenAI-compatible base URL `https://nano-gpt.com/api/v1` + `@nanogpt/mcp` as a dynamic MCP toolset. |
| OpenAI-compatible clients | openai_compatible | base URL `https://nano-gpt.com/api/v1`, `Authorization: Bearer $NANOGPT_API_KEY`. |
| A2A | agent_protocol | Your A2A server + Agent Card; call `https://nano-gpt.com/api/v1` for inference. |

## 7. CLI / agent auth for coding tools

- **auth.md discovery**: `GET https://nano-gpt.com/auth.md` is the machine-readable root. Also
  `/.well-known/oauth-protected-resource`, `/.well-known/nanogpt-agent-auth`,
  `/.well-known/oauth-authorization-server`, capability manifest `GET /api/v1/agent-capabilities`.
- **OAuth scopes**: `models.read`, `api.use`. OAuth access token is a dedicated NanoGPT API key.
- **Device login**: CLI-style browser-approved handoff (`sources/docs/integrations__cli-login.md`,
  auth.md section 2 "User-claimed device login").
- **Partner auth** (`sources/docs/api-reference__miscellaneous__partner-auth.md`): add NanoGPT to your
  product while keeping your own users/brand/UI.
- Auth failure hint: `WWW-Authenticate: Bearer resource_metadata="https://nano-gpt.com/.well-known/oauth-protected-resource"`.

## 8. Not live-tested
MCP server execution, A2A server build, WebMCP in-browser, device login, and the hosted tool-search
pilot require running clients/browsers and were not exercised in the live smoke test. Everything here
comes from the saved sources at the top; the model/HTTP layers they rely on (chat, catalogs, hunter)
ARE live-verified in `live-verification.md` / `data-enrichment.md`.
|---|---|---|
| `NANOGPT_API_KEY` | **Required.** API key | — |
| `NANOGPT_BASE_URL` | API base | `https://nano-gpt.com` |
| `NANOGPT_AUTH_MODE` | `bearer`, `x-api-key`, or `both` | `bearer` |
| `NANOGPT_LOG_LEVEL` | `debug`/`info`/`warn`/`error` | `info` |
| `NANOGPT_TIMEOUT_MS` | request timeout | `120000` |
| `NANOGPT_MAX_RETRIES` | retries | `0` |
| `NANOGPT_DEFAULT_MODEL` | default model for chat tools | — |