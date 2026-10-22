# NanoGPT cross-cutting reference (limits, pricing, caching, streaming, reasoning, security)

> Distilled from the 31 `sources/docs/api-reference__miscellaneous__*.md` guides and
> `api-reference/{teams,evals,management-api}.md`. Every number is from the docs.

## API hosts & limits
- **Use `https://api.nano-gpt.com`** for API-key calls: higher request-size and longer runtime than
  the website host `https://nano-gpt.com`. Batch uploads also use the direct host.
- Base URLs: OpenAI SDK `https://api.nano-gpt.com/api/v1`; Anthropic SDK
  `https://api.nano-gpt.com/api` (SDK appends `/v1/messages`).
- Body limit for authenticated Chat/Responses/Messages JSON: **32 MiB**.
- Catalogs differ per host during rollouts — check `GET /api/v1/models?detailed=true`.
- Website host is for dashboard, API-key management, browser sign-in, OAuth/device login, Management API.

## Rate limits
- **Global 25 requests/second.** Higher on request (support@nano-gpt.com).
- >1B tokens/day of a model → contact support (better pricing possible).
- **Optional per-key daily limits** (dashboard): RPD and USD/day. Reset **00:00 UTC**.
- Exceeding → OpenAI-style `429` + `Retry-After`. Codes: `daily_rpd_limit_exceeded`,
  `daily_usd_limit_exceeded`. USD/day is estimate-at-request (approximate). Subscription-covered calls
  bypass USD/day but count toward RPD.

## Pricing & billing lookup
- No minimum fee per query, **no fee on deposits**. Per-model pricing at nano-gpt.com/pricing.
- Use exact model IDs from `GET /api/v1/models` — no hidden aliases.
- **Request Billing** `GET /api/v1/usage/requests/{request_id}`: exact charge + tokens via response
  `X-Request-ID` + same key, **24h** window. Refunds/extras excluded. 404 ≠ free (honor
  `Retry-After: 30`); 409 = multiple charges. `X-Request-ID` is a **correlation ID, not idempotency** —
  re-running inference re-charges. Aggregate spend: `GET /api/v1/usage`.

## Errors (3 envelopes)
1. **OpenAI** (`/api/v1/*`): `{"error":{"message","type","code","param"}}`.
2. **Anthropic** (`/api/v1/messages`): `{"type":"error","error":{"type","message","param"}}`.
3. **Legacy** (`/api/*`): `{"error":"Insufficient balance","status":402}` (+`requiredBalance`).
- Codes: `400` bad request · `401` bad key (don't retry) · `402` balance · `403` not permitted ·
  `404` not found · `408`/`504` timeout (retry) · `409` conflict · `429` rate limit · `5xx` retry.
- Feedback quirk: `feedback_unavailable` = **both** `410` and `503` — check status before retrying.

## Prompt caching (up to ~90% off cached input)
- **Implicit (default):** automatic on OpenAI, Gemini, many open-source routes.
- **Explicit (Claude):** `prompt_caching`/`promptCaching`/`cache_control` (body or inline) + TTL.
  OpenCode auto-adds markers (5-min TTL; `enabled:true, ttl:"1h"` for 1h).
- **Cache routing:** top-level `caching: true` (or suffix `:caching`) → cache-capable provider.

## Streaming (SSE)
- `"stream": true` on `/v1/chat/completions` (OpenAI chunks), `/v1/messages` (Anthropic events),
  `/v1/responses`. `text/event-stream`; `data:` frames. Omit/`false` → single JSON.
- **Save `X-Request-ID` before reading the stream** — recover lost usage via Request Billing (24h).

## Extended thinking / reasoning
- Streaming: `choices[0].delta.reasoning` (legacy `reasoning_content`). Non-streaming:
  `choices[0].message.reasoning`. Not all models emit reasoning.
- **Three chat base paths:** `/api/v1/chat/completions` (separate `reasoning` + `content`);
  `/api/v1legacy/chat/completions` (legacy `reasoning_content` — use when a client won't show
  thinking, e.g. Cline); `/api/v1thinking/chat/completions` (reasoning merged into `content`).
- **Hide reasoning:** body `{"reasoning":{"exclude":true}}` or suffix `:reasoning-exclude`
  (hides output; does not disable compute).
- `:thinking` is a model **identity** suffix (kept, only IDs that exist); `-thinking` is a legacy
  alias for some families. Check `GET /api/v1/models`. Change effort mid-conversation via
  `reasoning_effort` (see `Change Reasoning Effort Within a Conversation`).

## Model suffixes (append to `model`; routing ones stripped before routing)
- **Provider routing:** `:speed`/`:fast` · `:throughput` · `:latency` · `:price`/`:cheap`/`:floor`
  (cheapest; stays on Auto if Auto is cheaper) · `:tools` · `:caching`/`:cache`/`:cached`.
- Identity suffixes (`:thinking`) preserved; routing stripped. Case-insensitive. Don't combine
  conflicting provider suffixes. Routing considers only user-selectable providers.

## Security & safety
- **PII redaction** — opt-in, **$0.0005/redacted request**, via **Grepture** before the model: masks
  PII, restores it in the response. **Secrets are labeled and NOT restored.** Endpoints:
  `/v1/chat/completions`, `/v1/completions`, `/v1/responses`. Header `redaction: true` (or `redacted`).
- **Inline moderation** — opt-in paid **input** preflight (not outputs) via header `moderation: true`
  (or `moderation: <model-id>`). Models: `GET /api/v1/moderation-models`. Flagged → charge moderation
  only, skip generation. Routes: chat/responses/completions/messages + image + video.
  **Not supported on accountless x402.**
- **BYOK** — bring your own provider key (see `sources/docs/...__byok.md`).
- **Tool-calling diagnostics** — off by default. Enable in Settings → Privacy & Analytics, then send
  `nanogpt fix this` (exact lowercase) after a failed tool turn. Stores the previous cycle (prompts,
  tool schemas/args/outputs, paths); best-effort redaction, configurable retention.
- **Distillation policy** — model-level control over distillation/training use of outputs.
- **Provider selection** — upstream provider pick/reroute (31 KB `provider-selection.md`).

## Client libraries
- **JavaScript:** `npm install nanogptjs` → `new NanoGPT('key')`; `.chat()`, `.generateImage()`, balance.
- **TypeScript:** `npm install nanogpt-client` (unofficial, OpenAPI-inferred, browser + Node) →
  `new NanoGPTClient({apiKey})` → `.chatCompletions.create()`.

## Web app, extensions & billing extras
- **URL parameters** (`web-app__url-parameters.md`); **Chrome extension**; **Brave**; **Auto Recharge**;
  **Pay-As-You-Go Billing Override** (per-request override of subscription billing).

## Account & org surfaces
- **Teams** (`api-reference__teams.md`, 24 KB) · **Evals & Observability** (`api-reference__evals.md`,
  23 KB) · **Management API** (`api-reference__management-api.md`, website host) · **Advisor**
  extension (non-streaming platform-billed calls) · **For Providers** · **Compressed request bodies**
  (gzip/deflate) · **Video input** (video blocks on supported models).

## Full text
Each guide is stored verbatim in `sources/docs/`. This is the distilled map; open the source file for
full detail on any topic.