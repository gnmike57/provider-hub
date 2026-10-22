# Auth, MCP, A2A and harness adapters (distilled)

> Full verbatim `auth.md` (incl. every request/response example): `sources/auth.md`.
> MCP/WebMCP/A2A detail: `agent-tooling.md`. Machine config: `INTEGRATIONS.md`.

## Discovery
Fetch `https://nano-gpt.com/auth.md` - the machine-readable root. It points to:
- `/.well-known/oauth-protected-resource` (protected resource metadata)
- `/.well-known/nanogpt-agent-auth` (agent registration metadata)
- `/.well-known/oauth-authorization-server` (OAuth AS metadata)
- `GET /api/v1/agent-capabilities` (capability manifest) · `https://nano-gpt.com/api` (docs) · `/mcp`
- Auth failures return `WWW-Authenticate: Bearer resource_metadata="https://nano-gpt.com/.well-known/oauth-protected-resource"`.

Resource server `https://nano-gpt.com/api/v1`; issuer `https://nano-gpt.com`.

## 4 auth methods (auth.md section 2)
1. **OAuth key handoff shortcut** - redirect to `https://nano-gpt.com/auth?callback_url=...&code_challenge=...&code_challenge_method=S256&state=...` (S256 PKCE required; callback must be HTTPS or loopback HTTP w/ explicit port; optional `invitation_code` from `/r/<code>`). Exchange code at `POST /api/v1/auth/keys` -> `{key, access_token, token_type, scope, user_id}`.
2. **OAuth PKCE + dynamic registration** - `POST /oauth/register` (public client, `token_endpoint_auth_method: none`), authorize at `/oauth/authorize`, exchange at `POST /oauth/token` (form-encoded) -> `{access_token, token_type, scope}`. Access token **is** a dedicated NanoGPT API key.
3. **Existing API key** - `Authorization: Bearer <key>` (or `x-api-key`).
4. **User-claimed device login** - start device login, user approves in browser (CLI handoff).

No anonymous spend-capable credentials. Agent-verified ID-JAG registration not yet enabled.

## Scopes (auth.md section 3)
- `models.read` - read public model catalogs + pricing.
- `api.use` - use API endpoints with a user-approved key (bounded by balance/subscription/per-key limits).
- OAuth grants use these; `api.use` is **required** in OAuth authorization requests (MVP).

## Key handoff extras (auth.md section 4)
- Authenticated clients can mint a one-time code for a downstream app: `POST /api/v1/auth/keys/code`
  with `{redirect_uri, code_challenge, code_challenge_method:"S256", limit, usage_limit_type, expires_at, key_label}`.
  `limit` is USD; `usage_limit_type` = `daily`/`weekly`/`monthly`. Applied to the dedicated key on exchange.
  Response has top-level fields + nested `data` object.
- Referral attribution via `invitation_code` (from `https://nano-gpt.com/r/<code>`).

## Use the credential / revocation (auth.md 7 & 9)
Send the key as `Authorization: Bearer sk-nano-...` (or `x-api-key`). Revoke keys from the dashboard.

## Harness adapters (agent-capabilities.json)
| Adapter | Type | Setup |
|---|---|---|
| auth.md discovery | toolset | fetch `/auth.md`, then OAuth PKCE / API key / device login |
| MCP clients | mcp_client | `npx -y @nanogpt/mcp` + `NANOGPT_API_KEY` |
| OpenClaw | skill | baseUrl `https://nano-gpt.com/api/v1` + MCP server |
| Hermes | toolset | base URL `https://nano-gpt.com/api/v1` + `@nanogpt/mcp` toolset |
| OpenAI-compatible | openai_compatible | base URL `https://nano-gpt.com/api/v1`, `Authorization: Bearer` |
| A2A | agent_protocol | your A2A server + Agent Card; NanoGPT does inference |

## MCP
`@nanogpt/mcp` / `npx -y @nanogpt/mcp`, protocol target 2025-11-25. Full tool list + params in
`agent-tooling.md`. Claude Code: `claude mcp add nanogpt --scope user --env NANOGPT_API_KEY=... -- npx -y @nanogpt/mcp`.

## A2A
NanoGPT = model provider for an external A2A server (`nativeServer: false`), protocol 1.0. You own
the Agent Card (`/.well-known/agent-card.json`) and task lifecycle. See `agent-tooling.md` + `setup/`.

## WebMCP (live /agents page)
Tools `get_chat_state`, `find_text_models`, `draft_chat_message` (never sends/pays). Anonymous
aggregate monitoring only - no arguments, outputs, prompts, conversation IDs, or session IDs recorded.

## Hosted tool search (toolSearch)
Pilot, `POST /api/v1/responses` only. Canonical `nanogpt:tool_search` (alias `tool_search`); mark
function tools `defer_loading: true`. Incompatible with chat_completions + messages. maxResults 5 (max 50).
