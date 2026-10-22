---
name: nanogpt-expert
description: Use when building, debugging, or integrating anything with NanoGPT or nano-gpt.com - chat/completions, Responses, Anthropic Messages, models, images, video, TTS/STT, music, embeddings, web search, scraping, batch, x402 accountless payments, MCP/WebMCP/A2A agent tooling, BYOK, memory, billing. Whole docs surface covered end-to-end with source-verified facts.
---

# NanoGPT Expert

Source-verified reference for the entire NanoGPT surface: 127 doc pages, both OpenAPI specs, the live agent-capabilities manifest, auth.md, OAuth metadata, the x402 matrix, and the agent harness page.

**Evidence rule:** every fact here traces to a file in `sources/`. If a claim is not in `sources/`, it is not a fact.

## Where to look
| Need | File |
|---|---|
| Endpoint + MCP tool + auth + inputs + x402 | `capability-matrix.md` |
| All 127 doc pages, grouped, linked to local copies | `docs-index.md` |
| Exact request/response per endpoint | `sources/docs/api-reference__endpoint__*.md` |
| Headers (verified names) | `headers.md` |
| x402 accountless payments | `x402.md` (docs) + `live-verification.md` (live-tested) |
| Hunter.io enrichment (8 tools) + Data API + all scrapers | `data-enrichment.md` |
| **Agents: MCP, WebMCP, A2A, tool search, adapters, CLI auth** | `agent-tooling.md` |
| **Install, dependencies, verified setup + runnable A2A starter** | `setup/SETUP.md`, `setup/` |
| **What is pre-wired on this machine (13 tool configs) + how to de-wire** | `INTEGRATIONS.md` |
| Auth, OAuth PKCE, device login, MCP, A2A, WebMCP, tool search | `auth-and-agents.md` |
| What was proven with real API calls vs. documentary only | `live-verification.md`, `VERIFICATION.txt` |
| Machine-readable contracts | `sources/manifests/*.json`, `sources/openapi.json`, `sources/openapi-site.json` |

## Authentication (verified)
- `Authorization: Bearer YOUR_API_KEY` or `x-api-key: YOUR_API_KEY`.
- Agent discovery: fetch `https://nano-gpt.com/auth.md`; metadata at `/.well-known/oauth-protected-resource`, `/.well-known/nanogpt-agent-auth`, `/.well-known/oauth-authorization-server`.
- Agent capability manifest: `https://nano-gpt.com/api/v1/agent-capabilities`.
- OAuth scopes: `models.read`, `api.use`. Unauthenticated request without `x-x402` returns `401 missing_api_key`.

## Hosts (verified)
- `https://api.nano-gpt.com/api` - direct API for large requests and long-running calls.
- `https://nano-gpt.com/api` - website API host (catalogs can differ during rollouts).
- Agent/MCP base URL: `https://nano-gpt.com/api/v1`.

## Agent harness pack (full detail in `agent-tooling.md`)
- **MCP** is the default agent surface. Package `@nanogpt/mcp`, `npx -y @nanogpt/mcp`, protocol
  target 2025-11-25. ~31 MCP tools across account, text, images, video, 3D, audio, web/research,
  social/maps, and catalogs (see `agent-tooling.md` for the full tool table + parameters).
- Claude Code: `claude mcp add nanogpt --scope user --env NANOGPT_API_KEY=your_key -- npx -y @nanogpt/mcp`
  (native Windows needs `cmd /c "...\npx.cmd"`).
- **A2A**: NanoGPT is the model provider for an external A2A server (`nativeServer: false`), protocol
  1.0. You own the Agent Card (`/.well-known/agent-card.json`) and task lifecycle. Never expose the key.
- **WebMCP** tools on chat pages: `get_chat_state`, `find_text_models`, `draft_chat_message` (never
  sends or pays). Anonymous/aggregate monitoring only.
- **Hosted tool search** (Responses-only pilot): `nanogpt:tool_search` / `tool_search`, mark tools
  `defer_loading: true`. Works on `/api/v1/responses`; NOT on chat_completions or messages.
- **Adapters**: auth.md discovery, MCP clients, OpenClaw, Hermes, OpenAI-compatible clients, A2A.
- **Async media via MCP**: `nanogpt_video_generate`/`nanogpt_3d_generate` use
  `operation: submit|submit_and_poll|poll|status`; charged on submit — poll, never re-submit.
- **CLI/agent auth**: `GET /auth.md` root, OAuth PKCE (`models.read`, `api.use`), device login,
  partner auth. See `agent-tooling.md`.

## Endpoint coverage (agent-capabilities.json)

### Chat and Reasoning
- `POST /api/v1/chat/completions` - Chat Completions (auth: api_key, streaming, MCP: nanogpt_chat | x402)
- `POST /api/v1/responses` - Responses API (auth: api_key, async_or_sync, MCP: nanogpt_responses | x402)
- `POST /api/v1/messages` - Anthropic Messages (auth: api_key, streaming, MCP: API only)

### Model Catalogs
- `GET /api/v1/models` - Text Model Catalog (auth: public, sync, MCP: nanogpt_list_text_models)
- `GET /api/v1/image-models` - Image Model Catalog (auth: public, sync, MCP: nanogpt_list_image_models)
- `GET /api/v1/video-models` - Video Model Catalog (auth: public, sync, MCP: nanogpt_list_video_models)
- `GET /api/v1/audio-models` - Audio Model Catalog (auth: public, sync, MCP: nanogpt_list_audio_models)

### Search and Fetch
- `POST /api/web` - Web Search (auth: api_key_or_session, sync, MCP: nanogpt_web_search | x402)
- `POST /api/scrape-urls` - URL Scraping (auth: api_key_or_session, sync, MCP: nanogpt_scrape_urls | x402)
- `POST /api/youtube-transcribe` - YouTube Transcripts (auth: api_key_or_session, sync, MCP: nanogpt_youtube_transcribe)

### Structured Scrapers
- `POST /api/v1/firecrawl` - Website Crawler (auth: api_key_or_session, async_or_sync, MCP: nanogpt_firecrawl)
- `POST /api/v1/reddit` - Reddit Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_reddit)
- `GET /api/v1/x` - X Research (auth: api_key_or_session, sync, MCP: nanogpt_x_research)
- `POST /api/v1/googlemaps` - Google Maps Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_google_maps_scrape)
- `POST /api/v1/googlemaps/reviews` - Google Maps Reviews (auth: api_key_or_session, async_job, MCP: nanogpt_google_maps_reviews_scrape)
- `POST /api/v1/tiktok` - TikTok Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_tiktok_scrape)
- `POST /api/v1/instagram/profile` - Instagram Profile Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_instagram_profile)
- `POST /api/v1/instagram/posts` - Instagram Posts Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_instagram_posts_scrape)
- `POST /api/v1/instagram/reels` - Instagram Reels Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_instagram_reels)
- `POST /api/v1/facebook/posts` - Facebook Posts Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_facebook_posts_scrape)
- `POST /api/v1/facebook/ads` - Facebook Ads Library Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_facebook_ads)
- `POST /api/v1/linkedin/profile` - LinkedIn Profile Scraper (auth: api_key_or_session, async_job, MCP: nanogpt_linkedin_profile)

### Image and Video
- `POST /api/v1/images/generations` - Image Generation (auth: api_key_or_session, async_or_sync, MCP: nanogpt_image_generate | x402)
- `POST /api/v1/images/edits` - Image Editing (auth: api_key_or_session, async_or_sync, MCP: nanogpt_image_edit | x402)
- `POST /api/generate-video` - Video Generation (auth: api_key_or_session, async_job, MCP: nanogpt_video_generate)
- `GET /api/video/status` - Video Status (auth: api_key_or_session, sync, MCP: nanogpt_video_generate)

### Audio and Music
- `POST /api/v1/audio/speech` - Text to Speech (auth: api_key_or_session, sync, MCP: nanogpt_text_to_speech)
- `POST /api/v1/audio/speech` - Music Generation (auth: api_key_or_session, async_or_sync, MCP: nanogpt_music_generate)
- `POST /api/v1/audio/transcriptions` - Speech to Text (auth: api_key_or_session, sync, MCP: nanogpt_audio_transcribe)

### Data Enrichment
- `GET /api/v1/hunter` - Hunter Email Data (auth: api_key_or_session, sync, MCP: nanogpt_hunter)

**Hunter has 8 tools, not 1** — see `data-enrichment.md` for the full reference. Billed via NanoGPT
(you never pass a Hunter API key). Reach them 3 ways: direct (`/api/v1/hunter/{path}`), generic
dispatch (`/api/v1/hunter?endpoint=...` or POST `{"endpoint":..., "params":{...}}`), or the Data API
(`/api/v1/data/hunter/{path}` / body-style `{"endpoint":"hunter.*","input":{...}}`):

| Tool | Direct path | Free? | Credit type |
|---|---|---|---|
| `hunter.discover` | `POST /api/v1/hunter/discover` | **Free** | — |
| `hunter.email_count` | `/api/v1/hunter/email-count` | **Free** | — |
| `hunter.domain_search` | `/api/v1/hunter/domain-search` | no | search |
| `hunter.email_finder` | `/api/v1/hunter/email-finder` | no | search |
| `hunter.email_verifier` | `/api/v1/hunter/email-verifier` | no | verification |
| `hunter.person_enrichment` | `/api/v1/hunter/people/find` | no | enrichment |
| `hunter.company_enrichment` | `/api/v1/hunter/companies/find` | no | enrichment |
| `hunter.combined_enrichment` | `/api/v1/hunter/combined/find` | no | enrichment |

Params: `endpoint`, `domain?`, `company?`, `email?`, `full_name?`, `first_name?`, `last_name?`.
Response is Hunter's JSON plus `meta.nanogpt` (`hunterSearchesBilled`, `hunterVerificationsBilled`,
`hunterEnrichmentsBilled`, `costUsd`). The Data API wrapper `GET /api/v1/data` lists all 20 data
endpoints (providers: Apify, Firecrawl, Hunter, NanoGPT) — see `data-enrichment.md`.

### Extras
- `GET /api/v1/feedback/{id}` - Retrieve Existing API Feedback (auth: api_key, sync, MCP: API only)
- `POST /api/v1/embeddings` - Embeddings (auth: api_key, sync, MCP: nanogpt_embeddings)
- `POST /api/v1/moderations` - Content Moderation (auth: api_key, sync, MCP: API only)
- `POST /api/v1/ai-detection` - AI Detection (auth: api_key_or_session, sync, MCP: nanogpt_ai_detection)

## Media and long-running jobs (verified patterns)
- Video: `POST /api/generate-video`, then poll `GET /api/video/status` with `requestId`/`runId`; `/generate-video/status`, `/video/status`, `/v1/video/status` variants also appear in the docs spec.
- Music rides the TTS transport `POST /api/v1/audio/speech` with a music-capable model (`input`/`text`, `duration`, `lyrics`, `tags`, `audio`, `sampleRate`, `bitrate`).
- Async scraper jobs (Reddit, Google Maps, TikTok, Instagram, Facebook, LinkedIn) are start-and-poll; see `sources/docs/api-reference__endpoint__data-api.md`.

## x402 accountless payments (LIVE-TESTED)
1. Send the request with no `Authorization`/`x-api-key` and header `x-x402: true`.
2. Receive `402 Payment Required` (verified live) with these response headers:
   `x-payment-address` (nano_...), `x-payment-amount` (XNO), `x-payment-amount-usd`,
   `x-payment-id` (pay_...), `x-payment-required` (JSON quote: scheme/network/asset/amount),
   `x-payment-schemes` (e.g. `nano,nano-exact,exact,usdc-base,solana-usdc-exact`),
   `x-request-id`, `x-nanogpt-failure-classification: user_balance`.
3. Pay on a rail, then:
   - manual: `POST /api/x402/complete/{paymentId}` (use the `x-payment-id`), or
   - replay the original request with `X-PAYMENT` (exact schemes), or
   - replay with `Authorization: L402 <token>:<preimage>` (Lightning).
- Observed live quote: $0.0887 USD = 0.2678 XNO for a 5-token chat call.
- The `402` error body is self-describing: it names the `X-PAYMENT` retry header and the exact
  `/api/x402/complete/pay_...` URL.
- Source of truth for enabled rails: `GET /api/v1/x402/endpoints` (add `?supported=all` for beta),
  or the `x-payment-schemes` header on the live quote. Docs' scheme table names (`base-usdc`,
  `x402-exact`, `x402-solana-usdc`, `lightning-l402`) differ from the live names — trust the API.
- Stable accountless scope is non-streaming chat/responses; streaming and video remain beta/deferred.
- Details: `x402.md` (docs verbatim), `live-verification.md` (observed), `sources/manifests/x402-endpoints.json`.

## Corrected claims (superseded — see live-verification.md)
Documentary review and live testing together fixed these. Live API behavior is authoritative where it
differs from the docs:
- `GET /api/video/status`, not `/api/video-status`.
- **`x-payment-required` is REAL** (a response header carrying the JSON quote). It appears in no doc
  page but the API emits it. It is a response header, not a request header. Don't dismiss it.
- Payment response headers are `x-payment-address`, `x-payment-amount`, `x-payment-amount-usd`,
  `x-payment-id`, `x-payment-required`, `x-payment-schemes` — all undocumented but real.
- Manual completion is `POST /api/x402/complete/{paymentId}` (not a `completeUrl` field).
- Live scheme names (`nano,nano-exact,exact,usdc-base,solana-usdc-exact`) differ from the docs' scheme
  table. Trust `GET /api/v1/x402/endpoints` / the live `x-payment-schemes` header.
- `POST /api/check-balance` is the correct verb (GET returns 405). The docs are correct here; an
  early note claiming otherwise was a test error.
- Memory header is `memory_expiration_days` on the memory endpoint, not `x-memory-size`.
- No `x-provider-key` header exists (confirmed in docs AND not observed live).
- x402 public accountless endpoints are the six listed in `x402.md`.

## Coverage
See `docs-index.md`: all 127 pages from `https://docs.nano-gpt.com/llms.txt` were downloaded to `sources/docs/` (127/127 ok, 0 failed).

Generated 2026-10-15 from live sources.