> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring Your Own Key (BYOK)

> Route chat completions through your own provider API keys.

## Overview

BYOK (Bring Your Own Key) lets you store API credentials for supported upstream providers and then opt-in per request to route through your own keys.

Typical reasons to use BYOK:

* Your provider bills you directly (enterprise agreements, committed-use discounts, free tiers).
* You want NanoGPT routing + enhancements, without using NanoGPT platform keys.

## Availability

BYOK is currently supported on:

* `POST /api/v1/chat/completions`

## Pricing

When you use BYOK:

* Your provider bills you directly for usage on their side.
* NanoGPT charges a **5% platform fee** on top for routing and platform features.

## Configure Keys

### Web UI (Recommended)

Manage BYOK keys in the NanoGPT web app:

* [https://nano-gpt.com/byok](https://nano-gpt.com/byok)

Keys are never shown again after saving (only a short suffix is displayed), so treat them like passwords.

### API (NanoGPT key required)

If you prefer managing keys programmatically, use these endpoints (not OpenAI-compatible):

```http theme={null}
POST   /api/user/provider-keys
GET    /api/user/provider-keys
DELETE /api/user/provider-keys?provider=<provider-slug>
```

Example: add/update a provider key

```bash theme={null}
curl -X POST "https://nano-gpt.com/api/user/provider-keys" \
  -H "Authorization: Bearer YOUR_NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "key": "YOUR_PROVIDER_API_KEY"
  }'
```

## Use BYOK On A Request

### Enable BYOK

Option A: request header

```http theme={null}
x-use-byok: true
```

Option B: request body

```json theme={null}
{
  "byok": { "enabled": true }
}
```

### Select a provider (optional)

If the model can route through multiple providers, you can force a specific provider.

Header:

```http theme={null}
x-byok-provider: openai
```

Body:

```json theme={null}
{
  "byok": { "enabled": true, "provider": "openai" }
}
```

### Fallbacks (optional)

BYOK defaults to **fail-fast** behavior. If your provider key fails, NanoGPT will not silently route the request through a different provider key.

You can control this via the request body:

```json theme={null}
{
  "byok": { "enabled": true, "disableFallbacks": true }
}
```

## Provider Slugs

The exact set of supported providers can evolve; the BYOK UI lists what your account can configure.

### Chat / completion providers

These providers can be used for BYOK on `POST /api/v1/chat/completions`:

| Provider | Slug | Key format |
| - | - | - |
| OpenAI | `openai` | API key string (`sk-...`) |
| OpenAI Responses | `openai-responses` | API key string (`sk-...`) |
| Anthropic | `anthropic` | API key string (`sk-ant-...`) |
| OpenRouter | `openrouter` | API key string (`or-...`) |
| Chutes | `chutes` | API key string (`cpk_...`) |
| AWS Bedrock | `aws` | JSON: `{"accessKeyId":"...","secretAccessKey":"...","region":"us-east-1"}` |
| Azure OpenAI | `azure` | JSON: `{"endpoint":"...","apiKey":"...","deploymentName":"...","apiVersion":"..."}` |
| Azure Responses | `azure-responses` | JSON: `{"endpoint":"...","apiKey":"...","apiVersion":"..."}` |
| Azure Anthropic Foundry | `azure-anthropic-foundry` | JSON: `{"endpoint":"...","apiKey":"..."}` |
| Google AI Studio | `google` | API key string (`AIza...`) |
| Groq | `groq` | API key string (`gsk_...`) |
| NVIDIA | `nvidia` | API key string (`nvapi-...`) |
| SambaNova | `sambanova` | API key string |
| Vercel | `vercel` | API key string |
| Novita | `novita` | API key string (`nvta_...`) |
| Akash | `akash` | API key string (`sk-...`) |
| Z.AI (GLM) | `zai` | API key string |
| GMICloud | `gmicloud` | API key string |
| Cerebras | `cerebras` | API key string (`csk-...`) |
| MegaNova | `meganova` | API key string |

Notes:

* AWS JSON can also include `sessionToken`.
* Azure-style providers require provider-specific endpoints and identifiers (for example, a deployment name).
* If you want to force Google AI Studio routing for Gemini models, set `x-byok-provider: google` (or `byok.provider: "google"`).
* Additional provider options may appear over time in the BYOK UI and provider-discovery endpoints.

### Web-search-only providers

These providers are BYOK for web search enhancements, not chat model execution:

| Provider | Slug |
| - | - |
| Tavily | `tavily` |
| Exa | `exa` |
| Kagi | `kagi` |
| Perplexity | `perplexity` |
| Valyu | `valyu` |

## Teams (BYOK)

Teams can also store provider keys and configure whether team-billed traffic should use team keys.

Team settings endpoints (session-authenticated, not OpenAI-compatible):

```http theme={null}
GET   /api/teams/{teamUuid}/byok-settings
PATCH /api/teams/{teamUuid}/byok-settings
GET   /api/teams/{teamUuid}/provider-keys
POST  /api/teams/{teamUuid}/provider-keys
DELETE /api/teams/{teamUuid}/provider-keys?provider=<provider-slug>
```

BYOK modes:

* `disabled`: BYOK off for the team.
* `prefer_team`: use a team key when available; otherwise fall back to normal routing.
* `require_team`: fail requests when no team key exists for the required provider.

Important behavior:

* In `prefer_team` mode, team-billed traffic will not use a member's personal BYOK keys unless the client explicitly opts in to BYOK on the request.

## Security Notes

* Never put provider keys in client-side code or public repos.
* Prefer storing keys once (UI or the `/api/user/provider-keys` endpoints) and then enabling BYOK per request.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.