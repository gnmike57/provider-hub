> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Models

> List available models. The default response is intentionally minimal for OpenAI compatibility; use `detailed=true` for capabilities, supported service tiers, and pricing.

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

## Overview

The `/api/v1/models` endpoint provides a list of available text generation models. It supports optional detailed information including capabilities, supported service tiers, and pricing data. The endpoint maintains full backwards compatibility while adding powerful new features.

The default response deliberately stays close to OpenAI's minimal Models API shape. Enhanced fields such as `supported_service_tiers` are returned only when you add `?detailed=true`.

For non-text model catalogs, use the dedicated catalog endpoints:

* [Image models](/api-reference/endpoint/image-models)
* [Video models](/api-reference/endpoint/video-models)
* [Audio models](/api-reference/endpoint/audio-models)
* [Embedding models](/api-reference/endpoint/embedding-models)

For API-only distillation metadata and filtering, see [Distillation Policy](/api-reference/miscellaneous/distillation-policy).

## Notable Model IDs (Examples)

Model availability changes frequently. Use `GET /api/v1/models` as the authoritative source of callable IDs.
Examples below include canonical IDs and public moving aliases; legacy compatibility aliases are intentionally omitted.

* **OpenAI**: <code>{exampleTextModel}</code>, `openai/gpt-6-astra`, `openai/gpt-latest`
* **Anthropic**: `anthropic/claude-opus-5.5`, `anthropic/claude-sonnet-5.5`, `anthropic/claude-fable-5.1`
* **Google Gemini**: `google/gemini-flash-latest`, `google/gemini-3.8-flash`, `google/gemini-3.1-pro-preview`
* **SpaceXAI Grok**: `x-ai/grok-4.7`, `x-ai/grok-latest`
* **Moonshot Kimi**: `moonshotai/kimi-k3`, `moonshotai/kimi-latest`
* **Z.AI GLM**: `z-ai/glm-5.3`, `z-ai/glm-5.3:thinking`, `z-ai/glm-5.3-flash`
* **Xiaomi MiMo**: `xiaomi/mimo-v2.5-pro`, `xiaomi/mimo-v2.5-pro:thinking`
* **DeepSeek V4**: `deepseek/deepseek-v4.1-flash`, `deepseek/deepseek-v4-flash`, `deepseek/deepseek-latest`
* **MiniMax**: `minimax/minimax-m3`, `minimax/minimax-latest`
* **Qwen**: `qwen/qwen3.8-max`, `qwen/qwen3-coder-next`

## Compatibility

Responses mirror OpenAI's Models API shape. All models endpoints return:

```json theme={null}
{
  "object": "list",
  "data": [ { /* model */ }, ... ]
}
```

Each model minimally includes:

```json theme={null}
{
  "id": "openai/gpt-6.1-sol",
  "object": "model",
  "created": 1736966400,
  "owned_by": "openai"
}
```

## Features

* **Basic Mode**: Standard OpenAI-compatible model listing. Capability and service-tier metadata is omitted.
* **Detailed Mode**: Enhanced information with capabilities, supported service tiers, pricing, and model descriptions.

## Provider Selection Discovery

Provider selection support, public provider IDs, and provider-specific prices are discovered via `GET /api/models/:canonicalId/providers`. Its `Per1kTokens` fields are USD per 1,000 tokens and include selection markup; `provider.max_price` uses USD per 1 million tokens. See [Provider Selection](/api-reference/miscellaneous/provider-selection#discover-providers-and-pricing) for details.

## Query Parameters

| Parameter | Type | Default | Description |
| - | - | - | - |
| `detailed` | boolean | `false` | Returns detailed model information including capabilities, supported service tiers, and pricing |
| `sort` | string | none | Values: `favorites`, `mostused`. Reorders the returned model list. Sorting only affects models that would already be visible to the caller. It does not add or hide models. |

When `detailed=true`, additional fields may be included per model:

* `name` — display name
* `description` — short model description
* `context_length` — max input tokens (if known)
* `max_output_tokens` — max output tokens (if known)
* `capabilities` — feature flags (see below)
* `supported_service_tiers` — alternate `service_tier` values accepted by the model (`flex`, `fast`, and/or the legacy `priority` alias); an empty array means only the default tier is available
* `pricing.prompt` and `pricing.completion` — at-cost per-million-token pricing in USD
* `pricing.unit` — `per_million_tokens`
* `icon_url` — small icon representing the provider
* `cost_estimate` — internal rollup used in UI for cost hints (for example `"$"`, `"$$"`, or an object)
* `category` — optional category tag (for example `"flagship"`, `"mini"`, `"reasoning"`)
* `distillationPolicy` — optional policy metadata indicating whether model outputs may be used for distillation or output-based training under NanoGPT's recorded model-license rules

### Discovering service-tier support

Service-tier availability is model-specific. To discover it programmatically, request the detailed model list and inspect each model's `supported_service_tiers` array:

```bash theme={null}
curl -s "https://nano-gpt.com/api/v1/models?detailed=true" \
  | jq '.data[] | select(.supported_service_tiers | length > 0) | {id, supported_service_tiers}'
```

For example:

```json theme={null}
{
  "id": "openai/gpt-6.1-sol",
  "supported_service_tiers": ["flex", "fast", "priority"]
}
```

* `flex` requests lower-cost, variable-capacity processing.
* `fast` is the preferred public spelling for higher-priority OpenAI processing.
* `priority` remains accepted as a legacy alias and may still be the provider-native name on compatible non-OpenAI routes.
* An empty array means the model supports only the default service tier.

The basic `GET /api/v1/models` response intentionally omits this field for OpenAI compatibility. The [Models page](https://nano-gpt.com/models) also displays service-tier badges for visual discovery. Provider-specific availability can differ when you explicitly force a route; see [Provider Selection](/api-reference/miscellaneous/provider-selection).

### Discovering video-capable models

For multimodal input, call `GET /api/v1/models?detailed=true` and select a model whose catalog entry advertises video input. Catalog fields are additive, so inspect both the architecture modalities and capability flags when present:

```json theme={null}
{
  "id": "google/gemini-3.1-flash-lite",
  "architecture": { "input_modalities": ["text", "image", "video"] },
  "capabilities": { "video_input": true }
}
```

An explicitly selected model without video capability is rejected before provider dispatch and billing. Automatic fallback keeps only routes that preserve the requested video input. See [Video Input](/api-reference/miscellaneous/video-input) for the endpoint content shapes and source rules.

### Sorting model lists

`GET /api/v1/models` supports `sort=favorites` and `sort=mostused`.

When `sort` is present, NanoGPT returns the same model list the caller would normally receive, but reordered by the selected ranking. Sorting only affects models that would already be visible to the caller. It does not add or hide models.

* `sort=favorites`: Orders models by the authenticated account's recent model usage.
* `sort=mostused`: Orders models by global completed model usage.
* Unused or unranked models remain in the response after ranked models, in the normal catalog order.
* `sort=favorites` requires a valid API key to personalize the order. If no valid API key is provided, it falls back to normal ordering.
* `sort=mostused` does not require authentication.
* Invalid `sort` values are ignored.
* Can be combined with `detailed=true`.

Examples:

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/v1/models?sort=favorites"
```

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?sort=mostused"
```

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/v1/models?detailed=true&sort=favorites"
```

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?detailed=true&sort=mostused"
```

### `capabilities` (detailed mode)

Common capability flags:

| Field | Type | Description |
| - | - | - |
| `vision` | boolean | Supports image inputs |
| `reasoning` | boolean | Supports extended thinking/reasoning |
| `tool_calling` | boolean | Supports function/tool calling |
| `parallel_tool_calls` | boolean | Supports multiple tool calls in parallel |
| `structured_output` | boolean | Supports structured/JSON output modes |
| `pdf_upload` | boolean | Supports PDF/document inputs |
| `video_input` | boolean | Supports video inputs for text or multimodal understanding |

## Authentication

Authentication is optional but enables user-specific pricing in detailed mode:

| Header | Format | Required | Description |
| - | - | - | - |
| `Authorization` | `Bearer {api_key}` | Optional | API key for user-specific pricing |
| `x-api-key` | `{api_key}` | Optional | Alternative API key header |

Notes:

* Invalid or missing API keys still return a list of models. We simply omit user-specific pricing considerations in `detailed=true` mode.
* With a valid key, the canonical `/api/v1/models` may apply your account’s subscription visibility preference (see Endpoint Variants).

## Response Formats

### Basic Response (Default)

Standard OpenAI-compatible format without pricing information:

```json theme={null}
{
  "object": "list",
  "data": [
    {
      "id": "openai/gpt-6.1-sol",
      "object": "model",
      "created": 1790640000,
      "owned_by": "openai"
    },
    {
      "id": "anthropic/claude-opus-5.5",
      "object": "model", 
      "created": 1790035200,
      "owned_by": "anthropic"
    }
  ]
}
```

### Detailed Response

Enhanced format with model descriptions, context lengths, and pricing:

```json theme={null}
{
  "object": "list",
  "data": [
    {
      "id": "openai/gpt-6.1-sol",
      "object": "model",
      "created": 1790640000,
      "owned_by": "openai",
      "name": "GPT 6.1 Sol",
      "description": "GPT-6.1 Sol delivers near-Astra performance at a lower cost for complex coding, computer use, and professional work. It supports text and image input, tool calling, structured outputs, and reasoning from low through max.",
      "context_length": 1050000,
      "max_output_tokens": 128000,
      "supported_service_tiers": [
        "flex",
        "fast",
        "priority"
      ],
      "capabilities": {
        "vision": true,
        "video_input": false,
        "audio_input": false,
        "reasoning": true,
        "tool_calling": true,
        "parallel_tool_calls": false,
        "structured_output": true,
        "pdf_upload": true,
        "batch_api": true
      },
      "pricing": {
        "prompt": 2,
        "completion": 10,
        "cacheReadInputPer1kTokens": 0.0001,
        "cacheWriteInputPer1kTokens": 0.0025,
        "currency": "USD",
        "unit": "per_million_tokens"
      }
    },
    {
      "id": "anthropic/claude-opus-5.5",
      "object": "model",
      "created": 1790035200,
      "owned_by": "anthropic",
      "name": "Claude Opus 5.5",
      "description": "Claude Opus 5.5 is Anthropic's flagship model for agentic coding, computer use, complex knowledge work, and long-running tasks, with improved efficiency and more natural communication.",
      "context_length": 1000000,
      "max_output_tokens": 128000,
      "supported_service_tiers": [],
      "capabilities": {
        "vision": true,
        "video_input": false,
        "audio_input": false,
        "reasoning": true,
        "tool_calling": true,
        "parallel_tool_calls": false,
        "structured_output": true,
        "pdf_upload": true,
        "batch_api": true
      },
      "pricing": {
        "prompt": 4,
        "completion": 20,
        "cacheReadInputPer1kTokens": 0.0002,
        "cacheWriteInputPer1kTokens": 0.005,
        "currency": "USD",
        "unit": "per_million_tokens"
      }
    }
  ]
}
```

## Field Descriptions

### Basic Fields (Always Present)

| Field | Type | Description |
| - | - | - |
| `id` | string | Unique model identifier |
| `object` | string | Always "model" for OpenAI compatibility |
| `created` | number | Unix timestamp of response creation |
| `owned_by` | string | Model provider (openai, anthropic, meta, google, etc.) |

### Enhanced Fields (Detailed Mode Only)

| Field | Type | Description |
| - | - | - |
| `name` | string | Human-readable model name |
| `description` | string | Detailed model description |
| `context_length` | number | Maximum input tokens (null if not available) |
| `max_output_tokens` | number | Maximum output tokens (null if not available) |
| `capabilities` | object | Feature flags (e.g., `vision: boolean`) |
| `supported_service_tiers` | string\[] | Alternate service tiers accepted by the model. An empty array means only the default tier is available. |
| `pricing` | object | Pricing information object |
| `icon_url` | string | Path/URL for a small provider icon |
| `cost_estimate` | string or object | Internal hints (for example `"$"` / `"$$"` or `{ cheap: true }`) |
| `category` | string | Optional category (e.g., `"flagship"`, `"mini"`, `"reasoning"`) |
| `distillationPolicy` | object | Optional API-only distillation metadata. See [Distillation Policy](/api-reference/miscellaneous/distillation-policy). |

### Pricing Object Structure

| Field | Type | Description |
| - | - | - |
| `prompt` | number | Cost per million input tokens in USD |
| `completion` | number | Cost per million output tokens in USD |
| `currency` | string | Always "USD" |
| `unit` | string | Always "per\_million\_tokens" |

### Distillation Policy

Where available, text model records include a `distillationPolicy` object with `status`, `label`, `basis`, `sourceUrl`, and `note`. This indicates whether model outputs may be used for model training, fine-tuning, distillation, or similar model-improvement workflows under NanoGPT's recorded interpretation of model licenses and provider terms.

```json theme={null}
{
  "distillationPolicy": {
    "status": "allowed",
    "label": "License permits distillation",
    "basis": "permissive-open-weights",
    "sourceUrl": "https://example.com/license-or-terms",
    "note": "Short explanation of the policy signal."
  }
}
```

Use the explore endpoints when you need to filter for distillation-allowed text models:

```http theme={null}
GET /api/explore/text-models?distillation=allowed
```

```http theme={null}
GET /api/explore/search?type=text&q=qwen&distillation=allowed
```

The filter applies only to text models. Responses include `meta.distillation: "allowed"` when the filter is used and `meta.distillation: "all"` otherwise.

Provider route policy can differ from model-level policy. Use `GET /api/models/:canonicalId/providers` and inspect each provider row's `distillationPolicy` before relying on a specific route for distillation.

This metadata is informational and is not legal advice. Provider terms and model licenses can change, and licenses may impose attribution, naming, acceptable-use, or derivative-model restrictions even when distillation is allowed.

## Usage Examples

### Basic Request

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models"
```

### Detailed Request

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?detailed=true"
```

### Sort by Favorites

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/v1/models?sort=favorites"
```

### Sort by Most Used

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?sort=mostused"
```

### Detailed and Sorted

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/v1/models?detailed=true&sort=favorites"
```

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?detailed=true&sort=mostused"
```

### Detailed with Authentication

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?detailed=true" \
  -H "Authorization: Bearer your_api_key_here"
```

### Alternative API Key Header

```bash theme={null}
curl "https://nano-gpt.com/api/v1/models?detailed=true" \
  -H "x-api-key: your_api_key_here"
```

## Endpoint Variants

In addition to the canonical `/api/v1/models`, two filtered variants are available:

### 1) GET /api/v1/models (canonical)

* Returns all visible text models (excludes internal free/helper selector models except `auto-model*`).
* If your account has an active subscription and you have not enabled “Also show paid models”, the list is automatically restricted to only subscription-included models.
* If you enable “Also show paid models” in settings, it returns the full set again.

Examples:

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  https://nano-gpt.com/api/v1/models
```

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/v1/models?detailed=true"
```

### 2) GET /api/subscription/v1/models (subscription-only)

* Always returns only models included in the NanoGPT subscription (equivalent to our `isTextEligible(modelId)` filter).
* Ignores the user’s “Also show paid models” preference; it is always subscription-only.
* Supports `?detailed=true` and API key–aware, at-cost pricing metadata.

Examples:

```bash theme={null}
curl https://nano-gpt.com/api/subscription/v1/models
```

```bash theme={null}
curl -H "x-api-key: $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/subscription/v1/models?detailed=true"
```

### 3) GET /api/paid/v1/models (paid/extras)

* Returns only models that are NOT part of the subscription (paid/premium/extras).
* Supports `?detailed=true` and API key–aware, at-cost pricing metadata.

Examples:

```bash theme={null}
curl https://nano-gpt.com/api/paid/v1/models
```

```bash theme={null}
curl -H "Authorization: Bearer $NANOGPT_API_KEY" \
  "https://nano-gpt.com/api/paid/v1/models?detailed=true"
```

### Choosing the Right Endpoint

* Use `/api/subscription/v1/models` for curated lists guaranteed to be subscription-included (e.g., sub-only integrations).
* Use `/api/paid/v1/models` to focus on paid or premium models.
* Use `/api/v1/models` for the canonical list and let the account’s “Also show paid models” preference decide visibility.

## Errors and Limits

* These endpoints typically return `200` with a list. If an invalid API key is provided, the list still returns and simply omits user-specific pricing considerations in `detailed=true` mode.
* Standard CORS and rate limiting apply. In overload scenarios you may receive `429` with:

```json theme={null}
{ "code": "rate_limited", "message": "Rate limit exceeded" }
```

## Backwards Compatibility

* Default response format unchanged
* All existing fields preserved
* New fields are additive only
* No breaking changes to existing integrations

## Related Endpoints

* [Image models](/api-reference/endpoint/image-models) - List image model capabilities and supported parameters
* [Video models](/api-reference/endpoint/video-models) - List video model capabilities and supported parameters
* [Audio models](/api-reference/endpoint/audio-models) - List text-to-speech and speech-to-text models
* [Embedding models](/api-reference/endpoint/embedding-models) - List embedding model dimensions, token limits, and pricing
* [/api/v1/embeddings](/api-reference/endpoint/embeddings) - Create embeddings using the available embedding models
* [Provider Selection](/api-reference/miscellaneous/provider-selection) - Discover model providers and set provider preferences
* `/api/subscription/v1/models` - Subscription-included text models
* `/api/paid/v1/models` - Paid or premium text models

## Notes

* Scope: These endpoints list text-chat models. For image, video, audio, and embedding catalogs, use the dedicated model catalog pages linked above.
* Fields are subject to change as new capabilities or providers are added. We aim to remain OpenAI-API compatible for basic consumers (`id`/`object`/`created`/`owned_by`).


## OpenAPI

````yaml GET /v1/models
openapi: 3.1.0
info:
  title: NanoGPT API
  description: >-
    API documentation for the NanoGPT language, image, video, speech-to-text,
    and text-to-speech generation services
  license:
    name: MIT
  version: 1.0.0
servers:
  - url: https://api.nano-gpt.com/api
    description: >-
      Direct API for uploads and long-running requests; choose a model listed by
      this host
  - url: https://nano-gpt.com/api
    description: Website API for current text model examples
security: []
paths:
  /v1/models:
    servers:
      - url: https://nano-gpt.com/api
        description: Website API (current text model catalog)
      - url: https://api.nano-gpt.com/api
        description: Direct API; choose a model listed by this host
    get:
      description: >-
        List available models. The default response is intentionally minimal for
        OpenAI compatibility; use `detailed=true` for capabilities, supported
        service tiers, and pricing.
      parameters:
        - name: detailed
          in: query
          description: >-
            Returns detailed model information including capabilities,
            `supported_service_tiers`, and pricing. Inspect
            `supported_service_tiers` to discover whether a model accepts
            `flex`, `fast`, or the legacy `priority` alias; an empty array means
            only the default tier is available.
          required: false
          schema:
            type: boolean
            default: false
        - name: sort
          in: query
          description: >-
            Reorders the returned model list without adding or hiding models.
            `favorites` orders by the authenticated account's recent model usage
            and requires a valid API key; without one it falls back to normal
            ordering. `mostused` orders by global completed model usage and does
            not require authentication. Unused or unranked models remain after
            ranked models in normal catalog order. Invalid values are ignored.
          required: false
          schema:
            type: string
            enum:
              - favorites
              - mostused
            example: favorites
      responses:
        '200':
          description: List of available models
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModelsResponse'
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    ModelsResponse:
      type: object
      properties:
        object:
          type: string
          description: Type of object, always 'list' for the models response
          default: list
        data:
          type: array
          description: List of available models
          items:
            type: object
            properties:
              id:
                type: string
                description: Unique identifier for the model
                example: openai/gpt-6.1-sol
              object:
                type: string
                description: Type of object, always 'model'
                default: model
              created:
                type: integer
                description: Unix timestamp when the model was created
              owned_by:
                type: string
                description: Organization that owns the model
                example: openai
              name:
                type: string
                description: Human-readable model name (detailed mode only)
                example: GPT-4o Mini
              description:
                type: string
                description: Detailed model description (detailed mode only)
                example: >-
                  OpenAI's affordable and intelligent small model for fast,
                  lightweight tasks
              context_length:
                type: integer
                description: >-
                  Maximum input tokens (detailed mode only, null if not
                  available)
                example: 128000
              max_output_tokens:
                type:
                  - integer
                  - 'null'
                description: >-
                  Maximum generated output tokens (detailed mode only, null if
                  no serving-route limit is known)
                example: 16384
              capabilities:
                type: object
                description: >-
                  Model capability flags such as vision, reasoning, tool
                  calling, structured output, PDF upload, video input, and Batch
                  API support (detailed mode only)
                additionalProperties:
                  type: boolean
              supported_service_tiers:
                type: array
                description: >-
                  Alternate service tiers accepted by the model (detailed mode
                  only). Fast is the preferred public spelling for
                  higher-priority OpenAI processing; priority remains accepted
                  as a legacy alias. An empty array means only the default
                  service tier is available.
                items:
                  type: string
                  enum:
                    - flex
                    - fast
                    - priority
                uniqueItems: true
                example:
                  - flex
                  - fast
                  - priority
              pricing:
                type: object
                description: Pricing information object (detailed mode only)
                properties:
                  prompt:
                    type: number
                    description: Cost per million input tokens in USD
                    example: 0.00015
                  completion:
                    type: number
                    description: Cost per million output tokens in USD
                    example: 0.0006
                  currency:
                    type: string
                    description: Always 'USD'
                    default: USD
                  unit:
                    type: string
                    description: Always 'per_million_tokens'
                    default: per_million_tokens
              distillationPolicy:
                $ref: '#/components/schemas/DistillationPolicy'
    Error:
      required:
        - error
        - message
      type: object
      properties:
        error:
          type: integer
          format: int32
        message:
          type: string
    DistillationPolicy:
      type: object
      description: >-
        API-only policy metadata indicating whether model or provider-route
        outputs may be used for model training, fine-tuning, distillation, or
        similar model-improvement workflows under NanoGPT's recorded
        model-license and provider-terms rules.
      properties:
        status:
          type: string
          description: Whether distillation is allowed under the current recorded rule set.
          enum:
            - allowed
            - disallowed
            - unknown
          example: allowed
        label:
          type: string
          description: Human-readable policy summary.
          example: License permits distillation
        basis:
          type: string
          description: Rule basis used to derive the policy status.
          enum:
            - deepseek-api-terms
            - permissive-open-weights
            - provider-output-use-terms
            - provider-output-use-restriction
            - closed-provider-restriction
            - provider-terms-unknown
          example: permissive-open-weights
        sourceUrl:
          type: string
          description: >-
            License or provider terms URL used as the policy source, when
            recorded.
          format: uri
          example: https://example.com/license-or-terms
        note:
          type: string
          description: Short explanation and caveats for the policy signal.
          example: Short explanation of the policy signal.
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
    apiKeyAuth:
      type: apiKey
      in: header
      name: x-api-key

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.