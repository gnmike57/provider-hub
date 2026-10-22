# Live endpoint verification (real API calls)

Tested against `https://api.nano-gpt.com` with a real API key. The key is **not** stored in this
skill — it was passed via the `NANOGPT_API_KEY` environment variable at test time.

Balance after testing: `usd_balance` ≈ 21.45 (tiny spend from one 5-token chat call and one embedding).

## Results

| Endpoint | HTTP | Result | Notes |
|---|---|---|---|
| `GET /api/v1/models` | 200 | OK | OpenAI `object":"list"` shape; `id`, `owned_by`. Models include `fireworks/ember-1`, `prism-ml/ternary-bonsai-2-27b`, `unbiased/pareto-26.10-preview`. |
| `GET /api/v1/image-models` | 200 | OK | Rich records: `architecture.modality` (`text+image->image`), `pricing`, e.g. `qwen-image-2.1-turbo`. |
| `GET /api/v1/video-models` | 200 | OK | e.g. `wavespeed-ai/ai-video-editor/video-captioner`, `video->video`. |
| `GET /api/v1/audio-models` | 200 | OK | e.g. `qwen-audio-3.1-tts-flash`. |
| `GET /api/v1/embedding-models` | 200 | OK | `text-embedding-3-small`, dims 1536, `supports_dimensions:true`, `pricing.per_million_tokens`. |
| `GET /api/v1/x402/endpoints` | 200 | OK | `object":"x402.endpoint_support.list"`, `version":"2026-06-03"`. |
| `GET /api/v1/agent-capabilities` | 200 | OK | `object":"agent_capabilities.manifest"`, `version":"2026-10-10"` — matches the saved manifest. |
| `POST /api/check-balance` | 200 | OK | Returns `usd_balance`, `nano_balance`, `nanoDepositAddress`. **Must be POST.** |
| `GET /api/check-balance` | 405 | (expected) | Method Not Allowed — consistent with the docs, which specify `POST /check-balance`. |
| `GET /api/v1/usage` | 200 | OK | `scope":"current_key"`, `apiKey.id`, `groupBy":"day,model"`, `rollupDays`. |
| `GET /api/v1/api-keys/current` | 200 | OK | `object":"api_key"` with `budget_diagnostics` (payer, billing_mode, budgets). |
| `POST /api/v1/chat/completions` | 200 | OK | `id":"chatcmpl-..."`, model `minimax/minimax-m2.7`, `usage` incl. `reasoning_tokens`, `citation_tokens`, `num_search_queries`. |
| `POST /api/v1/embeddings` | 200 | OK | OpenAI embedding list shape. |
| `POST /api/v1/chat/completions` + `x-x402: true` (no auth) | 402 | Quote OK | Full payment quote returned. |
| `GET /api/v1/hunter/email-count?domain=stripe.com` | 200 | OK | Free (costUsd 0). `data.total=3964` + department/seniority breakdown. |
| `GET /api/v1/hunter?endpoint=email-count&domain=openai.com` | 200 | OK | Generic dispatch works. |
| `POST /api/v1/data {"endpoint":"hunter.email_count",...}` | 200 | OK | Data API body-style dispatch works. |
| `POST /api/v1/hunter/discover` | 200 | OK | Free confirmed (costUsd 0). `data[]` with domain/organization/emails_count. |
| `GET /api/v1/hunter/domain-search?domain=nano-gpt.com` | 200 | OK | `hunterSearchesBilled: 1, costUsd: 0.02695`. All 3 dispatch styles verified. |

Hunter enrichment is fully live-verified — see `data-enrichment.md` for the observed response envelope
(`meta.params`, `meta.nanogpt.provider`, `meta.results/limit/offset`, top-level `status`).

## x402 live quote — observed response

Sending an unauthenticated `POST /api/v1/chat/completions` with `x-x402: true` returns **402** with
these headers (verified live):

| Header | Observed value (truncated) |
|---|---|
| `x-payment-address` | `nano_3upa1tepoyfej7zmkapjdnomcyhm1rgf61udwtfnz9thwy8mxdrtnrnzru8d` |
| `x-payment-amount` | `0.26779888` (XNO) |
| `x-payment-amount-usd` | `0.08870677200000002` |
| `x-payment-id` | `pay_c27794e99145396c1a62a16defc94842` |
| `x-payment-required` | JSON: `{"scheme":"exact","network":"solana","asset":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","amount":"88707","maxAmountRequired":"88707",...}` |
| `x-payment-schemes` | `nano,nano-exact,exact,usdc-base,solana-usdc-exact` |
| `x-request-id` | `req_7a7e3f1f-...` |
| `x-nanogpt-failure-classification` | `user_balance` |

402 body (verified):

```json
{"error":{"message":"Insufficient balance. Multiple payment options available. Payment required: $0.0887 USD (0.26779888 XNO). For x402 clients: retry this endpoint with X-PAYMENT header. For manual payments: send to nano_3upa1... then call /api/x402/complete/pay_c27794e99145396c1a62a16defc94842","type":"insufficient_quota",...}}
```

## Facts corrected BY live testing

These are things the docs pages do **not** state, discovered only by real calls. An earlier revision
of this skill wrongly listed some of them as "not documented — do not use".

1. **`x-payment-required` IS real.** It is a response header carrying a JSON payment quote
   (scheme/network/asset/amount). The docs never mention it; the API emits it. It is a
   **response** header, not a request header.
2. **Payment request headers are `x-payment-address`, `x-payment-amount`, `x-payment-amount-usd`,
   `x-payment-id`, `x-payment-schemes`.** None appear in the doc pages. The docs' prose names only
   `X-PAYMENT` and `Authorization: L402 ...` for replay.
3. **The completion URL is `POST /api/x402/complete/{paymentId}`** (as the 402 message states and
   `openapi.json` lists), where `{paymentId}` is the `x-payment-id`.
4. **Live scheme names differ from the docs' scheme table.** Observed: `nano, nano-exact, exact,
   usdc-base, solana-usdc-exact`. Docs table lists `nano, nano-exact, base-usdc, x402-exact,
   x402-solana-usdc, lightning-l402`. Treat `GET /api/v1/x402/endpoints` as the source of truth and
   prefer the `x-payment-schemes` header from the live quote for the actual enabled rails.
5. **`POST /api/check-balance` is the correct verb** (GET → 405). The docs are correct here.
6. **`x-nanogpt-failure-classification: user_balance`** is an undocumented diagnostic header.

## Remaining uncertainty (not live-tested)

- Paid media jobs (video generation, image generation, TTS, music, voice cloning) — cost money and
  were not run. Their request/response shapes come from `sources/docs/` and `sources/openapi.json`.
- Async scraper jobs (Reddit, TikTok, Google Maps, Instagram, Facebook, LinkedIn) — not run.
- OAuth PKCE / device login flows — require a browser redirect; documented in `auth.md` only.
- Streaming (SSE) and BYOK — documented, not exercised here.