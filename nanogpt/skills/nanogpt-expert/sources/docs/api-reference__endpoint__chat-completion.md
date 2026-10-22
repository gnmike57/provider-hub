> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Chat Completion

> Creates a chat completion for the provided messages. The NanoGPT Advisor extension is available for non-streaming, platform-billed pay-as-you-go API-key requests that do not use client tools, structured output, inline moderation, BYOK, accountless payment, memory, or server-side content enhancements.

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

<Note>
  **API host:** Use `https://nano-gpt.com/api/v1` as the base URL for OpenAI-compatible clients. The direct API host allows larger attachments and longer-running requests than the website host. See [API Hosts](/api-reference/miscellaneous/api-hosts).
</Note>

<Note>
  Decision models (Jev, Decider, Liquid D1, PPLX Decider v1.1, Clef and Clef Flash) use `response_format: {"type":"questions","questions":{...}}`, accept only non-streaming user text, and return the answer object as JSON text in `choices[0].message.content`. `usage.estimated_cost` is returned by default; send `include_usage: true` for the exact `usage.cost`. See [Decisions](/api-reference/endpoint/decisions) for complete examples and limitations.
</Note>

<Note>
  The subscription base URL, `https://nano-gpt.com/api/subscription/v1/chat/completions` (swap `/api/v1` for `/api/subscription/v1`), is billed the same way as `/api/v1`: subscription-included models use your subscription, and requests it does not cover can be billed to your balance. To keep an API key limited to your subscription, save the key as **Subscription only** in its [billing mode](/api-reference/miscellaneous/billing-override#api-key-billing-settings); requests the subscription does not cover are then rejected instead of billed.
</Note>

<Note>
  Provider selection is available for supported open-source models. `X-Provider` or body `provider` explicitly selects or constrains providers for the request and is always billed pay-as-you-go at the selected provider's price, including provider-selection markup. The body `provider` field accepts either the existing string form or a structured routing object with `order`, `only`, `ignore`, `sort`, `quantizations`, `min_quantization`, `max_price`, `allow_fallbacks`, and `require_parameters`. Provider-selection-capable models also support routing preference suffixes such as `:fast` and `:cheap`. For subscription users, explicit provider selection bypasses subscription coverage for that request; `X-Billing-Mode: paygo` is only needed when forcing pay-as-you-go without an explicit provider or when saved provider preferences should apply to subscription-included traffic. See [Provider Selection](/api-reference/miscellaneous/provider-selection), [Model Suffixes](/api-reference/miscellaneous/model-suffixes), and [Pay-As-You-Go Billing Override](/api-reference/miscellaneous/billing-override).
</Note>

<Note>
  **Accountless x402 payments**: Non-streaming `POST /api/v1/chat/completions` requests can be quoted without an account or API key on supported deployments when the initial quote request includes `x-x402: true`. Streaming chat has implementation coverage but is not part of the stable public accountless contract. This endpoint supports accountless x402 payments where listed by `GET /api/v1/x402/endpoints`, including Lightning L402 when advertised. See [Accountless x402 API Payments](/api-reference/miscellaneous/x402) for the full flow.
</Note>

<Note>
  **Advisor extension:** Non-streaming pay-as-you-go API-key requests can include an `advisor` object so the executor model can consult one different model before returning its final answer. Use `mode: "auto"` to let the executor decide or `mode: "required"` to require a consultation attempt. Each completed model phase is billed separately. Advisor is a NanoGPT extension, not part of the standard OpenAI request schema. See [Advisor](/api-reference/miscellaneous/advisor).
</Note>

<Note>
  **Billing after a disconnect:** Save the server-generated `X-Request-ID` response header before consuming a stream. With the same API key, [Request Billing](/api-reference/endpoint/request-billing) can return the recorded primary charge and token usage for 24 hours from its accounting timestamp. Refunds and separately billed extras are excluded. Billing may be delayed; a missing record does not mean zero cost.
</Note>

## Page map

Use the jump list below to navigate the long-form reference quickly.

<AccordionGroup>
  <Accordion title="Basics">
    * [Advisor extension](#advisor-extension)
    * [Tool calling](#tool-calling)
    * [Overview](#overview)
    * [Provider Routing Suffixes](#provider-routing-suffixes)
    * [Provider Routing Object](#provider-routing-object)
  </Accordion>

  <Accordion title="Sampling & decoding">
    * [Sampling & Decoding Controls](#sampling-decoding-controls)
    * [Temperature & Nucleus](#temperature-nucleus)
    * [Length & Stopping](#length-stopping)
    * [Penalties & Repetition Guards](#penalties-repetition-guards)
    * [Logit Shaping & Reproducibility](#logit-shaping-reproducibility)
    * [Sampling example request](#example-request-1)
  </Accordion>

  <Accordion title="Structured outputs">
    * [Structured Outputs (response\_format)](#structured-outputs-response-format)
    * [Supported Formats](#supported-formats)
    * [JSON Object Mode](#json-object-mode)
    * [JSON Schema Mode](#json-schema-mode-structured-outputs)
    * [Schema Requirements](#schema-requirements)
    * [Example Request](#example-request-2)
    * [Example Response](#example-response)
    * [Vercel AI SDK](#usage-with-vercel-ai-sdk)
  </Accordion>

  <Accordion title="Web search">
    * [Web Search](#web-search)
    * [Native search](#native-search)
    * [Limit native search](#limit-native-search)
    * [Option A: model suffixes](#option-a-model-suffixes)
    * [Option B: request body configuration](#option-b-request-body-configuration-recommended)
    * [Option C: OpenAI web\_search\_options](#option-c-openai-web_search_options)
    * [Provider-specific options](#provider-specific-options-set-inside-the-web-search-object)
    * [Examples](#examples)
    * [Pricing by provider](#pricing-by-provider)
    * [Bring your own key (BYOK)](#bring-your-own-key-byok)
  </Accordion>

  <Accordion title="Images & caching">
    * [Image Input](#image-input)
    * [Video Input](#video-input)
    * [Supported Forms](#supported-forms)
    * [Message Shape](#message-shape)
    * [cURL - Image URL](#curl-image-url-non-streaming)
    * [cURL - Base64 Data URL](#curl-base64-data-url-non-streaming)
    * [cURL - Streaming SSE](#curl-streaming-sse)
    * [Caching (Implicit and Explicit Controls)](#caching-implicit-and-explicit-controls)
    * [Cache-Capable Provider Routing](#cache-capable-provider-routing)
    * [Cache Consistency](#explicit-prompt-cache-consistency)
    * [Troubleshooting](#troubleshooting)
  </Accordion>

  <Accordion title="Memory & reasoning">
    * [Context Memory](#context-memory)
    * [Custom Context Size Override](#custom-context-size-override)
    * [Reasoning Streams](#reasoning-streams)
    * [Endpoint variants](#endpoint-variants)
    * [Streaming payload format](#streaming-payload-format)
    * [Showing or hiding reasoning](#showing-or-hiding-reasoning)
    * [Reasoning Effort](#reasoning-effort)
    * [Model suffix: reasoning effort](#model-suffix-reasoning-effort)
    * [Model suffix: :reasoning-exclude](#model-suffix-reasoning-exclude)
    * [Legacy delta field compatibility](#legacy-delta-field-compatibility)
  </Accordion>

  <Accordion title="Other">
    * [Service tiers (Flex and Fast/Priority)](#service-tiers-priority)
    * [Compressed Request Bodies](#compressed-request-bodies)
    * [YouTube Transcripts](#youtube-transcripts)
    * [Performance Benchmarks](#performance-benchmarks)
    * [Important Notes](#important-notes)
  </Accordion>
</AccordionGroup>

## Advisor extension

* `advisor` (optional object): Configures one different, client-selected model that the executor may consult. The initial version is limited to non-streaming, pay-as-you-go API-key requests and cannot be combined with client tools or structured output. See [Advisor](/api-reference/miscellaneous/advisor) for the full request contract, billing, privacy, response metadata, and limitations.

## Tool calling

The `/api/v1/chat/completions` endpoint supports OpenAI-compatible function calling. You can describe callable functions in the `tools` array, control when the model may invoke them, and continue the conversation by echoing `tool` role messages that reference the assistant's chosen call.

### Request parameters

* `tools` (optional array): Each entry must be `{ "type": "function", "function": { "name": string, "description"?: string, "parameters"?: JSON-Schema object } }`. Only `function` tools are accepted. The serialized `tools` payload is limited to 200 KB (overrides via `TOOL_SPEC_MAX_BYTES`); violating the shape or size yields a 400 with `tool_spec_too_large`, `invalid_tool_spec`, or `invalid_tool_spec_parse`.
* `tool_choice` (optional string or object): Defaults to `auto`. Set `"none"` to guarantee no tool calls (the server also drops the `tools` payload upstream), `"required"` to force the next response to be a tool call, or `{ "type": "function", "function": { "name": "your_function" } }` to pin the exact function.
* `parallel_tool_calls` (optional boolean): When `true` the flag is forwarded to providers that support issuing multiple tool calls in a single turn. Models that ignore the flag fall back to sequential calls.
* `max_tool_calls` (optional integer): Caps the built-in tool calls, such as [native web search](#limit-native-search), that the model makes in one response. It applies to requests NanoGPT sends to OpenAI's Responses API, which includes GPT-5+ and o-series native search; other routes ignore it.
* `messages[].tool_calls` (assistant role): Persist the tool call metadata returned by the model so future turns can see which functions were invoked. Each item uses the OpenAI shape `{ id, type: "function", function: { name, arguments } }`.
* `messages[]` with `role: "tool"`: Respond to the model by sending `{ "role": "tool", "tool_call_id": "<assistant tool_calls id>", "content": "<JSON or text payload>" }`. The server drops any tool response that references an unknown `tool_call_id`, so keep the IDs in sync.
* Validation behavior: If you send `tool_choice: "none"` with a `tools` array the request is accepted but the tools are omitted before hitting the model; invalid schemas or oversize payloads return the error codes above.

### Example request

```http theme={null}
POST /api/v1/chat/completions
{
  "model": "google/gemini-3-flash-preview",
  "messages": [
    { "role": "user", "content": "What's the temperature in San Francisco right now?" }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "lookup_weather",
        "description": "Fetch the current weather for a city.",
        "parameters": {
          "type": "object",
          "properties": {
            "city": { "type": "string" },
            "unit": { "type": "string", "enum": ["c", "f"] }
          },
          "required": ["city"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "parallel_tool_calls": true
}
```

### Example assistant/tool turn

```json theme={null}
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "lookup_weather",
        "arguments": "{\"city\":\"San Francisco\",\"unit\":\"f\"}"
      }
    }
  ]
}
```

```json theme={null}
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"city\":\"San Francisco\",\"temperatureF\":58,\"conditions\":\"foggy\"}"
}
```

Streaming responses emit delta events that mirror OpenAI's `tool_calls` schema, so consumers can reuse their existing parsing logic without changes.

## Overview

The Chat Completion endpoint provides OpenAI-compatible chat completions.

## Provider Routing Suffixes

Provider-selection-capable models support routing preference suffixes such as `:fast` and `:cheap`. See [Provider Selection > Per-Request Routing Preference](/api-reference/miscellaneous/provider-selection#per-request-routing-preference) for the full list and billing rules, or [Model Suffixes](/api-reference/miscellaneous/model-suffixes) for all suffix composition rules.

## Provider Routing Object

The `provider` request body field accepts either a provider ID string or a structured object for routing controls:

```json theme={null}
{
  "model": "model-id",
  "provider": {
    "order": ["provider-a", "provider-b"],
    "only": ["provider-b"],
    "ignore": ["provider-c"],
    "sort": "price",
    "quantizations": ["fp8", "fp16"],
    "min_quantization": "fp8",
    "max_price": {
      "prompt": 0.5,
      "completion": 2
    },
    "allow_fallbacks": false,
    "require_parameters": true
  },
  "messages": [
    { "role": "user", "content": "Hello" }
  ]
}
```

Use [Provider Selection > Provider Routing Object](/api-reference/miscellaneous/provider-selection#provider-routing-object) for field semantics, validation behavior, and provider discovery.

## Sampling & Decoding Controls

The `/api/v1/chat/completions` endpoint accepts a full set of sampling and decoding knobs. All fields are optional; omit any you want to leave at provider defaults.

### Temperature & Nucleus

| Parameter | Range/Default | Description |
| - | - | - |
| `temperature` | 0–2 (provider default) | Classic randomness control; higher values explore more. If omitted, NanoGPT does not force a value and the routed provider/model default applies. |
| `top_p` | 0–1 (default 1) | Nucleus sampling that trims to the smallest set above `top_p` cumulative probability. |
| `top_k` | 1+ | Sample only from the top-k tokens each step. |
| `top_a` | provider default | Blends temperature and nucleus behavior; set only if a model calls for it. |
| `min_p` | 0–1 | Require each candidate token to exceed a probability floor. |
| `tfs` | 0–1 | Tail free sampling; 1 disables. |
| `eta_cutoff` / `epsilon_cutoff` | provider default | Drop tokens once they fall below the tail thresholds. |
| `typical_p` | 0–1 | Entropy-based nucleus sampling; keeps tokens whose surprise matches expected entropy. |
| `mirostat_mode` | 0/1/2 | Enable Mirostat sampling; set tau/eta when active. |
| `mirostat_tau` / `mirostat_eta` | provider default | Target entropy and learning rate for Mirostat. |

### Length & Stopping

| Parameter | Range/Default | Description |
| - | - | - |
| `max_tokens` | 1+ (provider default) | Upper bound on generated tokens. If omitted, NanoGPT does not enforce an explicit default and the routed provider/model default applies. |
| `min_tokens` | 0+ (default 0) | Minimum completion length when provider supports it. |
| `stop` | string or string\[] | Stop sequences passed upstream. |
| `stop_token_ids` | int\[] | Stop generation on specific token IDs (limited provider support). |
| `include_stop_str_in_output` | boolean (default false) | Keep the stop sequence in the final text where supported. |
| `ignore_eos` | boolean (default false) | Continue even if the model predicts EOS internally. |

### Penalties & Repetition Guards

| Parameter | Range/Default | Description |
| - | - | - |
| `frequency_penalty` | -2 – 2 (default 0) | Penalize tokens proportional to prior frequency. |
| `presence_penalty` | -2 – 2 (default 0) | Penalize tokens based on whether they appeared at all. |
| `repetition_penalty` | -2 – 2 | Provider-agnostic repetition modifier; >1 discourages repeats. |
| `no_repeat_ngram_size` | 0+ | Forbid repeating n-grams of the given size (limited support). |
| `custom_token_bans` | int\[] | Fully block listed token IDs. |

### Logit Shaping & Reproducibility

| Parameter | Range/Default | Description |
| - | - | - |
| `logit_bias` | object | Map token IDs to additive logits (OpenAI-compatible). |
| `logprobs` | boolean or int | Return token-level logprobs where supported. |
| `prompt_logprobs` | boolean | Request logprobs on the prompt when available. |
| `seed` | integer | Optional integer forwarded on model/provider routes that support seeded sampling. This may improve reproducibility but does not guarantee identical output. Results can change if NanoGPT selects a different automatic or fallback route, or if the provider changes its backend. |

#### Reproducibility guidance

Seeded generation is best-effort. To reduce avoidable variation:

* Keep the exact model, messages, tools, and sampling settings unchanged.
* Select a specific provider where possible.
* Disable automatic fallbacks where supported when route consistency matters.
* Use a low or zero `temperature` where supported.
* Do not treat seeded output as byte-identical. Record provider, route, and system-fingerprint metadata when NanoGPT exposes reliable values.

NanoGPT will publish a seed-support matrix when reliable route-level capability data is available. Until then, do not infer seed support from endpoint compatibility alone.

### Usage notes

* Parameters can be combined (e.g., `temperature` + `top_p` + `top_k`), but overly narrow settings may lead to early stops.
* Invalid ranges yield a 400 before reaching the provider.
* Provider defaults apply to any omitted field.

### Example request

```bash theme={null}
curl -X POST https://nano-gpt.com/api/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemini-3-flash-preview",
    "messages": [
      {"role": "user", "content": "Write a creative story about space exploration"}
    ],
    "temperature": 0.8,
    "top_p": 0.9,
    "top_k": 40,
    "tfs": 0.8,
    "typical_p": 0.95,
    "mirostat_mode": 2,
    "mirostat_tau": 5,
    "mirostat_eta": 0.1,
    "max_tokens": 500,
    "frequency_penalty": 0.3,
    "presence_penalty": 0.1,
    "repetition_penalty": 1.1,
    "stop": ["###"],
    "seed": 42
  }'
```

## Structured Outputs (response\_format)

The `/api/v1/chat/completions` endpoint supports OpenAI-compatible structured outputs via the `response_format` parameter. This ensures the model returns valid JSON matching your specified schema.

### Supported Formats

| Type | Description |
| - | - |
| `json_object` | Forces the model to return valid JSON |
| `json_schema` | Forces the model to return JSON matching a specific schema |
| `text` | Default text output (no constraint) |
| `questions` | Decision models only: typed Choice, Score and yes/no answers. See [Decisions](/api-reference/endpoint/decisions). |

### JSON Object Mode

Request valid JSON output without a specific schema:

```json theme={null}
{
  "model": "openai/gpt-5.1",
  "messages": [{"role": "user", "content": "List 3 colors as JSON"}],
  "response_format": {"type": "json_object"}
}
```

### JSON Schema Mode (Structured Outputs)

Request JSON that conforms to a specific schema:

```json theme={null}
{
  "model": "openai/gpt-5.1",
  "messages": [{"role": "user", "content": "What is 2+2?"}],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "math_answer",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "answer": {"type": "number"},
          "explanation": {"type": "string"}
        },
        "required": ["answer", "explanation"],
        "additionalProperties": false
      }
    }
  }
}
```

### Schema Requirements

When using `strict: true`:

* All properties must be listed in `required`
* Set `additionalProperties: false`
* NanoGPT automatically transforms optional properties to be nullable for OpenAI compatibility

### Supported Models

JSON schema mode works with most models including:

* OpenAI models (GPT-5.1, GPT-5.2, etc.)
* Anthropic Claude models
* Google Gemini models
* Many open-source models

### Example Request

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST https://nano-gpt.com/api/v1/chat/completions \
    -H "Authorization: Bearer YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "openai/gpt-5.1",
      "messages": [
        {"role": "user", "content": "Generate a person profile"}
      ],
      "response_format": {
        "type": "json_schema",
        "json_schema": {
          "name": "person",
          "strict": true,
          "schema": {
            "type": "object",
            "properties": {
              "name": {"type": "string"},
              "age": {"type": "number"},
              "skills": {
                "type": "array",
                "items": {"type": "string"}
              }
            },
            "required": ["name", "age", "skills"],
            "additionalProperties": false
          }
        }
      },
      "stream": false
    }'
  ```

  ```python Python theme={null}
  import requests

  response = requests.post(
      "https://nano-gpt.com/api/v1/chat/completions",
      headers={
          "Authorization": "Bearer YOUR_API_KEY",
          "Content-Type": "application/json"
      },
      json={
          "model": "openai/gpt-5.1",
          "messages": [
              {"role": "user", "content": "Generate a person profile"}
          ],
          "response_format": {
              "type": "json_schema",
              "json_schema": {
                  "name": "person",
                  "strict": True,
                  "schema": {
                      "type": "object",
                      "properties": {
                          "name": {"type": "string"},
                          "age": {"type": "number"},
                          "skills": {
                              "type": "array",
                              "items": {"type": "string"}
                          }
                      },
                      "required": ["name", "age", "skills"],
                      "additionalProperties": False
                  }
              }
          }
      }
  )

  data = response.json()
  print(data["choices"][0]["message"]["content"])
  # Output: {"name": "Alice Chen", "age": 28, "skills": ["Python", "Machine Learning", "Data Analysis"]}
  ```

  ```javascript JavaScript theme={null}
  const response = await fetch("https://nano-gpt.com/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "Authorization": "Bearer YOUR_API_KEY",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "openai/gpt-5.1",
      messages: [
        { role: "user", content: "Generate a person profile" }
      ],
      response_format: {
        type: "json_schema",
        json_schema: {
          name: "person",
          strict: true,
          schema: {
            type: "object",
            properties: {
              name: { type: "string" },
              age: { type: "number" },
              skills: {
                type: "array",
                items: { type: "string" }
              }
            },
            required: ["name", "age", "skills"],
            additionalProperties: false
          }
        }
      }
    })
  });

  const data = await response.json();
  console.log(data.choices[0].message.content);
  // Output: {"name": "Alice Chen", "age": 28, "skills": ["Python", "Machine Learning", "Data Analysis"]}
  ```
</CodeGroup>

### Example Response

```json theme={null}
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1769278225,
  "model": "openai/gpt-5.1",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "{\"name\":\"Alice Chen\",\"age\":28,\"skills\":[\"Python\",\"Machine Learning\",\"Data Analysis\"]}"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### Usage with Vercel AI SDK

The `response_format` parameter is compatible with Vercel AI SDK's `generateObject`:

```typescript theme={null}
import { generateObject } from 'ai';
import { createOpenAI } from '@ai-sdk/openai';
import { z } from 'zod';


const nanogpt = createOpenAI({
  baseURL: 'https://nano-gpt.com/api/v1',
  apiKey: 'YOUR_API_KEY',
});

const { object } = await generateObject({
  model: nanogpt('openai/gpt-5.1'),
  schema: z.object({
    name: z.string(),
    age: z.number(),
    skills: z.array(z.string()),
  }),
  prompt: 'Generate a person profile',
});

console.log(object);
// { name: "Alice Chen", age: 28, skills: ["Python", "Machine Learning", "Data Analysis"] }
```

### Usage Notes

* Works with both streaming and non-streaming requests
* The `name` field in `json_schema` is required and should describe the output
* Response content is a JSON string; parse it with `JSON.parse()` in your application
* Some provider-specific limitations may apply; if you encounter issues with a specific model, try an alternative

## Web Search

Enable web search in three ways: a model suffix, a `web_search` field in the request body, or OpenAI's `web_search_options`.

* `web_search` accepts an object or a boolean. `true` turns search on with the default provider.
* `webSearch` and the legacy `linkup` object are accepted as aliases. If a request sends more than one, `web_search` wins, then `webSearch`, then `linkup`.
* If the body object has `enabled: true`, its settings override the suffix's settings field by field; settings it leaves out keep the suffix's values.
* On GPT-5+ and o-series models, an enabled body without `provider` selects native search even when the suffix names another provider. Set `provider` to keep a different one.
* `web_search: false` (or `enabled: false`) does not switch off search requested by an `:online` suffix. Remove the suffix to turn search off.

### Native search

Native search uses the model's own built-in web search instead of a separate search provider. It is available on GPT-5 and later and o-series (o1, o3, o4) models, Claude 4 and later, Gemini 3 and later, and Grok 4.20 and later. Image, multi-agent, and `:free` variants are not supported.

* GPT-5+ and o-series models use native search by default whenever web search is on. To use another provider, set `provider` or use a suffix such as `:online/linkup`.
* Other models, including older GPT models, use Linkup by default. Request native search with `"provider": "native"` or the `:online/native` suffix.
* If you request native search on a model without it, the request searches with the suffix's provider or Linkup instead.
* Native requests on Claude, Gemini, or Grok can fail with `400` and code `native_web_search_unavailable` when your provider restrictions leave no route that can run native search. On GPT models, such restrictions can instead leave the request answering without a search.
* With your own provider keys (BYOK), native search runs on OpenAI keys (GPT and o-series models) and Anthropic keys (Claude). The searches are billed to your provider account, not by NanoGPT. Other BYOK routes use Linkup instead. On Anthropic, an organization admin can turn web search off; requests then fail with Anthropic's `400` error.
* The model decides how many searches to run. GPT-5+ and o-series models have no default limit; set `max_tool_calls` to cap them (see [Limit native search](#limit-native-search)). On Claude, NanoGPT normally caps this at 2 (`low`), 3 (`medium`, the default), or 5 (`high`) searches per request, and skips native search when `tool_choice` is `none` or when you define your own function named `web_search`.
* Each search the model runs is billed once at the native rate (see [Pricing by provider](#pricing-by-provider)), even when it covers several queries. On GPT-5+ and o-series models, NanoGPT does not bill opening a page, searching within a page, or calls stopped by `max_tool_calls`, and waives the search fee when the answer shows no source links. With your own OpenAI key (BYOK), OpenAI bills the searches to your account instead. Where a route reports no count, NanoGPT may bill an estimate: 1 search for `low`, 2 otherwise.
* The search results are added to the model's input and billed at the model's input token rate, on top of the search fees. On larger models this is often most of the cost: a GPT-5.5 answer that searches several times can read tens of thousands of input tokens.

#### Limit native search

On GPT-5+ and o-series models, the top-level `max_tool_calls` field caps how many built-in tool calls the model can make while answering. Searches, page opens, and searches within a page all count toward the cap. Once it is reached, the model answers with what it has found; further calls are not run and not billed.

The cap applies when NanoGPT sends the request straight to OpenAI, which is the usual route for these models, including with your own OpenAI key (BYOK). Requests that NanoGPT reroutes, such as Auto Model or a fallback attempt, may not apply it.

```json theme={null}
{
  "model": "openai/gpt-5.5:online",
  "max_tool_calls": 3,
  "messages": [
    { "role": "user", "content": "Which commercial cleaning companies in Leeds would you recommend?" }
  ]
}
```

`max_tool_calls` has no effect on Claude, Gemini, or Grok native search; on Claude, `search_context_size` sets the cap. For a fixed search fee per request, use another provider, such as `:online/linkup`; model token charges still apply.

If you need full direct control over the search call itself (`query`, `outputType`, date/domain filters, or structured schema output), use [Direct Web Search API (`POST /api/web`)](/api-reference/endpoint/web-search).

| Use case | Recommended endpoint |
| - | - |
| Model should answer with web context in one call | `POST /api/v1/chat/completions` |
| You need raw/structured web payload control | `POST /api/web` |

### Option A: model suffixes

Append one of these to your `model` value:

* `:online` (default web search, standard depth; native search on GPT-5+ and o-series models)
* `:online/native` (the model's own search; see [Native search](#native-search))
* `:online/linkup` (Linkup, standard)
* `:online/linkup-deep` (Linkup, deep)
* `:online/tavily` (Tavily, standard)
* `:online/tavily-deep` (Tavily, deep)
* `:online/brave` (Brave, standard)
* `:online/brave-deep` (Brave, deep)
* `:online/sofya` (Sofya, standard)
* `:online/exa-fast` (Exa, fast)
* `:online/exa-auto` (Exa, auto)
* `:online/exa-neural` (Exa, neural)
* `:online/exa-deep` (Exa, deep)
* `:online/exa-instant` (Exa, instant)
* `:online/exa-deep-reasoning` (Exa, deep-reasoning)
* `:online/kagi` (Kagi, standard, search)
* `:online/kagi-web` (Kagi, standard, web)
* `:online/kagi-news` (Kagi, standard, news)
* `:online/kagi-search` (Kagi, deep, search)
* `:online/perplexity` (Perplexity, standard)
* `:online/perplexity-deep` (Perplexity, deep)
* `:online/valyu` (Valyu, standard, all sources)
* `:online/valyu-deep` (Valyu, deep, all sources)
* `:online/valyu-web` (Valyu, standard, web only)
* `:online/valyu-web-deep` (Valyu, deep, web only)
* `:online/firecrawl` (Firecrawl, standard)
* `:online/firecrawl-deep` (Firecrawl, deep)

`:online` without an explicit provider uses the default: native search on GPT-5+ and o-series models, Linkup on other models.

### Option B: request body configuration (recommended)

Send a `web_search` object in the request body. `webSearch` and the legacy `linkup` object are accepted as aliases. This works with or without a model suffix and controls web search across all providers. `"web_search": true` is shorthand for `{ "enabled": true }`.

`web_search` fields:

* `enabled` (boolean, required to activate web search)
* `provider` (string): `native` | `linkup` | `tavily` | `brave` | `sofya` | `exa` | `kagi` | `perplexity` | `valyu` | `firecrawl`
* `depth` (string):
  * Linkup/Tavily/Brave/Perplexity/Valyu/Firecrawl: `standard` or `deep`
  * Sofya: `standard`
  * Exa: `fast`, `auto`, `neural`, `deep`, `instant`, `deep-reasoning` (use `standard` if you want `auto`)
  * Kagi: `standard` or `deep` (`search` source only)
* `search_context_size` or `searchContextSize` (string, native search): `low` | `medium` | `high` (default: `medium`; OpenAI deep-research models always use `medium`)
* `user_location` or `userLocation` (object, native search on GPT-5+ and o-series models): `{ type: "approximate", country, city, region, timezone }`. It may be ignored when a fallback route serves the request.
* `searchType` (string, Valyu only): `all` | `web`
* `kagiSource` or `kagi_source` (string, Kagi only): `web` | `news` | `search`

Shorthand and legacy alias examples:

```json theme={null}
{ "web_search": true }
```

```json theme={null}
{
  "linkup": {
    "enabled": true,
    "provider": "tavily"
  }
}
```

### Option C: OpenAI `web_search_options`

Requests written for OpenAI's Chat Completions API can send `web_search_options`. It turns on web search with the default provider: native search on GPT-5+ and o-series models, Linkup on other models.

```json theme={null}
{
  "model": "openai/gpt-6.1-sol",
  "messages": [{ "role": "user", "content": "What changed in the news today?" }],
  "web_search_options": {
    "search_context_size": "low",
    "user_location": {
      "type": "approximate",
      "approximate": { "country": "US", "city": "Austin", "region": "Texas" }
    }
  }
}
```

* `search_context_size` (`low` | `medium` | `high`) is passed to native search. It never selects deep search.
* `user_location` is passed to native search on GPT-5+ and o-series models.
* If the request also sends `web_search`, `webSearch`, or `linkup`, those settings are used and `web_search_options` is ignored.
* With an `:online/<provider>` suffix, the suffix's provider is kept.
* Models that already search on their own, such as search-preview and deep-research models, ignore `web_search_options`. The NanoGPT help model rejects a non-empty `web_search_options` object.

#### Provider-specific options (set inside the web search object)

##### Perplexity

```json theme={null}
{
  "maxResults": 1-20,
  "maxTokensPerPage": number,
  "maxTokens": 1-1000000,
  "country": "string",
  "searchDomainFilter": ["domain1.com", "domain2.com"],
  "searchLanguageFilter": ["en", "de"]
}
```

Limits: `searchDomainFilter` max 20 entries; `searchLanguageFilter` max 10 entries (ISO 639-1).

##### Valyu

```json theme={null}
{
  "searchType": "all" | "web",
  "fastMode": boolean,
  "maxNumResults": 1-50,
  "maxPrice": number,
  "relevanceThreshold": 0-1,
  "responseLength": "short" | "medium" | "large" | "max" | number,
  "countryCode": "US",
  "includedSources": ["source1.com"],
  "excludedSources": ["source2.com"],
  "urlOnly": boolean,
  "category": "string"
}
```

`countryCode` uses a 2-letter ISO country code.

##### Tavily

```json theme={null}
{
  "maxResults": 0-20,
  "includeAnswer": boolean | "basic" | "advanced",
  "includeRawContent": boolean | "markdown" | "text",
  "includeImages": boolean,
  "includeImageDescriptions": boolean,
  "includeFavicon": boolean,
  "topic": "general" | "news" | "finance",
  "timeRange": "day" | "week" | "month" | "year",
  "startDate": "YYYY-MM-DD",
  "endDate": "YYYY-MM-DD",
  "chunksPerSource": 1-3,
  "country": "string"
}
```

##### Exa

```json theme={null}
{
  "numResults": 1-100,
  "category": "company" | "research paper" | "news" | "pdf" | "github" | "tweet" | "personal site" | "people" | "financial report",
  "userLocation": "US",
  "additionalQueries": ["query2"],
  "startCrawlDate": "ISO 8601",
  "endCrawlDate": "ISO 8601",
  "startPublishedDate": "ISO 8601",
  "endPublishedDate": "ISO 8601",
  "includeText": ["pattern"],
  "excludeText": ["pattern"],
  "livecrawl": "never" | "fallback" | "always" | "preferred",
  "livecrawlTimeout": number,
  "subpages": number,
  "subpageTarget": "string" | ["strings"]
}
```

##### Sofya

Sofya search returns extracted page content rather than snippets alone. Chat completions use its Search operation. For explicit query options and Sofya's Fetch, Extract, and Research operations, use the [Direct Web Search API](/api-reference/endpoint/web-search#sofya-operations).

##### Native search

```json theme={null}
{
  "provider": "native",
  "search_context_size": "low" | "medium" | "high",
  "user_location": {
    "type": "approximate",
    "country": "US",
    "city": "San Francisco",
    "region": "California",
    "timezone": "America/Los_Angeles"
  }
}
```

`user_location` applies to GPT-5+ and o-series models only.

### Examples

<CodeGroup>
  ```python Python theme={null}
  import requests
  import json

  BASE_URL = "https://nano-gpt.com/api/v1"
  API_KEY = "YOUR_API_KEY"

  headers = {
      "Authorization": f"Bearer {API_KEY}",
      "Content-Type": "application/json"
  }

  # Suffix-based standard web search
  data = {
      "model": "openai/gpt-6.1-sol:online",
      "messages": [
          {"role": "user", "content": "What are the latest developments in AI?"}
      ]
  }

  response = requests.post(
      f"{BASE_URL}/chat/completions",
      headers=headers,
      json=data
  )

  # Request-body configuration (Exa neural)
  data_search = {
      "model": "openai/gpt-6.1-sol",
      "messages": [
          {"role": "user", "content": "Provide a comprehensive analysis of recent AI breakthroughs"}
      ],
      "web_search": {
          "enabled": True,
          "provider": "exa",
          "depth": "neural",
          "numResults": 10
      }
  }
  ```

  ```javascript JavaScript theme={null}
  const BASE_URL = "https://nano-gpt.com/api/v1";
  const API_KEY = "YOUR_API_KEY";

  // Suffix-based standard web search
  const response = await fetch(`${BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json'
      },
      body: JSON.stringify({
          model: 'openai/gpt-6.1-sol:online',
          messages: [
              { role: 'user', content: 'What are the latest developments in AI?' }
          ]
      })
  });

  // Request-body configuration (Exa neural)
  const searchResponse = await fetch(`${BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json'
      },
      body: JSON.stringify({
          model: 'openai/gpt-6.1-sol',
          messages: [
              { role: 'user', content: 'Provide a comprehensive analysis of recent AI breakthroughs' }
          ],
          web_search: {
              enabled: true,
              provider: 'exa',
              depth: 'neural',
              numResults: 10
          }
      })
  });
  ```

  ```bash cURL theme={null}
  # Suffix-based standard web search
  curl -X POST https://nano-gpt.com/api/v1/chat/completions \
    -H "Authorization: Bearer YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "openai/gpt-6.1-sol:online",
      "messages": [
        {"role": "user", "content": "What are the latest developments in AI?"}
      ]
    }'

  # Request-body configuration (Exa neural)
  curl -X POST https://nano-gpt.com/api/v1/chat/completions \
    -H "Authorization: Bearer YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "openai/gpt-6.1-sol",
      "messages": [
        {"role": "user", "content": "Provide a comprehensive analysis of recent AI breakthroughs"}
      ],
      "web_search": {
        "enabled": true,
        "provider": "exa",
        "depth": "neural",
        "numResults": 10
      }
    }'
  ```
</CodeGroup>

### Pricing by provider

| Provider | Standard | Deep | Notes |
| - | - | - | - |
| Linkup | \$0.006 | \$0.06 | Default provider |
| Tavily | \$0.008 | \$0.016 | Good value, free tier available |
| Exa | \$0.005 base | + \$0.001/page | For contents retrieval |
| Kagi Web/News | \$0.002 | N/A | Cheapest for enrichment |
| Kagi Search | \$0.025 | N/A | Full search mode |
| Perplexity | \$0.005 | N/A | Flat rate |
| Valyu | \~\$0.0015/result | Variable | Dynamic pricing |
| Brave | \$0.005 | \$0.005 | Flat rate |
| Sofya | \$0.01575 | N/A | Extracted page content; standard depth only |
| Firecrawl | \~\$0.0105 | \~\$0.018 | \$0.0015 per Firecrawl credit used; standard is about 7 credits, deep about 12 |
| Native | Per search + tokens | N/A | GPT and Claude $0.01, Gemini $0.014, Grok \$0.005 per search, plus model token costs. Cap GPT searches with `max_tool_calls` |

For standard NanoGPT usage, provider credentials are handled automatically.

### Bring your own key (BYOK)

BYOK lets you route requests through your own upstream provider credentials.

* Configure keys once: [https://nano-gpt.com/byok](https://nano-gpt.com/byok)
* Opt in per request via `x-use-byok: true` or `byok.enabled: true`
* Optionally force the provider via `x-byok-provider` or `byok.provider`
* BYOK usage includes a **5% platform fee** (your provider bills you directly for usage)

See: [Bring Your Own Key (BYOK)](/api-reference/miscellaneous/byok)

#### Web search BYOK

Web search BYOK availability is provider-dependent and can change over time. See the BYOK reference for the current support matrix.

### Advanced behavior (optional)

* **Provider routing**: For GPT-5+ and o-series models, web search without an explicit provider uses native search. If you set `web_search.provider` or use an explicit `:online/<provider>` suffix, that provider is used instead, unless an enabled body without `provider` is also sent (see [Web Search](#web-search)).
* **Model suffix normalization**: `:online` (and provider/depth suffixes) are stripped from the model name before routing to the base model; the suffix only controls search behavior.
* **Query formation (providers other than native)**: The search query is derived from your latest user message and may include the previous user message if the latest is short. If you need full control over the query or raw results, use the Web Search endpoint (`/api/web`).
* **`scraping: true` URL handling**: When enabled, NanoGPT scans messages for public `http(s)` URLs, ignores local/private URLs, de-duplicates, and caps at 5. If no eligible URLs are found, scraping is skipped. Inline scraping in chat is billed at **\$0.0015 per successfully scraped URL**. For explicit URL lists and the standalone endpoint price (**\$0.001 per URL**), use `/scrape-urls`.

## Image Input

Send images using the OpenAI‑compatible chat format. Provide image parts alongside text in the `messages` array.

### Supported Forms

* Remote URL: `{"type":"image_url","image_url":{"url":"https://..."}}`
* Base64 data URL: `{"type":"image_url","image_url":{"url":"data:image/png;base64,...."}}`

Notes:

* Prefer HTTPS URLs; some upstreams reject non‑HTTPS. If in doubt, use base64 data URLs.
* Accepted mime types: `image/png`, `image/jpeg`, `image/jpg`, `image/webp`.
* Inline markdown images in plain text (e.g., `![alt](data:image/...;base64,...)`) are auto‑normalized into structured parts server‑side.

### Message Shape

```json theme={null}
{
  "role": "user",
  "content": [
    { "type": "text", "text": "What is in this image?" },
    { "type": "image_url", "image_url": { "url": "https://example.com/image.jpg" } }
  ]
}
```

### cURL — Image URL (non‑streaming)

```bash theme={null}
curl -sS \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST https://nano-gpt.com/api/v1/chat/completions \
  --data '{
    "model": "google/gemini-3-flash-preview",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "Describe this image in three words."},
          {"type": "image_url", "image_url": {"url": "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg"}}
        ]
      }
    ],
    "stream": false
  }'
```

### cURL — Base64 Data URL (non‑streaming)

Embed your image as a data URL. Replace `...BASE64...` with your image bytes.

```bash theme={null}
curl -sS \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type": "application/json" \
  -X POST https://nano-gpt.com/api/v1/chat/completions \
  --data '{
    "model": "google/gemini-3-flash-preview",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "What is shown here?"},
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,...BASE64..."}}
        ]
      }
    ],
    "stream": false
  }'
```

### cURL — Streaming SSE

See also: [Streaming Protocol (SSE)](/api-reference/miscellaneous/streaming-protocol).

```bash theme={null}
curl -N \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -X POST https://nano-gpt.com/api/v1/chat/completions \
  --data '{
    "model": "google/gemini-3-flash-preview",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "Two words only."},
          {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
        ]
      }
    ],
    "stream": true,
    "stream_options": { "include_usage": true }
  }'
```

The response streams `data: { ... }` lines until a final terminator. Usage metrics appear only when requested: set `stream_options.include_usage` to `true` for streaming responses, or send `"include_usage": true` on non-streaming calls.

*Note: Prompt-caching helpers implicitly force `include_usage`, so cached requests still receive usage data without extra flags.*

## Video Input

Send video clips to a compatible text or multimodal model using the canonical `video_url` content part. The URL may be a public HTTPS URL or a `data:video/*;base64,...` URL:

```json theme={null}
{
  "model": "google/gemini-3.1-flash-lite",
  "messages": [{
    "role": "user",
    "content": [
      { "type": "text", "text": "Describe this clip." },
      {
        "type": "video_url",
        "video_url": {
          "url": "https://cdn.example.com/clip.mp4",
          "detail": "auto"
        }
      }
    ]
  }]
}
```

Compatibility aliases (`input_video`, direct `video`, and safely identifiable `input_file`/`file` blocks) are accepted, but new integrations should emit `video_url`. See the [Video Input guide](/api-reference/miscellaneous/video-input) for model discovery, source validation, limits, errors, YouTube behavior, and the Responses and Messages shapes.

### Caching (Implicit and Explicit Controls)

For the full guide (supported models, thresholds, pricing, and usage fields), see [Prompt Caching](/api-reference/miscellaneous/prompt-caching).

NanoGPT automatically applies implicit caching on providers/models that support it (including OpenAI, Gemini, and many open-source provider/model routes), so most requests do not need caching flags.

Set top-level `caching: true` or append `:caching` / `:cache` / `:cached` to the model when you want NanoGPT to route the request to any available provider that supports prompt/input caching. This is capability-based routing: you do not need to choose a provider. If no cache-capable provider is available for the model, the request fails rather than silently using a non-caching provider.

Use explicit prompt-caching controls (`prompt_caching`, `promptCaching`, and body-level `cache_control` alias, plus inline `cache_control`) when you need Claude-specific cache boundaries, TTL selection, or `prompt_caching.stickyProvider` consistency control. Top-level `caching: true` does not add Anthropic-style `cache_control` markers or configure cache TTLs.

#### Cache-Capable Provider Routing

Top-level `caching: true` is provider routing, not prompt-cache annotation. It requires the routed provider to be marked as prompt-caching capable for the requested provider-selection model.

```json theme={null}
{
  "model": "model-id",
  "caching": true,
  "messages": [
    { "role": "user", "content": "Hello" }
  ]
}
```

`caching: true` prefers the provider from your previous matching request (soft affinity). `stickyProvider` defaults to `false`; set it to `true` to disable cross-provider fallback. Neither setting guarantees a cache hit.

To disable cross-provider fallback for a cache-capable request, set `stickyprovider: true`:

```json theme={null}
{
  "model": "model-id",
  "caching": true,
  "stickyprovider": true,
  "messages": [
    { "role": "user", "content": "Hello" }
  ]
}
```

Top-level fields:

| Parameter | Type | Default | Description |
| - | - | - | - |
| `caching` | boolean | `false` | Require a cache-capable provider for this request. If none is usable for the model, the request fails. |
| `stickyprovider` | boolean | `false` | Set `true` to disable cross-provider fallback. `false` allows fallback while keeping soft affinity for explicit cache-capable routing. |
| `stickyProvider` | boolean | Alias | CamelCase alias for top-level `stickyprovider`. Use `stickyprovider` in examples. |

Equivalent model suffix:

```json theme={null}
{
  "model": "moonshotai/kimi-k2.6:thinking:caching",
  "messages": [
    { "role": "user", "content": "Hello" }
  ]
}
```

For `caching: true`, routing works as follows:

1. Filter to providers that are available, not excluded by preferences, and marked as prompt-caching capable.
2. Prefer the previously recorded provider for the same cache-relevant request shape when still usable.
3. Try eligible saved provider preferences, then choose using prices and recent aggregate cache-read observations.

Price ranking takes precedence over cache-affinity selection. See [routing and caching combinations](/api-reference/miscellaneous/provider-selection#price-caps-and-cache-reuse), including how `max_price` can infer price ranking.

The `prompt_caching` / `promptCaching` helper accepts these options:

| Parameter | Type | Default | Description |
| - | - | - | - |
| `enabled` | boolean | — | Set `true` to enable or `false` to disable explicit caching; `ttl` alone does not enable it. |
| `ttl` | string | `"5m"` | Cache time-to-live: `"5m"` or `"1h"`. Only the exact string `"1h"` selects one hour. |
| `cut_after_message_index` / `cutAfterMessageIndex` | integer | — | Zero-based last message index eligible for automatic cache-boundary placement. Existing inline markers are preserved. |
| `stickyProvider` | boolean | `false` | When `true`, disable automatic failover to preserve explicit prompt-cache consistency. Returns 503 error instead of switching services. |

```python theme={null}
headers = {
  "Authorization": "Bearer YOUR_API_KEY",
  "Content-Type": "application/json"
}

payload = {
  "model": "anthropic/claude-sonnet-4.6",
  "messages": [
    {
      "role": "system",
      "content": [
        {
          "type": "text",
          "text": "Reference handbook + rules of engagement.",
          "cache_control": {"type": "ephemeral", "ttl": "5m"}
        }
      ]
    },
    {"role": "user", "content": "Live request goes here"}
  ]
}

requests.post("https://nano-gpt.com/api/v1/chat/completions", headers=headers, json=payload)
```

* Each `cache_control` marker caches the full prefix up to that block. Choose reusable prefix boundaries; you do not need a marker on every static chunk. The request supports at most four breakpoints across system, tools, and messages.
* Explicit TTL controls are `5m` and `1h` for Claude caching flows. See [Prompt Caching](/api-reference/miscellaneous/prompt-caching#pricing).
* `anthropic-beta: prompt-caching-2024-07-31` is an optional compatibility alternative. Callers using the helper or inline markers do not also need this header; NanoGPT handles upstream cache settings.
* For implicit-caching providers, no explicit `cache_control` markers are required.
* Supported explicit cache controls on Chat Completions use pay-as-you-go billing, including markers supplied automatically by clients. See [subscription billing for prompt caching](/api-reference/miscellaneous/prompt-caching#subscription-billing-for-chat-completions) and the [OpenCode caching guide](/integrations/opencode#claude-prompt-caching).

For a simpler experience, send the helper fields and NanoGPT will place cache boundaries before forwarding upstream:

```ts theme={null}
await client.chat.completions.create(
  {
    model: 'anthropic/claude-opus-5.5',
    messages: [
      { role: 'system', content: 'Static rubric lives here.' },
      { role: 'user', content: 'Additional reusable context.' },
      { role: 'user', content: 'This turn is not cached.' },
    ],
    prompt_caching: {
      enabled: true,
      ttl: '1h',
      cut_after_message_index: 1,
    },
  },
);
```

`cut_after_message_index` is zero-based and limits automatic boundary placement; it does not remove existing inline markers after that index. If omitted, NanoGPT selects boundaries automatically. Use inline `cache_control` blocks when you need to place individual boundaries. See [Prompt Caching](/api-reference/miscellaneous/prompt-caching) for marker and TTL precedence.

### Explicit Prompt Cache Consistency

NanoGPT automatically fails over to backup services when the primary service is temporarily unavailable. While this ensures high availability, it can break your prompt cache because **each backend service maintains its own separate cache**.

If cache consistency is more important than availability for your use case, you can enable the `stickyProvider` option:

```json theme={null}
{
  "model": "anthropic/claude-sonnet-4.6",
  "messages": [...],
  "prompt_caching": {
    "enabled": true,
    "ttl": "5m",
    "stickyProvider": true
  }
}
```

**Behavior:**

* **`stickyProvider: false` (default)** — If an eligible backup is available, NanoGPT can retry there. That service may need to create its own cache.
* **`stickyProvider: true`** — NanoGPT returns a 503 instead of failing over. The original cache remains subject to its TTL; this setting does not guarantee it will still exist when the service recovers.

**When to use `stickyProvider: true`:**

* You have very large cached contexts where cache misses are expensive
* You prefer to retry failed requests yourself rather than pay for cache rebuilds
* Cost predictability is more important than request success rate

**When to use `stickyProvider: false` (default):**

* You prefer requests to always succeed when possible
* Occasional cache misses are acceptable
* You're using shorter contexts where cache rebuilds are inexpensive

**Error response when stickyProvider blocks a failover:**

```json theme={null}
{
  "error": {
    "message": "Service is temporarily unavailable. Fallback disabled to preserve prompt cache consistency. Switching services would invalidate your cached tokens. Remove stickyProvider option or retry later.",
    "status": 503,
    "type": "service_unavailable",
    "code": "fallback_blocked_for_cache_consistency"
  }
}
```

### Troubleshooting

* 400 unsupported image: ensure the image is a valid PNG/JPEG/WebP, not a tiny 1×1 pixel, and either HTTPS URL or a base64 data URL.
* 503 after fallbacks: try a different model, verify API key/session, and prefer base64 data URL for local or protected assets.
* Missing usage events: confirm `include_usage` is `true` in the payload or that prompt caching is enabled.

## Context Memory

Enable unlimited-length conversations with lossless, hierarchical memory.

* Append `:memory` to any model name
* Or send header `memory: true`
* Can be combined with web search: `:online:memory`
* Retention: default 30 days; configure via `:memory-<days>` (1..365) or header `memory_expiration_days: <days>`; header takes precedence

<CodeGroup>
  ```python Python theme={null}
  import requests

  BASE_URL = "https://nano-gpt.com/api/v1"
  API_KEY = "YOUR_API_KEY"

  headers = {
      "Authorization": f"Bearer {API_KEY}",
      "Content-Type": "application/json"
  }

  # Suffix-based
  payload = {
      "model": "openai/gpt-6.1-sol:memory",
      "messages": [{"role": "user", "content": "Keep our previous discussion in mind and continue."}]
  }
  requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
  ```

  ```javascript JavaScript theme={null}
  const BASE_URL = "https://nano-gpt.com/api/v1";
  const API_KEY = "YOUR_API_KEY";

  // Header-based (with optional retention override)
  await fetch(`${BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
      'memory': 'true',
      'memory_expiration_days': '45'
    },
    body: JSON.stringify({
      model: 'openai/gpt-6.1-sol',
      messages: [{ role: 'user', content: 'Continue with full history awareness.' }]
    })
  });
  ```

  ```bash cURL theme={null}
  # Combine with web search (and set retention to 90 days via suffix)
  curl -X POST https://nano-gpt.com/api/v1/chat/completions \
    -H "Authorization: Bearer YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "openai/gpt-6.1-sol:online:memory-90",
      "messages": [
        {"role": "user", "content": "Research and continue our plan without losing context."}
      ]
    }'

  # Header-based retention override (header takes precedence)
  curl -X POST https://nano-gpt.com/api/v1/chat/completions \
    -H "Authorization: Bearer YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -H "memory: true" \
    -H "memory_expiration_days: 45" \
    -d '{
      "model": "openai/gpt-6.1-sol",
      "messages": [
        {"role": "user", "content": "Use memory with 45-day retention."}
      ]
    }'
  ```
</CodeGroup>

### Custom Context Size Override

When Context Memory is enabled, you can override the model-derived context size used for the memory compression step with `model_context_limit`.

* Parameter: `model_context_limit` (number or numeric string)
* Default: Derived from the selected model’s context size
* Minimum: Values below 10,000 are clamped internally
* Scope: Only affects memory compression; does not change the target model’s own window

Examples:

```bash theme={null}
# Enable memory via header; use model default context size
curl -s -X POST \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -H "memory: true" \
  https://nano-gpt.com/api/v1/chat/completions \
  -d '{
    "model": "google/gemini-3-flash-preview",
    "messages": [{"role":"user","content":"Briefly say hello."}],
    "stream": false
  }'

# Explicit numeric override
curl -s -X POST \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -H "memory: true" \
  https://nano-gpt.com/api/v1/chat/completions \
  -d '{
    "model": "google/gemini-3-flash-preview",
    "messages": [{"role":"user","content":"Briefly say hello."}],
    "model_context_limit": 20000,
    "stream": false
  }'

# String override (server coerces to number)
curl -s -X POST \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -H "memory: true" \
  https://nano-gpt.com/api/v1/chat/completions \
  -d '{
    "model": "google/gemini-3-flash-preview",
    "messages": [{"role":"user","content":"Briefly say hello."}],
    "model_context_limit": "30000",
    "stream": false
  }'
```

## Reasoning Streams

The Chat Completions endpoint separates the model’s visible answer from its internal reasoning. By default, reasoning is included and delivered alongside normal content so that clients can decide whether to display it.

`:thinking` is model-specific and only works when that exact ID (or a documented alias) exists.
`-thinking` is a legacy alias pattern for some model families only, not universal.
Do not assume `-thinking` works for arbitrary model IDs. Always check `GET /api/v1/models` for exact valid IDs.

See also: [Extended Thinking (Reasoning)](/api-reference/miscellaneous/extended-thinking).

### Endpoint variants

Choose the base path that matches how your client consumes reasoning streams:

* `https://nano-gpt.com/api/v1/chat/completions` — default endpoint that streams internal thoughts through `choices[0].delta.reasoning` (and repeats them in `message.reasoning` on completion). Recommended for apps like SillyTavern that understand the modern response shape.
* `https://nano-gpt.com/api/v1legacy/chat/completions` — legacy contract that swaps the field name to `choices[0].delta.reasoning_content` / `message.reasoning_content` for older OpenAI-compatible clients. Use this for LiteLLM’s OpenAI adapter to avoid downstream parsing errors.
* `https://nano-gpt.com/api/v1thinking/chat/completions` — reasoning-aware models write everything into the normal `choices[0].delta.content` stream so clients that ignore reasoning fields still see the full conversation transcript. This is the preferred base URL for JanitorAI.

### Streaming payload format

Server-Sent Event (SSE) streams emit the answer in `choices[0].delta.content` and the thought process in `choices[0].delta.reasoning` (plus optional `delta.reasoning_details`). Reasoning deltas are dispatched before or alongside regular content, letting you render both panes in real-time.

```text theme={null}
data: {
  "choices": [{
    "delta": {
      "reasoning": "Assessing possible tool options…"
    }
  }]
}
data: {
  "choices": [{
    "delta": {
      "content": "Let me walk you through the solution."
    }
  }]
}
```

When streaming completes, the formatter aggregates the collected values and repeats them in the final payload: `choices[0].message.content` contains the assistant reply and `choices[0].message.reasoning` (plus `reasoning_details` when available) contains the full chain-of-thought. Non-streaming requests reuse the same formatter, so the reasoning block is present as a dedicated field.

### Showing or hiding reasoning

Send `reasoning: { "exclude": true }` to strip the reasoning payload from both streaming deltas and the final message. With this flag set, `delta.reasoning` and `message.reasoning` are omitted entirely.

```bash theme={null}
curl -X POST https://nano-gpt.com/api/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-opus-4.6",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "reasoning": {"exclude": true}
  }'
```

**Without reasoning.exclude**:

```json theme={null}
{
  "choices": [{
    "message": {
      "content": "The answer is 4.",
      "reasoning": "The user is asking for a simple addition. 2+2 equals 4."
    }
  }]
}
```

**With reasoning.exclude**:

```json theme={null}
{
  "choices": [{
    "message": {
      "content": "The answer is 4."
    }
  }]
}
```

### Reasoning Effort

`reasoning_effort` (or `reasoning.effort`) controls reasoning depth and also acts as an explicit reasoning-mode signal.
An accepted value other than `"none"` requests reasoning/thinking behavior. Available levels and defaults depend on the model.
Use `"none"` to request disabled reasoning only on models that support turning it off. Always-thinking models keep their reasoning requirements; Claude Opus 5.5 rejects attempts to disable thinking.

#### Parameter: `reasoning_effort`

| Value | Description |
| - | - |
| `none` | Requests disabled reasoning where the model supports it |
| `minimal` | Lowest reasoning depth |
| `low` | Low reasoning depth |
| `medium` | Medium reasoning depth |
| `high` | High reasoning depth |
| `xhigh` | Extra-high reasoning depth where supported |
| `max` | Maximum effort where supported; distinct from `xhigh` on models that accept both |

Claude Opus 5.5 uses adaptive thinking automatically, supports `low`, `medium`, `high`, `xhigh`, and `max`, and defaults to `high` when no effort or thinking budget is supplied. See [Opus 5.5 reasoning controls](/api-reference/miscellaneous/extended-thinking#claude-opus-5-5). `reasoning.exclude` only hides returned reasoning; it never disables thinking generation.

#### Usage

The `reasoning_effort` parameter can be passed at the top level:

```bash theme={null}
curl -X POST https://nano-gpt.com/api/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-opus-4.6",
    "messages": [
      {"role": "user", "content": "Explain quantum entanglement step by step"}
    ],
    "reasoning_effort": "high",
    "max_tokens": 4096
  }'
```

Alternatively, pass it as part of the `reasoning` object:

```json theme={null}
{
  "model": "anthropic/claude-opus-4.6",
  "messages": [{"role": "user", "content": "Solve this complex math problem..."}],
  "reasoning": {
    "effort": "high"
  }
}
```

Both formats are accepted. If both are present, top-level `reasoning_effort` is authoritative for Chat Completions request shaping.

#### Change Effort Within a Conversation

GPT-6 Astra and Claude Fable 5.1 accept `configuration_update` on empty `system` or `developer` messages. An update at the end of the request applies to the generated answer. Keep the request-level effort constant, preserve each update in later history, and do not place updates next to each other. See [inline reasoning effort updates](/api-reference/miscellaneous/inline-reasoning-effort) for examples and supported combinations.

#### Combining effort with exclude

`reasoning.exclude` controls output visibility only. It hides reasoning fields/blocks, but does not inherently disable reasoning compute.
If an effort level is set to a non-`none` value, reasoning can still run while hidden.

```json theme={null}
{
  "model": "anthropic/claude-opus-4.6",
  "messages": [{"role": "user", "content": "..."}],
  "reasoning": {
    "effort": "high",
    "exclude": true
  }
}
```

### Model suffix: reasoning effort

Clients that do not expose reasoning controls for custom-provider models can set an effort in the model ID, for example `openai/gpt-latest:reasoning-effort/high`. Supported suffix values are `none`, `low`, `medium`, `high`, `xhigh`, and `max`.

NanoGPT strips the suffix before model lookup and uses it as the default `reasoning_effort`. Explicit body generation settings take precedence. These IDs are not additional model-list entries; enter them manually in your client. Effort support remains model/provider-specific.

```json theme={null}
{
  "model": "openai/gpt-latest:reasoning-effort/high",
  "messages": [{ "role": "user", "content": "Analyze this design." }],
  "reasoning": { "exclude": true }
}
```

The `:reasoning-effort/high` example requests high effort while hiding reasoning output.

Use `openai/gpt-latest:reasoning-effort/none` to request disabled reasoning, equivalent to the base model with `reasoning_effort: "none"`. This is different from `:reasoning-exclude`, which only hides reasoning output. Models that require reasoning keep their existing restrictions. Explicit body generation settings, including enabled thinking, take precedence over the `none` suffix.

See [Reasoning Effort Suffixes](/api-reference/miscellaneous/model-suffixes#reasoning-effort-suffixes) for precedence, suffix composition, and Responses/Messages equivalents.

### Model suffix: `:reasoning-exclude`

You can toggle the filter without altering your JSON body by appending `:reasoning-exclude` to the `model` name.

* Equivalent to sending `{ "reasoning": { "exclude": true } }`
* Only the `:reasoning-exclude` suffix is stripped before the request is routed; other suffixes remain active
* Works for streaming and non-streaming responses on both Chat Completions and Text Completions

```json theme={null}
{
  "model": "anthropic/claude-opus-4.6:reasoning-exclude",
  "messages": [{ "role": "user", "content": "What is 2+2?" }]
}
```

#### Combine with other suffixes

`:reasoning-exclude` composes safely with the other routing suffixes you already use:

* `:thinking` (when that exact model ID exists). `-thinking` variants are legacy aliases for some families only.
* `:online` and `:online/linkup-deep`
* `:memory` and `:memory-<days>`

Examples:

* `anthropic/claude-sonnet-4.6:thinking:8192:reasoning-exclude`
* <code>{exampleTextModel}:online:reasoning-exclude</code>
* `anthropic/claude-opus-4.6:memory-30:online/linkup-deep:reasoning-exclude`
* `z-ai/glm-5.3-flash:fast:reasoning-exclude`
* `z-ai/glm-5.3-flash:cheap:reasoning-exclude`

### Legacy delta field compatibility

Older clients that expect the legacy `reasoning_content` field can opt in per request. Set `reasoning.delta_field` to `"reasoning_content"`, or use the top-level shorthands `reasoning_delta_field` / `reasoning_content_compat` if updating nested objects is difficult. When the toggle is active, every streaming and non-streaming response exposes `reasoning_content` instead of `reasoning`, and the modern key is omitted. The compatibility pass is skipped if `reasoning.exclude` is `true`, because no reasoning payload is emitted. If you cannot change the request payload, target `https://nano-gpt.com/api/v1legacy/chat/completions` instead—the legacy endpoint keeps `reasoning_content` without extra flags. LiteLLM’s OpenAI adapter should point here to maintain compatibility. For clients that ignore reasoning-specific fields entirely, use `https://nano-gpt.com/api/v1thinking/chat/completions` so the full text appears in the standard content stream; this is the correct choice for JanitorAI.

```json theme={null}
{
  "model": "openai/gpt-6.1-sol",
  "messages": [...],
  "reasoning": {
    "delta_field": "reasoning_content"
  }
}
```

#### Notes and limitations

* GPU-TEE models (`phala/*`) require byte-for-byte SSE passthrough for signature verification. For those models, streaming cannot be filtered; the suffix has no effect on the streaming bytes.
* When assistant content is an array (e.g., vision/text parts), only text parts are filtered; images and tool/metadata content are untouched.

<a id="service-tiers-priority" />

## Service tiers (Flex and Fast/Priority)

Set `service_tier` to request a non-default capacity tier on providers that support service tiers:

* `auto` or omitted: use NanoGPT's normal routing and the provider default.
* `default`: request the provider's standard tier where the provider accepts an explicit default value.
* `flex`: request lower-cost, variable-capacity processing where supported.
* `fast`: request lower-latency, higher-priority processing where supported.
* `priority`: legacy alias for `fast` on OpenAI models; compatible non-OpenAI providers may continue to use the Priority name.

Before sending a tiered request, call [`GET /api/v1/models?detailed=true`](/api-reference/endpoint/models) and inspect the selected model's `supported_service_tiers` array. The basic model list intentionally omits this field for OpenAI compatibility. An empty array means the model supports only the default tier.

Behavior notes:

* When `service_tier` is `"flex"`, `"fast"`, or `"priority"`, NanoGPT prefers routing to providers that support the requested tier.
* Service tier availability is model- and provider-specific. The detailed model API is the programmatic source of truth; [model pages](https://nano-gpt.com/models) show the same support as badges.
* Not all providers support service tiers, so tiered requests may be routed differently than default requests.
* Header provider overrides (like `X-Provider`) and explicit provider selection are honored for pricing and x402 estimates.
* Provider-native web search can force routing; tier pricing follows that routing.
* If you explicitly force a provider that does not support service tiers, the requested tier may be ignored by the upstream provider, or routing and pricing may differ from the default route.

Billing note:

* Flex requests are billed at flex rates where applicable.
* Fast/Priority requests are billed at the applicable higher-priority rate.
* High-context pricing may also apply for models and providers with separate high-context SKUs, such as `es2k` pricing for GPT-5.5/GPT-5.4 where available.

Response note:

* Responses now include a top-level `service_tier` field when it is provided on the request.

### Example: flex tier

```json theme={null}
{
  "model": "openai/gpt-5.5",
  "messages": [
    { "role": "user", "content": "Give me a concise release note." }
  ],
  "service_tier": "flex"
}
```

### Example: fast tier

```json theme={null}
{
  "model": "openai/gpt-5.5",
  "messages": [
    { "role": "user", "content": "Give me a concise release note." }
  ],
  "service_tier": "fast"
}
```

Use `"priority"` instead only when maintaining compatibility with an older integration or a provider route that still uses that name.

## YouTube Transcripts

Automatically fetch and prepend YouTube video transcripts when the latest user message contains YouTube links.

### Defaults

* Parameter: `youtube_transcripts` (boolean)
* Default: `false` (opt-in)
* Opt-in: set `youtube_transcripts` to `true` (string `"true"` is also accepted) to fetch transcripts
* Limit: Up to 3 YouTube URLs processed per request
* Higher volume: Use the standalone [`POST /api/youtube-transcribe`](/api-reference/endpoint/youtube-transcribe) endpoint for up to 10 URLs per request
* Injection: Transcripts are added as a system message before your messages
* Billing: \$0.01 per transcript fetched

### Enable automatic transcripts

By default, YouTube links are ignored. Set `youtube_transcripts` to `true` when you want the system to retrieve and bill for transcripts.

```bash theme={null}
curl -X POST https://nano-gpt.com/api/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemini-3-flash-preview",
    "messages": [
      {"role": "user", "content": "Summarize this: https://youtu.be/dQw4w9WgXcQ"}
    ],
    "youtube_transcripts": true
  }'
```

### Notes

* Web scraping is separate. To scrape non‑YouTube URLs, set `scraping: true`. YouTube transcripts do not require `scraping: true`.
* When not requested, YouTube links are ignored for transcript fetching and are not billed.
* If your balance is insufficient when enabled, the request may be blocked with a 402.

## Performance Benchmarks

LinkUp achieves state-of-the-art performance on OpenAI's SimpleQA benchmark:

| Provider | Score |
| - | - |
| LinkUp Deep Search | 90.10% |
| Exa | 90.04% |
| Perplexity Sonar Pro | 86% |
| LinkUp Standard Search | 85% |
| Perplexity Sonar | 77% |
| Tavily | 73% |

## Compressed Request Bodies

Request bodies may be sent gzip, deflate, or Brotli compressed by adding a `Content-Encoding` header (e.g. `Content-Encoding: gzip`). Conversation-history payloads compress roughly 5:1, which cuts upload time — and therefore time-to-first-token — on long conversations. Requires a JSON `Content-Type` and authentication; the 32 MB body limit applies to both the compressed and decompressed body. See [Compressed Request Bodies](/api-reference/miscellaneous/request-compression) for SDK-ready snippets.

## Important Notes

* Web search increases input token count, which affects total cost
* Models gain access to real-time information published less than a minute ago
* Internet connectivity can provide up to 10x improvement in factuality
* Almost all models support web search (the NanoGPT help model does not) - append a suffix or send a `web_search` object (`webSearch` and `linkup` are supported as aliases)


## OpenAPI

````yaml POST /v1/chat/completions
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
  /v1/chat/completions:
    servers:
      - url: https://nano-gpt.com/api
        description: Website API (current model examples)
      - url: https://api.nano-gpt.com/api
        description: Direct API; choose a model listed by this host
    post:
      description: >-
        Creates a chat completion for the provided messages. The NanoGPT Advisor
        extension is available for non-streaming, platform-billed pay-as-you-go
        API-key requests that do not use client tools, structured output, inline
        moderation, BYOK, accountless payment, memory, or server-side content
        enhancements.
      parameters:
        - name: X-Provider
          in: header
          description: >-
            Optional explicit provider override for supported open-source models
            (case-insensitive). Explicit provider selection is billed
            pay-as-you-go at the selected provider's price, including
            provider-selection markup; for subscription users it bypasses
            subscription coverage for that request.
          required: false
          schema:
            type: string
        - name: X-Billing-Mode
          in: header
          description: >-
            Optional billing override to force pay-as-you-go without an explicit
            provider, or to apply saved provider preferences to
            subscription-included traffic (e.g., paygo). Header name is
            case-insensitive.
          required: false
          schema:
            type: string
        - name: x-x402
          in: header
          description: >-
            Set to true on unauthenticated accountless x402 quote requests.
            Without this header, unauthenticated requests return 401
            missing_api_key.
          required: false
          schema:
            type: string
            enum:
              - 'true'
      requestBody:
        description: Parameters for chat completion
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ChatCompletionRequest'
        required: true
      responses:
        '200':
          description: Chat completion response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ChatCompletionResponse'
        '400':
          description: >-
            Unexpected error. Video errors include video_input_not_supported,
            invalid_video_url_scheme, invalid_video_data_url,
            invalid_video_base64, invalid_video_mime_type, missing_video_source,
            video_file_id_not_supported, video_attachment_too_large,
            video_attachment_limit_exceeded, invalid_video_segment,
            video_segment_not_supported, and youtube_video_route_not_supported.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '402':
          description: >-
            Payment Required - authenticated insufficient balance or opted-in
            accountless x402 quote for supported non-streaming requests
          content:
            application/json:
              schema:
                oneOf:
                  - $ref: '#/components/schemas/Error'
                  - $ref: '#/components/schemas/X402PaymentRequiredResponse'
      security:
        - bearerAuth: []
        - {}
components:
  schemas:
    ChatCompletionRequest:
      type: object
      required:
        - model
        - messages
      properties:
        model:
          type: string
          description: >-
            The model to use for completion. The model value may include
            supported model suffixes, including web search (':online',
            ':online/<provider>'), memory (':memory', ':memory-<days>'),
            reasoning visibility (':reasoning-exclude'), thinking variants where
            listed by the model catalog (':thinking'), and provider routing
            preferences for eligible models (':fast', ':cheap', ':caching',
            etc.). Model ID or compatibility alias. Append
            :reasoning-effort/<effort>, where effort is none, low, medium, high,
            xhigh, or max, to supply a default reasoning_effort. The suffix is
            stripped before model routing and is not listed as a separate model.
            Explicit reasoning generation settings take precedence, including
            enabled thinking when the suffix is none. The none suffix requests
            disabled reasoning where supported; it does not bypass
            model/provider restrictions. Other effort levels remain
            model/provider-specific.
          default: minimax/minimax-m2.7
          examples:
            - minimax/minimax-m2.7
            - zai-org/glm-5:fast
            - zai-org/glm-5:cheap
            - openai/gpt-6.1-sol:online/exa-instant
            - openai/gpt-6.1-sol:online/exa-deep-reasoning
        billing_mode:
          type: string
          description: >-
            Billing override to force pay-as-you-go without an explicit
            provider, or to apply saved provider preferences to
            subscription-included traffic. Accepted values (case-insensitive):
            paygo, pay-as-you-go, pay_as_you_go, paid, payg.
        billingMode:
          type: string
          description: Alias for billing_mode.
        provider:
          description: >-
            Optional provider override or structured provider routing controls
            for provider-selection-capable models. A string explicitly selects
            one provider. An object can set soft order, hard pins, exclusions,
            sort preference, price caps, fallback behavior, and
            parameter-capability requirements.
          oneOf:
            - type: string
              description: Provider ID or accepted provider display name/alias.
            - $ref: '#/components/schemas/ProviderRoutingObject'
        caching:
          type: boolean
          description: >-
            When true, route to an available provider that is marked as
            prompt/input-caching capable for the requested provider-selection
            model. If no usable cache-capable provider exists, the request fails
            instead of falling back to a non-cache-capable provider. This is
            provider capability routing only; it does not add cache_control
            markers, configure cache TTLs, or force a cache write. The model
            suffixes ':caching', ':cache', and ':cached' request the same
            behavior.
          default: false
        stickyprovider:
          type: boolean
          description: >-
            Top-level routing control for caching: true. When caching is true,
            defaults to true and prefers the previously recorded provider for
            later matching requests from the same API key or session when still
            usable. Set false to require a cache-capable provider without sticky
            routing.
        stickyProvider:
          type: boolean
          description: >-
            CamelCase alias for top-level stickyprovider. Distinct from
            prompt_caching.stickyProvider, which controls explicit prompt-cache
            failover behavior.
        messages:
          type: array
          description: >-
            Array of message objects with role and content; content-less
            system/developer configuration_update messages are supported for
            Astra and Fable 5.1, including trailing updates.
          default:
            - role: user
              content: Testing, please reply!
          items:
            type: object
            required:
              - role
            properties:
              role:
                type: string
                description: The role of the message author
                enum:
                  - system
                  - user
                  - assistant
                  - developer
              content:
                description: >-
                  Message content as a simple string or an array of multimodal
                  parts
                oneOf:
                  - type: string
                  - type: array
                    items:
                      $ref: '#/components/schemas/MessageContentPart'
                  - type: 'null'
              configuration_update:
                $ref: '#/components/schemas/InlineConfigurationUpdate'
            allOf:
              - if:
                  required:
                    - configuration_update
                then:
                  properties:
                    role:
                      enum:
                        - system
                        - developer
                    content:
                      enum:
                        - ''
                        - []
                        - null
                else:
                  required:
                    - content
                  properties:
                    content:
                      not:
                        type: 'null'
        stream:
          type: boolean
          description: Whether to stream the response
          default: false
        service_tier:
          type: string
          enum:
            - auto
            - default
            - flex
            - fast
            - priority
          description: >-
            Optional processing tier. Use `flex` for lower-cost
            variable-capacity processing or `fast` for higher-priority
            processing where supported. `priority` remains accepted as a legacy
            alias for Fast on OpenAI models. Discover model support with `GET
            /api/v1/models?detailed=true` and inspect `supported_service_tiers`;
            the basic model list intentionally omits this field.
        temperature:
          type: number
          description: >-
            Classic randomness control. Accepts any decimal between 0-2. If
            omitted, NanoGPT does not force a value and the routed
            provider/model default applies
          minimum: 0
          maximum: 2
        max_tokens:
          type: integer
          description: >-
            Upper bound on generated tokens. If omitted, NanoGPT does not
            enforce an explicit default and the routed provider/model default
            applies
          minimum: 1
        top_p:
          type: number
          description: >-
            Nucleus sampling. When set below 1.0, trims candidate tokens to the
            smallest set whose cumulative probability exceeds top_p. Works well
            as an alternative to tweaking temperature
          minimum: 0
          maximum: 1
          default: 1
        frequency_penalty:
          type: number
          description: >-
            Penalizes tokens proportionally to how often they appeared
            previously. Negative values encourage repetition; positive values
            discourage it
          minimum: -2
          maximum: 2
          default: 0
        presence_penalty:
          type: number
          description: >-
            Penalizes tokens based on whether they appeared at all. Good for
            keeping the model on topic without outright banning words
          minimum: -2
          maximum: 2
          default: 0
        repetition_penalty:
          type: number
          description: >-
            Provider-agnostic repetition modifier (distinct from OpenAI
            penalties). Values >1 discourage repetition
          minimum: -2
          maximum: 2
        top_k:
          type: integer
          description: Caps sampling to the top-k highest probability tokens per step
        top_a:
          type: number
          description: >-
            Combines top-p and temperature behavior; leave unset unless a model
            description explicitly calls for it
        min_p:
          type: number
          description: >-
            Ensures each candidate token probability exceeds a floor (0-1).
            Helpful for stopping models from collapsing into low-entropy loops
          minimum: 0
          maximum: 1
        tfs:
          type: number
          description: >-
            Tail free sampling. Values between 0-1 let you shave the long tail
            of the distribution; 1.0 disables the feature
          minimum: 0
          maximum: 1
        eta_cutoff:
          type: number
          description: >-
            Cut probabilities as soon as they fall below the specified tail
            threshold
        epsilon_cutoff:
          type: number
          description: >-
            Cut probabilities as soon as they fall below the specified tail
            threshold
        typical_p:
          type: number
          description: >-
            Typical sampling (aka entropy-based nucleus). Works like top_p but
            preserves tokens whose surprise matches the expected entropy
          minimum: 0
          maximum: 1
        mirostat_mode:
          type: integer
          description: >-
            Enables Mirostat sampling for models that support it. Set to 1 or 2
            to activate
          enum:
            - 0
            - 1
            - 2
        mirostat_tau:
          type: number
          description: >-
            Mirostat target entropy parameter. Used when mirostat_mode is
            enabled
        mirostat_eta:
          type: number
          description: Mirostat learning rate parameter. Used when mirostat_mode is enabled
        min_tokens:
          type: integer
          description: >-
            For providers that support it, enforces a minimum completion length
            before stop conditions fire
          default: 0
          minimum: 0
        stop:
          description: >-
            Stop sequences. Accepts string or array of strings. Values are
            passed directly to upstream providers
          oneOf:
            - type: string
            - type: array
              items:
                type: string
        stop_token_ids:
          type: array
          description: >-
            Numeric array that lets callers stop generation on specific token
            IDs. Not supported by many providers
          items:
            type: integer
        include_stop_str_in_output:
          type: boolean
          description: >-
            When true, keeps the stop sequence in the final text. Not supported
            by many providers
          default: false
        ignore_eos:
          type: boolean
          description: >-
            Allows completions to continue even if the model predicts EOS
            internally. Useful for long creative writing runs
          default: false
        no_repeat_ngram_size:
          type: integer
          description: >-
            Extension that forbids repeating n-grams of the given size. Not
            supported by many providers
          minimum: 0
        custom_token_bans:
          type: array
          description: List of token IDs to fully block
          items:
            type: integer
        logit_bias:
          type: object
          description: >-
            Object mapping token IDs to additive logits. Works just like
            OpenAI's version
          additionalProperties:
            type: number
        logprobs:
          description: >-
            When true or a number, forwards the request to providers that
            support returning token-level log probabilities
          oneOf:
            - type: boolean
            - type: integer
        prompt_logprobs:
          type: boolean
          description: >-
            Requests logprobs on the prompt itself when the upstream API allows
            it
        seed:
          type: integer
          description: >-
            Optional integer forwarded on model/provider routes that support
            seeded sampling. This may improve reproducibility but does not
            guarantee identical output. Results can change if NanoGPT selects a
            different automatic or fallback route, or if the provider changes
            its backend.
        web_search:
          description: >-
            Web search for this request. `true` turns search on with the default
            provider (native search on GPT-5+ and o-series models, Linkup
            elsewhere); `false` leaves search off unless an `:online` model
            suffix turns it on. `webSearch` and the legacy `linkup` object are
            accepted aliases; when more than one is sent, `web_search` wins,
            then `webSearch`. See the Web Search section of the chat completion
            guide for provider-specific options.
          oneOf:
            - type: boolean
            - type: object
              properties:
                enabled:
                  type: boolean
                  description: Must be true for the object to turn on search.
                provider:
                  type: string
                  enum:
                    - native
                    - linkup
                    - tavily
                    - brave
                    - sofya
                    - exa
                    - kagi
                    - perplexity
                    - valyu
                    - firecrawl
                  description: >-
                    Search provider. `native` uses the model's own search
                    (GPT-5+ and o-series, Claude 4+, Gemini 3+, Grok 4.20+; not
                    image, multi-agent, or `:free` variants). Unsupported models
                    fall back to the suffix's provider, or Linkup.
                depth:
                  type: string
                  description: >-
                    Search depth: `standard` or `deep` for most providers; Exa
                    also accepts `fast`, `auto`, `neural`, `instant`, and
                    `deep-reasoning`.
                search_context_size:
                  type: string
                  enum:
                    - low
                    - medium
                    - high
                  description: >-
                    Native search only. How much search context the model uses
                    (default `medium`; OpenAI deep-research models always use
                    `medium`).
                user_location:
                  type: object
                  description: >-
                    Native search on GPT-5+ and o-series models only; may be
                    ignored when a fallback route serves the request.
                    Approximate user location; `userLocation` is accepted as an
                    alias.
                  properties:
                    type:
                      type: string
                      enum:
                        - approximate
                    country:
                      type: string
                      description: Two-letter ISO country code, for example `US`.
                    city:
                      type: string
                    region:
                      type: string
                    timezone:
                      type: string
                      description: IANA time zone, for example `America/Los_Angeles`.
        web_search_options:
          type: object
          description: >-
            OpenAI-compatible web search options. Turns on web search with the
            default provider (native search on GPT-5+ and o-series models,
            Linkup elsewhere). Ignored when the request also sends `web_search`,
            `webSearch`, or `linkup`, and on models that already search on their
            own. When an `:online/<provider>` suffix is present, its provider
            and depth are kept. The NanoGPT help model rejects a non-empty
            object.
          properties:
            search_context_size:
              type: string
              enum:
                - low
                - medium
                - high
              description: Passed to native search. Never selects deep search.
            user_location:
              type: object
              description: >-
                Approximate user location, passed to native search on GPT-5+ and
                o-series models.
              properties:
                type:
                  type: string
                  enum:
                    - approximate
                approximate:
                  type: object
                  properties:
                    country:
                      type: string
                    city:
                      type: string
                    region:
                      type: string
                    timezone:
                      type: string
        max_tool_calls:
          type: integer
          description: >-
            Maximum number of built-in tool calls, such as native web searches,
            page opens and searches within a page, the model can make in one
            response. Applies to requests NanoGPT sends to OpenAI's Responses
            API, including GPT-5+ and o-series native search and your own OpenAI
            key (BYOK); calls past the cap are not run or billed. Other routes,
            and rerouted requests such as Auto Model, ignore it.
        prompt_caching:
          type: object
          description: >-
            Helper to tag leading messages for explicit prompt-caching control
            (primarily Claude flows). Providers with implicit caching support
            (including OpenAI, Gemini, and many open-source provider routes) do
            not require this helper. NanoGPT injects cache_control blocks on
            each message up to the specified index before forwarding upstream.
            If cut_after_message_index is omitted, NanoGPT selects a cache
            boundary automatically.
          properties:
            enabled:
              type: boolean
              description: Whether to enable prompt caching on this request
              default: false
            ttl:
              type: string
              description: Cache time-to-live ('5m' or '1h')
              enum:
                - 5m
                - 1h
              example: 5m
            cut_after_message_index:
              type: integer
              minimum: 0
              description: >-
                Zero-based index of the last message that should be cached. All
                messages up to and including this index receive the same
                cache_control block.
            stickyProvider:
              type: boolean
              description: >-
                When true, avoids failover to preserve prompt cache consistency.
                If a fallback would be required, the request can return 503
                instead.
              default: false
        reasoning_effort:
          type: string
          description: >-
            Controls reasoning depth and acts as an explicit reasoning-mode
            signal. Any value other than "none" requests reasoning/thinking
            behavior. Use "none" to explicitly disable reasoning.
          enum:
            - none
            - minimal
            - low
            - medium
            - high
            - xhigh
        reasoning:
          type: object
          description: >-
            Reasoning configuration. `exclude` controls output visibility (hides
            reasoning fields/blocks) and does not inherently disable reasoning
            compute. `effort` controls depth, and `delta_field` switches to
            legacy `reasoning_content` fields.
          additionalProperties: true
          properties:
            exclude:
              type: boolean
              description: When true, omits reasoning fields from the response
            effort:
              type: string
              description: >-
                Alias for reasoning_effort. If both are provided, top-level
                reasoning_effort is authoritative for Chat Completions request
                shaping.
              enum:
                - none
                - minimal
                - low
                - medium
                - high
                - xhigh
            delta_field:
              type: string
              description: >-
                When set to "reasoning_content", uses legacy reasoning_content
                fields instead of reasoning
              enum:
                - reasoning_content
        reasoning_delta_field:
          type: string
          description: Shorthand for reasoning.delta_field
          enum:
            - reasoning_content
        reasoning_content_compat:
          type: boolean
          description: Shorthand to force legacy reasoning_content fields in the response
        advisor:
          $ref: '#/components/schemas/AdvisorConfig'
      allOf:
        - if:
            properties:
              advisor: {}
            required:
              - advisor
          then:
            properties:
              stream:
                enum:
                  - false
    ChatCompletionResponse:
      type: object
      properties:
        id:
          type: string
          description: Unique identifier for the completion
        object:
          type: string
          description: Object type, always 'chat.completion'
        created:
          type: integer
          description: Unix timestamp of when the completion was created
        choices:
          type: array
          description: Array of completion choices
          items:
            type: object
            properties:
              index:
                type: integer
                description: Index of the choice
              message:
                type: object
                properties:
                  role:
                    type: string
                    description: Role of the completion message
                    enum:
                      - assistant
                  content:
                    type: string
                    description: Content of the completion message
                  reasoning:
                    type: string
                    description: >-
                      Optional reasoning output (when supported and not
                      excluded)
                  reasoning_content:
                    type: string
                    description: >-
                      Legacy alias of reasoning (only present when legacy
                      compatibility is enabled)
                  reasoning_details:
                    type: array
                    description: Optional structured reasoning metadata (when available)
                    items:
                      type: object
                      additionalProperties: true
              finish_reason:
                type: string
                description: Reason why the completion finished
                enum:
                  - stop
                  - length
                  - content_filter
        usage:
          type: object
          properties:
            prompt_tokens:
              type: integer
              description: Number of tokens in the prompt
            prompt_tokens_details:
              type: object
              description: Optional details about prompt token accounting
              properties:
                cached_tokens:
                  type: integer
                  description: Cached input tokens (when prompt caching is used)
            cache_creation_input_tokens:
              type: integer
              description: >-
                Input tokens written to cache on this request (when prompt
                caching is used)
            cache_read_input_tokens:
              type: integer
              description: >-
                Input tokens read from cache on this request (when prompt
                caching is used)
            completion_tokens:
              type: integer
              description: Number of tokens in the completion
            completion_tokens_details:
              type: object
              description: Optional breakdown of completion token accounting
              additionalProperties: true
              properties:
                reasoning_tokens:
                  type: integer
                  description: Reasoning tokens within the completion (when reported)
            reasoning_tokens:
              type: integer
              description: Reasoning tokens within the completion (when reported)
            total_tokens:
              type: integer
              description: Total number of tokens used
        service_tier:
          type: string
          description: Service tier used (echoed when provided on the request)
        advisor:
          $ref: '#/components/schemas/AdvisorResponseMetadata'
          description: >-
            Advisor orchestration status and per-phase usage. Present on
            responses to requests that use the Advisor extension.
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
    X402PaymentRequiredResponse:
      type: object
      description: >-
        402 Payment Required body for accountless x402. New clients should key
        off the top-level payment object; accepts is retained for backwards
        compatibility.
      additionalProperties: true
      properties:
        error:
          type: object
          additionalProperties: true
          properties:
            message:
              type: string
            type:
              type: string
            code:
              type: string
        payment:
          $ref: '#/components/schemas/X402PaymentQuote'
        x402Version:
          type: integer
          example: 1
        accepts:
          type: array
          items:
            $ref: '#/components/schemas/X402AcceptOption'
        requestHash:
          type: string
    ProviderRoutingObject:
      type: object
      description: >-
        Structured per-request provider routing controls. Per-request controls
        take precedence over saved provider preferences and are not merged with
        them.
      properties:
        order:
          type: array
          description: >-
            Soft provider preference order. NanoGPT tries these providers first
            when possible, but this does not hard-pin routing to only these
            providers. Unknown providers are ignored.
          items:
            type: string
        only:
          type: array
          description: >-
            Hard provider pin. NanoGPT restricts routing to these providers and
            fails instead of silently routing elsewhere. Unknown providers
            return a structured 400 error with code provider_unknown_provider.
          items:
            type: string
        ignore:
          type: array
          description: Providers to exclude from routing. Unknown providers are ignored.
          items:
            type: string
        sort:
          type: string
          description: >-
            Routing preference. speed, throughput, latency, and price actively
            request that strategy. auto, none, and default are accepted to
            suppress stored/default routing preferences without requesting a
            provider sort.
          enum:
            - speed
            - throughput
            - latency
            - price
            - auto
            - none
            - default
        quantizations:
          type: array
          description: >-
            Hard allowlist of model weight quantization levels. Providers
            without matching known quantization metadata are excluded unless
            unknown is included explicitly.
          minItems: 1
          items:
            type: string
            enum:
              - int4
              - fp4
              - fp6
              - int8
              - fp8
              - fp16
              - bf16
              - fp32
              - unknown
        min_quantization:
          type: string
          description: >-
            Minimum model weight quantization precision floor. Quantizations are
            ordered by bit width; integer and floating-point formats with the
            same bit width are treated as equivalent. unknown is not valid
            because it cannot be compared to a precision floor.
          enum:
            - int4
            - fp4
            - fp6
            - int8
            - fp8
            - fp16
            - bf16
            - fp32
        max_price:
          type: object
          description: >-
            Optional provider price caps in USD per 1 million tokens. Pricing
            checks are best-effort when provider pricing is unknown.
          properties:
            prompt:
              type: number
              description: Maximum prompt/input price in USD per 1 million tokens.
              minimum: 0
            completion:
              type: number
              description: Maximum completion/output price in USD per 1 million tokens.
              minimum: 0
        allow_fallbacks:
          type: boolean
          description: When false, disables cross-provider fallback for this request.
        require_parameters:
          type: boolean
          description: >-
            When true, requires the selected provider to support the requested
            parameters on routes that support parameter-level capability checks.
    MessageContentPart:
      type: object
      required:
        - type
      additionalProperties: true
      properties:
        type:
          type: string
          description: Content block type
          enum:
            - text
            - image_url
            - video_url
            - input_text
            - input_audio
            - input_video
            - video
            - input_file
            - file
            - document
            - tool_use
            - tool_result
        text:
          type: string
          description: Text content when type is 'text'
        image_url:
          type: object
          description: Image reference for multimodal prompts
          properties:
            url:
              type: string
              description: HTTPS URL or base64 data URL for the image
            detail:
              type: string
              description: Requested image resolution detail
              enum:
                - low
                - high
                - auto
        input_audio:
          type: object
          description: Inline audio input payload
          properties:
            data:
              type: string
              description: Base64 encoded audio bytes
            format:
              type: string
              description: Audio format (e.g. wav, mp3)
        video_url:
          $ref: '#/components/schemas/VideoUrl'
        start_offset:
          type: number
          minimum: 0
        end_offset:
          type: number
          minimum: 0
        cache_control:
          type: object
          description: >-
            Prompt caching control applied to this content block for explicit
            caching flows (primarily Claude).
          properties:
            type:
              type: string
              enum:
                - ephemeral
              description: >-
                Cache type. Claude currently exposes the 'ephemeral' tier for
                5m/1h TTLs.
            ttl:
              type: string
              enum:
                - 5m
                - 1h
              description: Optional TTL override for this block.
    InlineConfigurationUpdate:
      type: object
      required:
        - reasoning
      properties:
        reasoning:
          $ref: '#/components/schemas/InlineReasoningEffort'
      additionalProperties: false
      description: >-
        Ordered effort control for Astra and Fable 5.1. A trailing update
        applies to the generated response. Keep baseline effort unchanged and
        replay each update in its original position; adjacent updates are
        rejected. See /api-reference/miscellaneous/inline-reasoning-effort.
    AdvisorConfig:
      type: object
      description: >-
        Allows the executor model to consult one different advisor model. Auto
        mode lets the executor decide whether to consult; required mode forces
        one consultation request. Advisor is non-streaming and available only
        for platform-billed pay-as-you-go API-key requests. Subscriptions, BYOK,
        accountless x402, Private Mode, inline moderation, client tools,
        structured outputs, memory, and server-side content enhancements are
        rejected before orchestration. Each completed executor, advisor, and
        continuation phase is billed separately.
      properties:
        model:
          type: string
          minLength: 1
          description: >-
            Explicit advisor model ID. Automatic model selection and the
            executor's resolved model are not allowed.
        instructions:
          type: string
          maxLength: 16000
        mode:
          type: string
          enum:
            - auto
            - required
          default: auto
          description: >-
            Auto lets the executor decide whether to consult. Required forces
            exactly one internal consultation request before the final answer.
        max_uses:
          type: integer
          enum:
            - 1
          default: 1
        max_completion_tokens:
          type: integer
          minimum: 1
          description: >-
            Optional advisor output-token limit. When omitted, NanoGPT does not
            impose an Advisor-specific output cap and the selected
            model/provider defaults apply.
        forward_transcript:
          type: boolean
          enum:
            - false
          default: false
      required:
        - model
      additionalProperties: false
    AdvisorResponseMetadata:
      type: object
      description: >-
        Advisor orchestration outcome. Top-level usage and pricing aggregate
        billable phases that returned usage, including an HTTP-success advisor
        phase whose output was unusable; the optional per-phase objects provide
        reconciliation detail.
      properties:
        id:
          type: string
        mode:
          type: string
          enum:
            - auto
            - required
        executor_model:
          type: string
        advisor_model:
          type: string
        requested:
          type: boolean
          description: Whether the executor emitted the internal consultation request.
        consulted:
          type: boolean
          description: Whether an advisor child call was attempted.
        successful:
          type: boolean
          description: Whether the advisor returned usable advice.
        consultation_count:
          type: integer
          enum:
            - 0
            - 1
        max_uses:
          type: integer
          enum:
            - 1
        status:
          type: string
          enum:
            - not_used
            - completed
            - failed
        error:
          type: string
          description: Present when consultation failed but the executor could continue.
        usage:
          $ref: '#/components/schemas/AdvisorPhaseBreakdown'
        pricing:
          $ref: '#/components/schemas/AdvisorPhaseBreakdown'
      required:
        - id
        - mode
        - executor_model
        - advisor_model
        - requested
        - consulted
        - successful
        - consultation_count
        - max_uses
        - status
      additionalProperties: false
    X402PaymentQuote:
      type: object
      description: Canonical accountless x402 payment quote.
      additionalProperties: true
      properties:
        version:
          type: integer
          example: 1
        paymentId:
          type: string
          example: pay_abc123
        requestHash:
          type: string
          example: sha256:...
        expiresAt:
          type: string
          format: date-time
        amountUsd:
          type: string
          example: '0.0714'
        statusUrl:
          type: string
          format: uri
        completeUrl:
          type: string
          format: uri
        accepted:
          type: array
          items:
            $ref: '#/components/schemas/X402PaymentAcceptedOption'
    X402AcceptOption:
      type: object
      description: Legacy lower-level payment option offered in an x402 402 response.
      additionalProperties: true
      properties:
        scheme:
          type: string
        network:
          type: string
        asset:
          type: string
        resource:
          type: string
        description:
          type: string
        payTo:
          type: string
        paymentId:
          type: string
        expiresAt:
          type: integer
        callbackUrl:
          type: string
        completeUrl:
          type: string
        maxAmountRequired:
          type: string
        maxAmountRequiredFormatted:
          type: string
        maxAmountRequiredUSD:
          type: number
        mimeType:
          type: string
        extra:
          type: object
          additionalProperties: true
    VideoUrl:
      type: object
      description: >-
        Canonical Chat Completions video reference. Use a public HTTPS URL or a
        data:video/*;base64,... URL.
      required:
        - url
      properties:
        url:
          type: string
          description: Public HTTPS URL or video base64 data URL.
        detail:
          type: string
          enum:
            - auto
            - low
            - high
        start_offset:
          type: number
          minimum: 0
          description: >-
            Validated segment start; current public text-model routes return
            video_segment_not_supported.
        end_offset:
          type: number
          minimum: 0
          description: >-
            Validated segment end; current public text-model routes return
            video_segment_not_supported.
      additionalProperties: false
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
    AdvisorPhaseBreakdown:
      type: object
      properties:
        executor:
          type: object
          additionalProperties: true
        advisor:
          type: object
          additionalProperties: true
        continuation:
          type: object
          additionalProperties: true
        total:
          type: object
          additionalProperties: true
      additionalProperties: false
    X402PaymentAcceptedOption:
      type: object
      description: Normalized public accountless x402 payment option.
      additionalProperties: true
      properties:
        scheme:
          type: string
          enum:
            - nano
            - nano-exact
            - base-usdc
            - x402-exact
            - x402-solana-usdc
            - lightning-l402
        protocolScheme:
          type: string
        network:
          type: string
        asset:
          type: string
        amount:
          type: string
        amountFormatted:
          type: string
        amountUsd:
          type: string
        payTo:
          type: string
        invoice:
          type: string
          description: >-
            Lightning invoice for lightning-l402 quotes. Same value as payTo for
            most clients.
        paymentHash:
          type: string
          description: Lightning payment hash for lightning-l402 quotes.
        l402Token:
          type: string
          description: >-
            L402 token to pair with the Lightning payment preimage in
            Authorization: L402 <token>:<preimage>.
        discountRate:
          type: number
          description: Discount rate applied to this payment option when present.
        undiscountedAmountUsd:
          type: string
          description: Undiscounted USD quote amount when a discount is applied.
        feePayer:
          type: string
          description: >-
            Solana facilitator fee payer for x402-solana-usdc quotes. Copy from
            the quote; do not hardcode.
        paymentId:
          type: string
        statusUrl:
          type: string
          format: uri
        completeUrl:
          type: string
          format: uri
        expiresAt:
          type: string
          format: date-time
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.