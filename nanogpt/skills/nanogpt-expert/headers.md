# Verified NanoGPT headers

Every header was searched across all 127 downloaded doc pages (`sources/docs/*.md`). Count = pages containing the literal header.

| Header | Pages | Purpose |
|---|---|---|
| `authorization` | 67 | `Authorization: Bearer <key>`; after a Lightning x402 payment: `Authorization: L402 <token>:<preimage>`. |
| `x-api-key` | 57 | Alternate API-key auth: `x-api-key: YOUR_API_KEY` (same as Bearer). |
| `accept` | 55 | Use `Accept: text/event-stream` for SSE streaming. |
| `content-type` | 54 | `application/json` for JSON bodies; multipart for file uploads. |
| `x-request-id` | 11 | Server-generated request id; use it with `GET /api/v1/usage/requests/{request_id}`. |
| `x-x402` | 10 | `x-x402: true` on an unauthenticated request asks for an accountless x402 quote (HTTP 402). |
| `x-provider` | 9 | Force a specific upstream provider for a request instead of NanoGPT routing. |
| `anthropic-beta` | 6 | Anthropic beta header on Messages batch endpoints. |
| `x-billing-mode` | 6 | Billing mode selector on supported endpoints (see chat-completion / responses docs). |
| `memory_expiration_days` | 4 | Context Memory: `1..365`, default 30. Overrides body `expiration_days`. |
| `idempotency-key` | 3 | Idempotency key for batch creation and other writes. |
| `x-payment` | 2 | `X-PAYMENT` carries an exact-payment payload when replaying after `nano-exact`, `x402-exact`, or `x402-solana-usdc`. |

## Response headers observed live (in no doc page — discovered by real API calls)

These are **real** API behaviors verified against `https://api.nano-gpt.com`. They appear in the x402
402-response. See `live-verification.md` for the captured values.

| Header | Observed purpose |
|---|---|
| `x-payment-address` | Nano address to send payment to (`nano_...`). |
| `x-payment-amount` | Amount in XNO (e.g. `0.26779888`). |
| `x-payment-amount-usd` | Same amount in USD. |
| `x-payment-id` | Payment id (`pay_...`); used in `POST /api/x402/complete/{paymentId}`. |
| `x-payment-required` | JSON quote: `scheme`, `network`, `asset`, `amount`, `maxAmountRequired`, `maxAmountRequiredFormatted`, `maxAmountRequiredUSD`. |
| `x-payment-schemes` | Enabled rails, e.g. `nano,nano-exact,exact,usdc-base,solana-usdc-exact`. |
| `x-nanogpt-failure-classification` | Failure class, e.g. `user_balance`. |
| `x-x402` | (request) `x-x402: true` asks for an accountless quote. |

## Still not documented and not observed — do not use

`x-provider-key`, `x-memory-size`, `x-user`, `x-session`. Confirmed absent from all 127 doc pages and
not emitted by any live call. Search `sources/docs/` before using any header.
