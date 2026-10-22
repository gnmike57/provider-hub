> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Messages

> Accepts Anthropic Messages requests, including video blocks for models that advertise video input. Authenticate with an API key using the Authorization: Bearer header or the x-api-key header.

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

<Note>
  To set reasoning effort through a custom model ID, append `:reasoning-effort/high` (also `none`, `low`, `medium`, `xhigh`, or `max`). NanoGPT strips the suffix before routing and uses it as the default `output_config.effort` for enabled reasoning levels. `:reasoning-effort/none` instead supplies `thinking: { type: "disabled" }`; `output_config.effort: "none"` is not accepted. Explicit body generation settings, including enabled thinking, take precedence over `none`. The suffix does not bypass model/provider restrictions. See [Reasoning Effort Suffixes](/api-reference/miscellaneous/model-suffixes#reasoning-effort-suffixes).
</Note>

<Note>
  **API host:** Use `https://nano-gpt.com/api` as the base URL for the Anthropic SDK, which appends `/v1/messages`. For raw HTTP requests, use `https://nano-gpt.com/api/v1/messages`. See [API Hosts](/api-reference/miscellaneous/api-hosts).
</Note>

<Note>
  `/v1/messages` accepts **compressed request bodies** (`Content-Encoding: gzip`, `deflate`, or `br`) on authenticated JSON requests — useful for long conversations, where compressed uploads cut time-to-first-token. See [Compressed Request Bodies](/api-reference/miscellaneous/request-compression).
</Note>

## Overview

The `/v1/messages` endpoint provides full Anthropic API compatibility. Clients using the Anthropic SDK can use NanoGPT by simply changing the base URL -- no code changes required.

NanoGPT accepts requests in the **Anthropic Messages** format, routes them to the requested NanoGPT model, and returns responses back in the Anthropic Messages shape.

For non‑Anthropic models, NanoGPT transparently translates the request to an OpenAI-style chat format internally and then converts the response back to Anthropic Messages format.

<Note>
  Decision models (Jev, Decider, Liquid D1, PPLX Decider v1.1, Clef and Clef Flash) use `output_config.format: {"type":"questions","questions":{...}}`, accept only non-streaming user text, and return the answer object as JSON text in `content[0].text`. See [Decisions](/api-reference/endpoint/decisions) for complete examples and limitations.
</Note>

This endpoint supports:

* Text generation (streaming and non-streaming)
* Multi-turn conversations
* Tool use (function calling)
* Vision (images), video understanding, and document/PDF processing
* Extended thinking (reasoning models)
* Prompt caching
* Token estimates via [`POST /api/v1/messages/count_tokens`](/api-reference/endpoint/messages-count-tokens)

For asynchronous Claude requests at batch token rates, use [Anthropic Message Batches](/api-reference/endpoint/batches#anthropic-message-batches). The native batch API supports create, list, retrieve, cancel, results, and delete through the official Anthropic SDK. It accepts supported Claude models, with one model per batch and a required `max_tokens` for each request; synchronous Messages model support does not imply batch support.

## Endpoint

```
POST https://nano-gpt.com/api/v1/messages
```

## Authentication

Use either header:

* `Authorization: Bearer YOUR_API_KEY`
* `x-api-key: YOUR_API_KEY`

## Request Format

### Required Fields

| Field | Type | Description |
| - | - | - |
| `model` | string | Model identifier (any NanoGPT model, including non‑Anthropic models) |
| `max_tokens` | number | Maximum tokens to generate (must be a finite number) |
| `messages` | array | Array of conversation messages |

### Optional Fields

| Field | Type | Default | Description |
| - | - | - | - |
| `system` | string or array | -- | System prompt (string or array of text blocks) |
| `stream` | boolean | `false` | Enable streaming responses |
| `temperature` | number | -- | Sampling temperature |
| `top_p` | number | -- | Nucleus sampling parameter |
| `top_k` | number | -- | Top-k sampling parameter |
| `stop_sequences` | string\[] | -- | Custom stop sequences |
| `tools` | array | -- | Tool definitions for function calling |
| `tool_choice` | string or object | -- | Control tool selection behavior |
| `disable_parallel_tool_use` | boolean | -- | Disable parallel tool calls |
| `thinking` | object | -- | Enable extended thinking for supported models |
| `metadata` | object | -- | Request metadata (`user` or `user_id`) |
| `service_tier` | string | -- | Service tier: `"auto"`, `"default"`, `"standard"`, `"flex"`, `"fast"`, the legacy `"priority"` alias, or `"batch"` |

### Message Format

Messages must have a `role` (`user` or `assistant`) and `content`:

```json theme={null}
{
  "role": "user",
  "content": "Hello!"
}
```

Or with structured content blocks:

```json theme={null}
{
  "role": "user",
  "content": [
    { "type": "text", "text": "What's in this image?" },
    {
      "type": "image",
      "source": {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": "<base64-encoded-image>"
      }
    }
  ]
}
```

### Content Block Types

#### Text Block

```json theme={null}
{ "type": "text", "text": "Your message here" }
```

#### Image Block (for vision-capable models)

```json theme={null}
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/jpeg",
    "data": "<base64-data>"
  }
}
```

Or with URL:

```json theme={null}
{
  "type": "image",
  "source": {
    "type": "url",
    "url": "https://example.com/image.jpg"
  }
}
```

Supported media types: `image/jpeg`, `image/png`, `image/gif`, `image/webp`

#### Document Block (for PDF-capable models)

```json theme={null}
{
  "type": "document",
  "source": {
    "type": "base64",
    "media_type": "application/pdf",
    "data": "<base64-data>"
  }
}
```

#### Video Block (for video-capable models)

Use `type: "video"` for new integrations. Inline video bytes use an Anthropic base64 source:

```json theme={null}
{
  "type": "video",
  "source": {
    "type": "base64",
    "media_type": "video/mp4",
    "data": "AAAA..."
  }
}
```

For URL transport, use an HTTPS URL and declare the video MIME type:

```json theme={null}
{
  "type": "video",
  "source": {
    "type": "url",
    "url": "https://cdn.example.com/clip.mp4",
    "media_type": "video/mp4"
  }
}
```

A `document` compatibility block with a `video/*` source is normalized as video. A document with `application/pdf` remains a document. Public remote sources must use HTTPS; inline base64 must be valid. See the [Video Input guide](/api-reference/miscellaneous/video-input) for model discovery, limits, errors, segment behavior, and the equivalent Chat Completions and Responses shapes.

#### Tool Use Block (in assistant messages)

```json theme={null}
{
  "type": "tool_use",
  "id": "tool_abc123",
  "name": "get_weather",
  "input": { "city": "Paris" }
}
```

#### Tool Result Block (in user messages)

```json theme={null}
{
  "type": "tool_result",
  "tool_use_id": "tool_abc123",
  "content": "The weather in Paris is sunny, 22 C"
}
```

### Tool Definitions

```json theme={null}
{
  "tools": [
    {
      "name": "get_weather",
      "description": "Get current weather for a city",
      "input_schema": {
        "type": "object",
        "properties": {
          "city": { "type": "string", "description": "City name" }
        },
        "required": ["city"]
      }
    }
  ]
}
```

### Tool Choice Options

| Value | Description |
| - | - |
| `"auto"` | Model may use tools if appropriate |
| `"none"` | Disable tool use for this request |
| `"any"` | Model must use at least one tool |
| `"required"` | Model must use at least one tool |
| `{"type": "tool", "name": "tool_name"}` | Force use of a specific tool |

### Extended Thinking

For models that support extended thinking (reasoning):

```json theme={null}
{
  "thinking": {
    "type": "enabled",
    "budget_tokens": 8192
  }
}
```

Requirements:

* `budget_tokens` must be >= 1024
* `budget_tokens` must be \< `max_tokens`
* Model must support thinking for the exact model ID you send (check `GET /api/v1/models`)

`:thinking` is model-specific and only works when that exact ID (or a documented alias) exists.
`-thinking` is a legacy alias pattern for some model families only, not universal.
Do not assume `-thinking` works for arbitrary model IDs. Always check `GET /api/v1/models` for exact valid IDs.

If the requested model does not support thinking, NanoGPT automatically ignores/strips the `thinking` parameter and routes the request to the base model.

For Chat Completions compatibility controls, `:reasoning-exclude` (or `reasoning.exclude`) only hides reasoning output; it does not force reasoning compute off. Use `reasoning_effort` / `reasoning.effort` to control reasoning depth, and set `none` to disable reasoning behavior.

## Change Effort Within a Conversation

GPT-6 Astra and Claude Fable 5.1 support [inline reasoning effort updates](/api-reference/miscellaneous/inline-reasoning-effort) using an empty system message: `{"role":"system","content":[],"output_config":{"effort":"high"}}`. Set the baseline with request-level `output_config.effort` and leave it unchanged. A trailing update applies to the generated answer; preserve it before assistant output when replaying history. This Messages form requires the `system` role.

## Response Format

### Non-Streaming Response

```json theme={null}
{
  "id": "msg_abc123",
  "type": "message",
  "role": "assistant",
  "model": "claude-opus-4-5-20251101",
  "content": [
    { "type": "text", "text": "Hello! How can I help you today?" }
  ],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 12,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation": {
      "ephemeral_5m_input_tokens": 0,
      "ephemeral_1h_input_tokens": 0
    },
    "service_tier": "standard"
  }
}
```

### Stop Reasons

| Stop Reason | Description |
| - | - |
| `end_turn` | Natural end of response |
| `max_tokens` | Hit token limit |
| `stop_sequence` | Hit a custom stop sequence |
| `tool_use` | Model wants to use a tool |
| `content_filter` | Content was filtered |

### Streaming Response (SSE)

See also: [Streaming Protocol (SSE)](/api-reference/miscellaneous/streaming-protocol).

When `stream: true`, the response is Server-Sent Events with named event types:

#### Event: message\_start

```text theme={null}
event: message_start
data: {"type": "message_start", "message": {"id": "msg_abc", "type": "message", "role": "assistant", "model": "claude-opus-4-5-20251101", "content": [], "stop_reason": null, "usage": {"input_tokens": 10, "output_tokens": 0}}}
```

#### Event: content\_block\_start

```text theme={null}
event: content_block_start
data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
```

#### Event: content\_block\_delta

```text theme={null}
event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}
```

#### Event: content\_block\_stop

```text theme={null}
event: content_block_stop
data: {"type": "content_block_stop", "index": 0}
```

#### Event: message\_delta

```text theme={null}
event: message_delta
data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 12}}
```

#### Event: message\_stop

```text theme={null}
event: message_stop
data: {"type": "message_stop"}
```

### Streaming Tool Use

When the model uses tools during streaming:

```text theme={null}
event: content_block_start
data: {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tool_abc", "name": "get_weather", "input": {}}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{\"city\":"}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": " \"Paris\"}"}}

event: content_block_stop
data: {"type": "content_block_stop", "index": 0}
```

## Supported Models

### Claude Models (Full Support)

| Model | Streaming | Tools | Vision | Thinking |
| - | - | - | - | - |
| claude-opus-4-6 | Yes | Yes | Yes | Yes\* |
| claude-opus-4-5-20251101 | Yes | Yes | Yes | Yes\* |
| claude-opus-4-1-20250805 | Yes | Yes | Yes | Yes\* |
| claude-sonnet-4-5-20250929 | Yes | Yes | Yes | Yes\* |

\*Use only exact thinking-capable model IDs from `GET /api/v1/models`.

### Other Models (Via Compatibility Layer)

The v1/messages endpoint also works with non-Anthropic models:

| Model | Streaming | Tools | Vision |
| - | - | - | - |
| {exampleTextModel} | Yes | Yes | Yes |
| google/gemini-3-flash-preview | Yes | Yes | Yes |
| google/gemini-3.1-pro-preview | Yes | Yes | Yes |
| zai-org/glm-4.7 | Yes | Yes | -- |

See the [Models documentation](/api-reference/endpoint/models) for the full list.

## Prompt Caching

For the full guide (supported models, thresholds, pricing, and usage fields), see [Prompt Caching](/api-reference/miscellaneous/prompt-caching).

NanoGPT automatically applies implicit caching on providers/models that support it (including OpenAI, Gemini, and many open-source provider/model routes), with no extra request flags.

Use explicit prompt-caching controls on Claude when you need deterministic cache boundaries, TTL selection, or `stickyProvider` consistency control.

### Enable via Header

```
anthropic-beta: prompt-caching-2024-07-31
```

### TTL Options

* Default: 5-minute cache TTL
* Extended: Add `extended-cache-ttl-2025-04-11` to request 1-hour TTL on Anthropic-native Claude flows

### Cache Control in Content (Explicit Claude Controls)

Add `cache_control` to content blocks for explicit Claude caching:

```json theme={null}
{
  "type": "text",
  "text": "This is a long system prompt...",
  "cache_control": { "type": "ephemeral" }
}
```

### Cache Usage in Response

```json theme={null}
{
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_creation_input_tokens": 80,
    "cache_read_input_tokens": 0
  }
}
```

## Error Handling

For a general guide across NanoGPT APIs, see [Error Handling](/api-reference/miscellaneous/error-handling).

### Error Response Format

```json theme={null}
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "max_tokens is required",
    "param": "max_tokens"
  }
}
```

### Error Types

| HTTP Status | Error Type | Description |
| - | - | - |
| 400 | `invalid_request_error` | Invalid request (missing fields, bad format) |
| 401 | `authentication_error` | Invalid or missing API key |
| 403 | `permission_error` | Insufficient permissions |
| 404 | `not_found_error` | Unknown model |
| 429 | `rate_limit_error` | Rate limit exceeded |
| 500+ | `api_error` | Server error |

All error responses include an `X-Request-ID` header for support requests.

## Headers

### Request Headers

| Header | Required | Description |
| - | - | - |
| `Authorization` | Yes\* | Bearer token authentication |
| `x-api-key` | Yes\* | Alternative API key header |
| `Content-Type` | Yes | Must be `application/json` |
| `anthropic-beta` | No | Enable beta features (e.g., prompt caching) |
| `anthropic-version` | No | API version (accepted but not required) |

\*One of `Authorization` or `x-api-key` is required.

### BYOK Headers

For Bring Your Own Key:

| Header | Description |
| - | - |
| `x-use-byok` | Set to `true` to use your own API key |
| `x-byok-provider` | Provider name for your key |

## Examples

### Basic Request (cURL)

```bash theme={null}
curl -X POST https://nano-gpt.com/api/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "claude-opus-4-5-20251101",
    "max_tokens": 256,
    "messages": [
      { "role": "user", "content": "Hello!" }
    ]
  }'
```

### Streaming Request (cURL)

```bash theme={null}
curl -N -X POST https://nano-gpt.com/api/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "claude-opus-4-5-20251101",
    "stream": true,
    "max_tokens": 256,
    "messages": [{ "role": "user", "content": "Hello!" }]
  }'
```

### With Tools (cURL)

```bash theme={null}
curl -X POST https://nano-gpt.com/api/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "claude-opus-4-5-20251101",
    "max_tokens": 1024,
    "tools": [
      {
        "name": "get_weather",
        "description": "Get current weather",
        "input_schema": {
          "type": "object",
          "properties": {
            "city": { "type": "string" }
          },
          "required": ["city"]
        }
      }
    ],
    "messages": [
      { "role": "user", "content": "What is the weather in Tokyo?" }
    ]
  }'
```

### Anthropic SDK (Node.js)

```typescript theme={null}
import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic({
  apiKey: process.env.NANOGPT_API_KEY,
  baseURL: "https://nano-gpt.com/api"
});

const message = await anthropic.messages.create({
  model: "claude-opus-4-5-20251101",
  max_tokens: 256,
  messages: [
    { role: "user", content: "Hello!" }
  ]
});

console.log(message.content[0].text);
```

### Anthropic SDK with Streaming (Node.js)

```typescript theme={null}
import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic({
  apiKey: process.env.NANOGPT_API_KEY,
  baseURL: "https://nano-gpt.com/api"
});

const stream = await anthropic.messages.stream({
  model: "claude-opus-4-5-20251101",
  max_tokens: 256,
  messages: [
    { role: "user", content: "Tell me a story" }
  ]
});

for await (const event of stream) {
  if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
    process.stdout.write(event.delta.text);
  }
}
```

### Anthropic SDK with Prompt Caching (Node.js)

```typescript theme={null}
import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic({
  apiKey: process.env.NANOGPT_API_KEY,
  baseURL: "https://nano-gpt.com/api"
});

const message = await anthropic.messages.create({
  model: "claude-opus-4-5-20251101",
  max_tokens: 256,
  system: [
    {
      type: "text",
      text: "You are a helpful assistant with expertise in...",
      cache_control: { type: "ephemeral" }
    }
  ],
  messages: [
    { role: "user", content: "Hello!" }
  ]
}, {
  headers: {
    "anthropic-beta": "prompt-caching-2024-07-31"
  }
});
```

### Vision Example (Node.js)

```typescript theme={null}
import Anthropic from "@anthropic-ai/sdk";
import fs from "fs";


const anthropic = new Anthropic({
  apiKey: process.env.NANOGPT_API_KEY,
  baseURL: "https://nano-gpt.com/api"
});

const imageData = fs.readFileSync("image.jpg").toString("base64");

const message = await anthropic.messages.create({
  model: "claude-opus-4-5-20251101",
  max_tokens: 1024,
  messages: [
    {
      role: "user",
      content: [
        { type: "text", text: "What's in this image?" },
        {
          type: "image",
          source: {
            type: "base64",
            media_type: "image/jpeg",
            data: imageData
          }
        }
      ]
    }
  ]
});
```

### Python SDK

```python theme={null}
import anthropic

client = anthropic.Anthropic(
    api_key="YOUR_NANOGPT_API_KEY",
    base_url="https://nano-gpt.com/api"
)

message = client.messages.create(
    model="claude-opus-4-5-20251101",
    max_tokens=256,
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)

print(message.content[0].text)
```

## Limits

| Limit | Value |
| - | - |
| Request timeout | 800 seconds |
| Tool argument size | \~100 KB per tool call |
| Image types | JPEG, PNG, GIF, WebP |

## Limitations

* GPU-TEE models do not support streaming through `POST /api/v1/messages`. Use `POST /api/v1/chat/completions` if you need streaming with GPU-TEE models.

## Migration from Anthropic

To migrate from Anthropic's API to NanoGPT:

1. Change the base URL:

   * From: `https://api.anthropic.com`
   * To: `https://nano-gpt.com/api`

   The full endpoint will be: `https://nano-gpt.com/api/v1/messages`

2. Use your NanoGPT API key instead of your Anthropic key

3. No other code changes required -- the API is fully compatible

## Service tier compatibility

Anthropic-style service tiers are normalized when routing to providers that support service tiers:

* `standard` → `default`
* `default` → `default`
* `flex` → `flex`
* `fast` → higher-priority processing where supported
* `priority` → legacy alias for `fast` on OpenAI models; compatible non-OpenAI providers may continue to use the Priority name
* `batch` → ignored for service-tier routing

Before sending a tiered request, call [`GET /api/v1/models?detailed=true`](/api-reference/endpoint/models) and inspect the selected model's `supported_service_tiers` array. The basic model list intentionally omits this field for OpenAI compatibility. An empty array means the model supports only the default tier.

Flex and Fast/Priority availability is model- and provider-specific. If you explicitly force a provider that does not support service tiers, the requested tier may be ignored by the upstream provider, or routing and pricing may differ from the default route.

## Notes

* The `anthropic-version` header is accepted but not required
* Token usage numbers use NanoGPT's token accounting (may differ slightly from Anthropic's exact counts)
* All Anthropic SDK features are supported, including streaming, tools, and caching


## OpenAPI

````yaml POST /v1/messages
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
  /v1/messages:
    servers:
      - url: https://nano-gpt.com/api
        description: Website API (current model examples)
      - url: https://api.nano-gpt.com/api
        description: Direct API; choose a model listed by this host
    post:
      tags:
        - Anthropic
      summary: Create an Anthropic-compatible message
      description: >-
        Accepts Anthropic Messages requests, including video blocks for models
        that advertise video input. Authenticate with an API key using the
        Authorization: Bearer header or the x-api-key header.
      operationId: createMessage
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/AnthropicMessageRequest'
      responses:
        '200':
          description: Anthropic message response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AnthropicMessage'
            text/event-stream:
              schema:
                type: string
        '400':
          description: >-
            Bad Request. Video errors include video_input_not_supported,
            invalid_video_url_scheme, invalid_video_data_url,
            invalid_video_base64, invalid_video_mime_type, missing_video_source,
            video_file_id_not_supported, invalid_video_segment,
            video_segment_not_supported, and youtube_video_route_not_supported.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    AnthropicMessageRequest:
      type: object
      required:
        - model
        - messages
      properties:
        output_config:
          $ref: '#/components/schemas/InlineReasoningEffort'
          description: >-
            Request-level effort baseline. Keep unchanged when using inline
            output_config updates.
        model:
          type: string
          description: >-
            Model ID or compatibility alias. Append :reasoning-effort/<effort>,
            where effort is none, low, medium, high, xhigh, or max, to supply a
            default output_config.effort for enabled reasoning levels; none
            instead supplies thinking: { type: "disabled" }. The suffix is
            stripped before model routing and is not listed as a separate model.
            Explicit reasoning generation settings take precedence, including
            enabled thinking when the suffix is none. The none suffix requests
            disabled reasoning where supported; it does not bypass
            model/provider restrictions. Other effort levels remain
            model/provider-specific.
        max_tokens:
          type: integer
        messages:
          type: array
          items:
            type: object
            required:
              - role
            properties:
              role:
                type: string
                enum:
                  - user
                  - assistant
                  - system
              content:
                oneOf:
                  - type: string
                  - type: array
                    items:
                      anyOf:
                        - $ref: '#/components/schemas/AnthropicVideoBlock'
                        - type: object
                          additionalProperties: true
                  - type: 'null'
              output_config:
                $ref: '#/components/schemas/InlineReasoningEffort'
                description: >-
                  Astra/Fable 5.1 inline effort update. Requires system role and
                  empty content; trailing updates apply to the generated
                  response.
            additionalProperties: true
            allOf:
              - if:
                  required:
                    - output_config
                then:
                  properties:
                    role:
                      const: system
                    content:
                      enum:
                        - ''
                        - []
                        - null
                else:
                  required:
                    - content
                  properties:
                    role:
                      enum:
                        - user
                        - assistant
                    content:
                      not:
                        type: 'null'
      additionalProperties: true
    AnthropicMessage:
      type: object
      properties:
        id:
          type: string
        type:
          type: string
        role:
          type: string
        model:
          type: string
        content:
          type: array
          items:
            type: object
            additionalProperties: true
        stop_reason:
          type:
            - string
            - 'null'
        usage:
          type: object
          additionalProperties: true
      additionalProperties: true
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
    InlineReasoningEffort:
      type: object
      required:
        - effort
      properties:
        effort:
          type: string
          enum:
            - minimal
            - low
            - medium
            - high
            - xhigh
            - max
          description: >-
            Astra: low, medium, high, xhigh. Fable 5.1: low, medium, high,
            xhigh, max; minimal maps to low. Other models and none are
            unsupported for inline updates.
      additionalProperties: false
    AnthropicVideoBlock:
      type: object
      required:
        - type
        - source
      properties:
        type:
          const: video
        source:
          oneOf:
            - $ref: '#/components/schemas/AnthropicVideoSourceBase64'
            - $ref: '#/components/schemas/AnthropicVideoSourceUrl'
      additionalProperties: true
    AnthropicVideoSourceBase64:
      type: object
      required:
        - type
        - media_type
        - data
      properties:
        type:
          const: base64
        media_type:
          type: string
          pattern: ^video/
        data:
          type: string
          contentEncoding: base64
      additionalProperties: false
    AnthropicVideoSourceUrl:
      type: object
      required:
        - type
        - url
        - media_type
      properties:
        type:
          const: url
        url:
          type: string
          format: uri
          pattern: ^https://
        media_type:
          type: string
          pattern: ^video/
      additionalProperties: false
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