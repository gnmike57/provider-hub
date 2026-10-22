> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Decisions

> Typed choices, scores, and yes/no probabilities from decision models.

## Overview

Decision models answer named, typed questions about the state you provide instead of generating prose:

* `choice` selects one named option and returns a probability for every option.
* `score` returns an expected score over an ordered rubric.
* `noul` returns the probability that a yes/no statement is true.

PPLX Decider v1.1, Clef and Clef Flash can also evaluate images: send up to four photos with your questions and get the same typed answers. See [Image input](#image-input).

For new HTTP integrations, use the native `POST /api/v1/decisions` endpoint. If you already use the official TypeSafe SDK, point it at NanoGPT's `POST /api/v1/systemone` compatibility endpoint. Decision models are also available through NanoGPT's OpenAI-compatible Chat Completions and Responses APIs and the Anthropic-compatible Messages API.

Only input tokens are billed. Browse every decision model, with current pricing, on [nano-gpt.com/models/text?output=decisions](https://nano-gpt.com/models/text?output=decisions).

<Note>
  Decision models work on both API hosts. The text examples use the direct API host, `https://api.nano-gpt.com`; `https://nano-gpt.com` accepts the same requests. See [API Hosts](/api-reference/miscellaneous/api-hosts).

  PPLX Decider v1.1, Clef Flash, image input and `include_usage` are currently available only on `https://nano-gpt.com`. The direct API host does not support them yet and still serves Clef as a 16K text-only model, so the image examples use `https://nano-gpt.com`.
</Note>

<Note>
  Decision models return calibrated probabilities, not generated text. Use a chat model when you need an explanation or other free-form response.
</Note>

## Models

| Model | Context | Images | Use |
| - | - | - | - |
| `typesafe/jev-1.13` | 32K | No | TypeSafe Jev 1.13, pinned for integrations that should not follow alias upgrades. |
| `typesafe/jev-latest` | 32K | No | Moving alias for the latest TypeSafe Jev release. |
| `llmtech/decider-0.8b-fp8` | 32K | No | Mapika's Decider 0.8B, quantized and hosted by LLM Tech. |
| `llmtech/decider-2b-fp8` | 32K | No | Mapika's Decider 2B, quantized and hosted by LLM Tech. |
| `llmtech/decider-4b-nvfp4` | 32K | No | Mapika's Decider 4B, quantized and hosted by LLM Tech. |
| `liquid/d1` | 64K | No | Liquid AI's D1. |
| `perplexity/pplx-decider-v1.1-27b` | 262K | Yes | Perplexity's PPLX Decider v1.1 27B. Supports zero data retention. |
| `cloudflare/clef` | 1,800 text tokens | Yes | Cloudflare's open decision model. |
| `cloudflare/clef-flash` | 1,800 text tokens | Yes | Lower-cost Clef variant. |

Decider IDs are also accepted without the `llmtech/` prefix, and Clef accepts `clef`. The System One compatibility endpoint also accepts the official SDK model names `jev-1.13` and `jev-latest`. In `GET /api/v1/models?detailed=true`, decision models have `architecture.output_modalities: ["decisions"]`, a `supported_endpoints` list, and a `decision_input` object. `decision_input.image_input` is `true` for the image-capable models, and `decision_input.image_limits` lists their limits.

For Clef and Clef Flash, the 1,800-token limit covers all text in the request, including `state` text, `questions` and request overhead. Images are counted separately; see [Image input](#image-input).

## Native Decisions API

### Endpoint

```text theme={null}
POST https://api.nano-gpt.com/api/v1/decisions
```

Authenticate with either `Authorization: Bearer YOUR_API_KEY` or `x-api-key: YOUR_API_KEY`.

### Example request

<CodeGroup>
  ```bash cURL theme={null}
  curl https://api.nano-gpt.com/api/v1/decisions \
    -H "Authorization: Bearer $NANOGPT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "typesafe/jev-1.13",
      "state": {
        "ticket": "I was charged twice and need this fixed before Friday.",
        "customer_tier": "business"
      },
      "questions": {
        "route": {
          "type": "choice",
          "instructions": "Which team should handle this ticket?",
          "criteria": {
            "billing": "Payments, invoices, refunds, or duplicate charges",
            "technical": "Product behavior, bugs, or integrations",
            "sales": "Plans, pricing, or purchasing"
          }
        },
        "urgency": {
          "type": "score",
          "instructions": "How urgent is the ticket?",
          "criteria": [
            "No time pressure",
            "Can wait several days",
            "Needs attention within one business day",
            "Immediate action is required"
          ]
        },
        "needs_human_review": {
          "type": "noul",
          "instructions": "Does this ticket need human review?",
          "criteria": {
            "true": "A person should review the case",
            "false": "Automation can safely handle the case"
          }
        }
      },
      "user": "customer_123"
    }'
  ```

  ```javascript JavaScript theme={null}
  const response = await fetch("https://api.nano-gpt.com/api/v1/decisions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.NANOGPT_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "typesafe/jev-1.13",
      state: {
        ticket: "I was charged twice and need this fixed before Friday.",
        customer_tier: "business",
      },
      questions: {
        route: {
          type: "choice",
          instructions: "Which team should handle this ticket?",
          criteria: {
            billing: "Payments, invoices, refunds, or duplicate charges",
            technical: "Product behavior, bugs, or integrations",
            sales: "Plans, pricing, or purchasing",
          },
        },
        urgency: {
          type: "score",
          instructions: "How urgent is the ticket?",
          criteria: [
            "No time pressure",
            "Can wait several days",
            "Needs attention within one business day",
            "Immediate action is required",
          ],
        },
        needs_human_review: {
          type: "noul",
          instructions: "Does this ticket need human review?",
          criteria: {
            true: "A person should review the case",
            false: "Automation can safely handle the case",
          },
        },
      },
      user: "customer_123",
    }),
  });

  if (!response.ok) throw new Error(await response.text());
  const decision = await response.json();
  console.log(decision.answers);
  ```

  ```python Python theme={null}
  import os
  import requests

  response = requests.post(
      "https://api.nano-gpt.com/api/v1/decisions",
      headers={
          "Authorization": f"Bearer {os.environ['NANOGPT_API_KEY']}",
          "Content-Type": "application/json",
      },
      json={
          "model": "typesafe/jev-1.13",
          "state": {
              "ticket": "I was charged twice and need this fixed before Friday.",
              "customer_tier": "business",
          },
          "questions": {
              "route": {
                  "type": "choice",
                  "instructions": "Which team should handle this ticket?",
                  "criteria": {
                      "billing": "Payments, invoices, refunds, or duplicate charges",
                      "technical": "Product behavior, bugs, or integrations",
                      "sales": "Plans, pricing, or purchasing",
                  },
              },
              "urgency": {
                  "type": "score",
                  "instructions": "How urgent is the ticket?",
                  "criteria": [
                      "No time pressure",
                      "Can wait several days",
                      "Needs attention within one business day",
                      "Immediate action is required",
                  ],
              },
              "needs_human_review": {
                  "type": "noul",
                  "instructions": "Does this ticket need human review?",
                  "criteria": {
                      "true": "A person should review the case",
                      "false": "Automation can safely handle the case",
                  },
              },
          },
          "user": "customer_123",
      },
      timeout=30,
  )
  response.raise_for_status()
  print(response.json()["answers"])
  ```
</CodeGroup>

### Example response

```json theme={null}
{
  "id": "decision_...",
  "model": "typesafe/jev-1.13",
  "answers": {
    "route": {
      "type": "choice",
      "choice": "billing",
      "confidence": 0.97,
      "probabilities": {
        "billing": 0.97,
        "technical": 0.02,
        "sales": 0.01
      }
    },
    "urgency": {
      "type": "score",
      "score": 2.63,
      "confidence": 0.81,
      "legend": {
        "0": "No time pressure",
        "1": "Can wait several days",
        "2": "Needs attention within one business day",
        "3": "Immediate action is required"
      },
      "probabilities": {
        "0": 0.01,
        "1": 0.05,
        "2": 0.24,
        "3": 0.70
      }
    },
    "needs_human_review": {
      "type": "noul",
      "noul": 0.84
    }
  },
  "usage": {
    "input_tokens": 126,
    "output_tokens": 8,
    "estimated_cost": 0.000005292
  }
}
```

`noul` is the probability of the `true` outcome. A `score` can be fractional because it is the expected value across the returned score distribution.

### Usage and cost

Every response reports `usage.input_tokens` and `usage.output_tokens`. Only input tokens are billed; output tokens are free.

By default, the response is returned as soon as the answers are ready, and billing settles immediately afterwards. The charge itself is unaffected. These responses report `usage.estimated_cost`: the model's published input price for the reported input tokens, in USD. It does not include account discounts or payment-currency conversion, so your actual charge can differ.

To get the exact amount charged instead, send `"include_usage": true`. The response then waits for billing to settle and reports the exact charge, in USD, as `usage.cost` instead of `usage.estimated_cost`. This adds a little latency. Your usage history always shows the exact charge.

```json theme={null}
"usage": {
  "input_tokens": 126,
  "output_tokens": 8,
  "cost": 0.000005027
}
```

### Image input

`perplexity/pplx-decider-v1.1-27b`, `cloudflare/clef` and `cloudflare/clef-flash` accept images on the native `POST /api/v1/decisions` endpoint and the `POST /api/v1/systemone` compatibility endpoint. Use them to classify photos, score visual content, or answer yes/no questions about an image.

Make `state` an array, and put each image directly in it as an `image_url` part with a base64 data URL. Plain strings in the same array add text context. The optional `image_url.detail` field accepts `auto`, `low` or `high`.

<CodeGroup>
  ```bash cURL theme={null}
  IMAGE=$(base64 < return-photo.jpg | tr -d '\n')

  curl https://nano-gpt.com/api/v1/decisions \
    -H "Authorization: Bearer $NANOGPT_API_KEY" \
    -H "Content-Type: application/json" \
    -d @- <<EOF
  {
    "model": "perplexity/pplx-decider-v1.1-27b",
    "state": [
      "Return claim photo.",
      { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,$IMAGE" } }
    ],
    "questions": {
      "condition": {
        "type": "choice",
        "instructions": "What condition is the returned item in?",
        "criteria": {
          "like_new": "No visible wear",
          "used": "Normal signs of use",
          "damaged": "Cracked, broken or missing parts"
        }
      },
      "screen_cracked": {
        "type": "noul",
        "instructions": "Is the screen cracked?"
      }
    }
  }
  EOF
  ```

  ```javascript JavaScript theme={null}
  import { readFile } from "node:fs/promises";

  const image = (await readFile("return-photo.jpg")).toString("base64");

  const response = await fetch("https://nano-gpt.com/api/v1/decisions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.NANOGPT_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "perplexity/pplx-decider-v1.1-27b",
      state: [
        "Return claim photo.",
        { type: "image_url", image_url: { url: `data:image/jpeg;base64,${image}` } },
      ],
      questions: {
        condition: {
          type: "choice",
          instructions: "What condition is the returned item in?",
          criteria: {
            like_new: "No visible wear",
            used: "Normal signs of use",
            damaged: "Cracked, broken or missing parts",
          },
        },
        screen_cracked: {
          type: "noul",
          instructions: "Is the screen cracked?",
        },
      },
    }),
  });

  if (!response.ok) throw new Error(await response.text());
  console.log((await response.json()).answers);
  ```

  ```python Python theme={null}
  import base64
  import os
  import requests

  with open("return-photo.jpg", "rb") as f:
      image = base64.b64encode(f.read()).decode()

  response = requests.post(
      "https://nano-gpt.com/api/v1/decisions",
      headers={"Authorization": f"Bearer {os.environ['NANOGPT_API_KEY']}"},
      json={
          "model": "perplexity/pplx-decider-v1.1-27b",
          "state": [
              "Return claim photo.",
              {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
          ],
          "questions": {
              "condition": {
                  "type": "choice",
                  "instructions": "What condition is the returned item in?",
                  "criteria": {
                      "like_new": "No visible wear",
                      "used": "Normal signs of use",
                      "damaged": "Cracked, broken or missing parts",
                  },
              },
              "screen_cracked": {
                  "type": "noul",
                  "instructions": "Is the screen cracked?",
              },
          },
      },
      timeout=30,
  )
  response.raise_for_status()
  print(response.json()["answers"])
  ```
</CodeGroup>

To compare several images, put a label before each one, for example `["Photo 1", image1, "Photo 2", image2]`, and refer to the labels in your question criteria.

| Limit | Value |
| - | - |
| Images per request | Up to 4 |
| Formats | Static PNG, JPEG or WebP, sent inline as base64 data URLs. Remote image URLs are not fetched, and animated images are rejected. |
| Dimensions | Each image at most 512 × 512 pixels |
| Size | All images together at most 240,000 base64 characters (180,000 decoded bytes); the whole JSON body at most 1 MiB |
| Questions | Up to 128 per request |
| Text | Clef and Clef Flash: at most 1,800 text tokens, including questions and request overhead |

Images are billed as input tokens at the model's normal input price; `usage.input_tokens` includes them. Resize larger photos before sending them.

Privacy rules for image requests:

* PPLX Decider v1.1 supports zero data retention: set `provider.zdr` to `true`, or use an API key with a ZDR policy.
* Clef and Clef Flash do not support zero data retention. On these models, requests that require ZDR, and image requests with `provider.data_collection: "deny"`, return `400`.
* Image input cannot be combined with PII redaction.

Image errors use these codes:

| Status | Code | Meaning |
| - | - | - |
| 400 | `invalid_image` | The image is not a valid static PNG, JPEG or WebP data URL, or it is not placed directly in the `state` array. |
| 400 | `unsupported_modality` | The model does not accept images, or the requested privacy settings are not available for image input. |
| 413 | `image_too_large` | An image, or all images together, exceed the limits above. A JSON body over 1 MiB returns `413 request_body_too_large`. |
| 400 | `context_length_exceeded` | The text and images exceed the model's input limit. |

The Chat Completions, Responses and Messages compatibility endpoints accept text only.

## Question types

| Type | Required fields | Answer |
| - | - | - |
| `choice` | `instructions` and a non-empty `criteria` object | `choice`, `confidence`, and `probabilities` keyed by the supplied labels |
| `score` | `instructions` and 2-10 ordered `criteria` entries | Fractional `score`, `confidence`, `legend`, and `probabilities` keyed from `0` |
| `noul` | `instructions`; optional `criteria.true` and `criteria.false` descriptions | `noul`, a probability from `0` to `1` |

`instructions` and criterion descriptions can be strings, non-empty JSON objects, or non-empty arrays. A `choice` criterion may also be `null` when its label is self-explanatory. The top-level `state` can be a string, JSON object, or JSON array. Question names become keys in `answers`.

## Model-specific rules

| Rule | Applies to |
| - | - |
| Choice questions need 2-255 options and Score questions 2-10 levels. A request can contain at most 1,024 scoring rows (otherwise `413 too_many_questions`). | Decider |
| `isolated` on a Score question (default `true`) evaluates each level as its own row, repeating the instructions per level. Set `false` to evaluate the question as one row. | Decider |
| A Noul question may omit `instructions` when `criteria.true` or `criteria.false` describes the answer. | Decider |
| Noul questions need `instructions`, and `criteria` needs both `true` and `false` when it is sent. | Jev, Liquid D1, PPLX Decider v1.1, Clef, Clef Flash |
| A request can contain at most 128 questions. | PPLX Decider v1.1, Clef, Clef Flash |
| Text input, including questions and request overhead, is limited to 1,800 tokens. | Clef, Clef Flash |

## Request fields

| Field | Type | Required | Description |
| - | - | -: | - |
| `model` | string | Yes | A decision model from the table above. |
| `state` | string, object, or array | Yes | Application state for the model to evaluate. Image-capable models also accept image parts in a `state` array; see [Image input](#image-input). |
| `questions` | object | Yes | One or more named `choice`, `score`, or `noul` questions. |
| `user` | string | No | Your end-user identifier, up to 256 characters. |
| `session_id` | string | No | Your session identifier, up to 256 characters. |
| `trace` | object | No | Caller-supplied trace metadata. |
| `independent` | boolean | No | Decider only. Decider always evaluates questions independently, so send `true` or omit it; other models reject the field. |
| `provider` | object or null | No | Native Decisions routing controls. Usually omit this field. |
| `include_usage` | boolean | No | Wait for billing to settle and report the exact charge as `usage.cost`. Defaults to `false`, which returns `usage.estimated_cost` without waiting. See [Usage and cost](#usage-and-cost). |

The native `provider` object can contain endpoint-level `order`, `only`, `ignore`, `allow_fallbacks`, `require_parameters`, `max_price`, `zdr`, and `data_collection` controls. These names describe native Decisions endpoints such as `TypeSafe`; they are not NanoGPT provider IDs. API-key provider restrictions and zero-data-retention requirements still apply. Decider, PPLX Decider v1.1, Clef and Clef Flash use fixed decision endpoints and accept only `zdr` and `data_collection`. Clef and Clef Flash reject `zdr: true`.

## Official TypeSafe SDK

NanoGPT exposes `POST /api/v1/systemone` so the official TypeSafe JavaScript and Python SDKs can call any decision model without changing their request types. Set the model to `jev-latest`, `jev-1.13`, `decider-2b-fp8` (or another Decider), `liquid/d1`, `perplexity/pplx-decider-v1.1-27b`, `clef` or `cloudflare/clef-flash`. Image input and `include_usage` work the same way as on the native endpoint.

<CodeGroup>
  ```typescript JavaScript / TypeScript theme={null}
  // npm install @typesafe-ai/sdk
  import { choice, TypeSafeClient } from "@typesafe-ai/sdk";

  const client = new TypeSafeClient({
    apiKey: process.env.NANOGPT_API_KEY!,
    baseURL: "https://api.nano-gpt.com/api",
    defaultModel: "jev-latest",
  });

  const result = await client.systemOne({
    state: { ticket: "I was charged twice. Please fix this." },
    questions: {
      route: choice("Which team should handle this ticket?", {
        billing: null,
        technical: null,
        sales: null,
      }),
    },
  });

  console.log(result.answers.route.choice);
  ```

  ```python Python theme={null}
  # pip install typesafe-sdk
  import os
  from typesafe_sdk import Choice, TypeSafeClient

  with TypeSafeClient(
      api_key=os.environ["NANOGPT_API_KEY"],
      base_url="https://api.nano-gpt.com/api",
      model="jev-latest",
  ) as client:
      result = client.system_one(
          state={"ticket": "I was charged twice. Please fix this."},
          questions={
              "route": Choice(
                  instructions="Which team should handle this ticket?",
                  criteria={
                      "billing": None,
                      "technical": None,
                      "sales": None,
                  },
              ),
          },
      )

  print(result.choices["route"].choice)
  ```
</CodeGroup>

<Warning>
  The SDK's System One call is supported. The SDK's model-list method is not, because NanoGPT's `/api/v1/models` response uses the NanoGPT/OpenAI-compatible model-list shape rather than TypeSafe's model-list shape.
</Warning>

## OpenAI and Anthropic compatibility

Use these shapes when a decision model must fit into an existing OpenAI- or Anthropic-compatible client. The answer object is returned as JSON text, so parse the returned string once.

Chat Completions and Responses report `usage.estimated_cost` by default. To get the exact charge as `usage.cost`, send `"include_usage": true` or `"stream_options": {"include_usage": true}`. Messages responses always report the exact charge.

### Chat Completions

```bash theme={null}
curl https://api.nano-gpt.com/api/v1/chat/completions \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "typesafe/jev-latest",
    "messages": [
      {"role": "user", "content": "I was charged twice. Please fix this."}
    ],
    "stream": false,
    "response_format": {
      "type": "questions",
      "questions": {
        "billing": {
          "type": "noul",
          "instructions": "Is this request about billing?"
        }
      }
    }
  }'
```

Parse `choices[0].message.content` as JSON.

### Responses API

```bash theme={null}
curl https://api.nano-gpt.com/api/v1/responses \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "typesafe/jev-latest",
    "input": "I was charged twice. Please fix this.",
    "stream": false,
    "store": false,
    "text": {
      "format": {
        "type": "questions",
        "questions": {
          "billing": {
            "type": "noul",
            "instructions": "Is this request about billing?"
          }
        }
      }
    }
  }'
```

Parse `output_text` as JSON. The same JSON text is also available in the assistant output item.

### Anthropic Messages

```bash theme={null}
curl https://api.nano-gpt.com/api/v1/messages \
  -H "x-api-key: $NANOGPT_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "typesafe/jev-latest",
    "max_tokens": 128,
    "messages": [
      {"role": "user", "content": "I was charged twice. Please fix this."}
    ],
    "stream": false,
    "output_config": {
      "format": {
        "type": "questions",
        "questions": {
          "billing": {
            "type": "noul",
            "instructions": "Is this request about billing?"
          }
        }
      }
    }
  }'
```

Parse `content[0].text` as JSON. `max_tokens` is accepted for Anthropic SDK compatibility but does not change the fixed typed output.

## Limitations

Decision-model requests are deliberately narrower than chat generation requests:

* Only non-streaming text input in `user` messages is supported on compatibility endpoints. Image input is available only on the native Decisions and System One endpoints, for PPLX Decider v1.1, Clef and Clef Flash.
* System, developer, assistant, tool, audio, video, and file input is not supported. Compatibility endpoints also reject images.
* Tools, sampling controls, log probabilities, and reasoning generation controls are not supported.
* Output-token-limit fields are accepted where an SDK requires them, but they do not change the fixed typed output.
* BYOK and accountless x402 payments are not supported.
* Standard NanoGPT or `X-Provider` provider pins are not supported. Use the native Decisions `provider` object only when you need endpoint-level routing controls.

Unsupported combinations return a `400` error instead of being silently ignored.


## OpenAPI

````yaml POST /v1/decisions
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
  /v1/decisions:
    post:
      tags:
        - Decisions
      summary: Create typed decisions with a decision model
      description: >-
        Evaluates application state with one or more typed Choice, Score, or
        Noul (yes/no) questions. Decision models return typed answers with
        calibrated probabilities instead of generated text, and only input
        tokens are billed. Supported models: TypeSafe Jev (typesafe/jev-1.13,
        typesafe/jev-latest), Mapika's Decider hosted by LLM Tech
        (llmtech/decider-0.8b-fp8, llmtech/decider-2b-fp8,
        llmtech/decider-4b-nvfp4), Liquid AI's D1 (liquid/d1), Perplexity's PPLX
        Decider v1.1 (perplexity/pplx-decider-v1.1-27b), and Cloudflare's Clef
        (cloudflare/clef) and Clef Flash (cloudflare/clef-flash). Decider needs
        2-255 Choice options or 2-10 Score levels per question and allows at
        most 1,024 scoring rows per request. Decider, PPLX Decider v1.1, Clef
        and Clef Flash accept only the zdr and data_collection routing controls
        in provider. PPLX Decider v1.1, Clef and Clef Flash also accept up to
        four inline images in the state array; Clef and Clef Flash limit text
        input to 1,800 tokens. By default the response returns before billing
        settles and reports usage.estimated_cost; set include_usage to true for
        the exact usage.cost. PPLX Decider v1.1, Clef Flash, image input and
        include_usage are currently available on https://nano-gpt.com only.
      operationId: createDecision
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DecisionsRequest'
      responses:
        '200':
          description: Typed decisions response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DecisionsResponse'
        '400':
          description: Invalid state, questions, model, or unsupported parameter
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DecisionsError'
        '401':
          description: Missing or invalid API key
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DecisionsError'
        '429':
          description: Rate limit exceeded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DecisionsError'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    DecisionsRequest:
      type: object
      additionalProperties: false
      required:
        - model
        - state
        - questions
      properties:
        model:
          type: string
          description: >-
            Decision model ID. Bare Decider IDs and clef are aliases of the
            prefixed IDs.
          enum:
            - typesafe/jev-1.13
            - ~typesafe/jev-latest
            - typesafe/jev-latest
            - llmtech/decider-0.8b-fp8
            - llmtech/decider-2b-fp8
            - llmtech/decider-4b-nvfp4
            - decider-0.8b-fp8
            - decider-2b-fp8
            - decider-4b-nvfp4
            - liquid/d1
            - cloudflare/clef
            - clef
            - cloudflare/clef-flash
            - perplexity/pplx-decider-v1.1-27b
        state:
          description: >-
            Application state to evaluate. On https://nano-gpt.com, PPLX Decider
            v1.1, Clef and Clef Flash also accept an array that mixes plain
            strings with up to four image_url parts holding static PNG, JPEG or
            WebP base64 data URLs, each at most 512x512 pixels (240,000 base64
            characters in total). Remote image URLs are not fetched.
          oneOf:
            - type: string
            - type: object
              additionalProperties: true
            - type: array
              items: {}
        questions:
          type: object
          minProperties: 1
          additionalProperties:
            oneOf:
              - $ref: '#/components/schemas/DecisionsChoiceQuestion'
              - $ref: '#/components/schemas/DecisionsScoreQuestion'
              - $ref: '#/components/schemas/DecisionsNoulQuestion'
        independent:
          type: boolean
          const: true
          description: >-
            Decider only. Decider always evaluates questions independently, so
            send true or omit the field; other models reject it.
        provider:
          description: >-
            Optional native Decisions endpoint-routing controls. These are not
            NanoGPT provider IDs. Decider, PPLX Decider v1.1, Clef and Clef
            Flash accept only zdr and data_collection; Clef and Clef Flash
            reject zdr true.
          type:
            - object
            - 'null'
          additionalProperties: true
        session_id:
          type: string
          maxLength: 256
        trace:
          type: object
          additionalProperties: true
        user:
          type: string
          maxLength: 256
        include_usage:
          type: boolean
          default: false
          description: >-
            Wait for billing to settle and report the exact charge as
            usage.cost. By default the response returns without waiting and
            reports usage.estimated_cost. Available on https://nano-gpt.com.
    DecisionsResponse:
      type: object
      required:
        - model
        - answers
        - usage
      properties:
        id:
          type: string
        model:
          type: string
        answers:
          type: object
          additionalProperties:
            oneOf:
              - $ref: '#/components/schemas/DecisionsChoiceAnswer'
              - $ref: '#/components/schemas/DecisionsScoreAnswer'
              - $ref: '#/components/schemas/DecisionsNoulAnswer'
        usage:
          type: object
          required:
            - input_tokens
            - output_tokens
          properties:
            input_tokens:
              type: integer
              minimum: 0
            output_tokens:
              type: integer
              minimum: 0
            cost:
              type: number
              minimum: 0
              description: >-
                Exact charge in USD. Returned when the request sets
                include_usage to true.
            estimated_cost:
              type: number
              minimum: 0
              description: >-
                Estimated charge in USD at the model's published input price for
                the reported input tokens, before account discounts and
                payment-currency conversion. Returned when include_usage is not
                set; billing settles right after the response.
    DecisionsError:
      type: object
      required:
        - error
      properties:
        error:
          type: object
          required:
            - message
            - type
            - code
          properties:
            message:
              type: string
            type:
              type: string
            code:
              type: string
            param:
              type: string
    DecisionsChoiceQuestion:
      type: object
      required:
        - type
        - instructions
        - criteria
      properties:
        type:
          type: string
          const: choice
        instructions:
          $ref: '#/components/schemas/DecisionsStructuredDescription'
        criteria:
          type: object
          minProperties: 1
          additionalProperties:
            oneOf:
              - $ref: '#/components/schemas/DecisionsStructuredDescription'
              - type: 'null'
    DecisionsScoreQuestion:
      type: object
      required:
        - type
        - instructions
        - criteria
      properties:
        type:
          type: string
          const: score
        instructions:
          $ref: '#/components/schemas/DecisionsStructuredDescription'
        isolated:
          type: boolean
          description: >-
            Decider only. When true or omitted, each Score level is evaluated as
            its own row: the question's instructions are repeated per level
            (more input tokens) and every level counts toward the 1,024-row
            limit. Set false to evaluate the question as one row.
        criteria:
          type: array
          minItems: 2
          maxItems: 10
          items:
            $ref: '#/components/schemas/DecisionsStructuredDescription'
    DecisionsNoulQuestion:
      description: >-
        A yes/no question. Jev, Liquid D1 and Clef require instructions and,
        when criteria is sent, both true and false descriptions. Decider also
        accepts a question without instructions (omitted, null or empty) when
        criteria.true or criteria.false describes the answer.
      type: object
      required:
        - type
      anyOf:
        - required:
            - instructions
          properties:
            instructions:
              $ref: '#/components/schemas/DecisionsStructuredDescription'
        - required:
            - criteria
          properties:
            criteria:
              anyOf:
                - required:
                    - 'true'
                  properties:
                    'true':
                      $ref: '#/components/schemas/DecisionsStructuredDescription'
                - required:
                    - 'false'
                  properties:
                    'false':
                      $ref: '#/components/schemas/DecisionsStructuredDescription'
      properties:
        type:
          type: string
          const: noul
        instructions:
          oneOf:
            - $ref: '#/components/schemas/DecisionsStructuredDescription'
            - type: 'null'
            - type: string
              maxLength: 0
        criteria:
          type: object
          minProperties: 1
          properties:
            'true':
              oneOf:
                - $ref: '#/components/schemas/DecisionsStructuredDescription'
                - type: 'null'
            'false':
              oneOf:
                - $ref: '#/components/schemas/DecisionsStructuredDescription'
                - type: 'null'
    DecisionsChoiceAnswer:
      type: object
      required:
        - type
        - choice
        - confidence
        - probabilities
      properties:
        type:
          type: string
          const: choice
        choice:
          type: string
        confidence:
          type: number
          minimum: 0
          maximum: 1
        probabilities:
          type: object
          additionalProperties:
            type: number
            minimum: 0
            maximum: 1
    DecisionsScoreAnswer:
      type: object
      required:
        - type
        - score
        - confidence
        - legend
        - probabilities
      properties:
        type:
          type: string
          const: score
        score:
          type: number
          minimum: 0
        confidence:
          type: number
          minimum: 0
          maximum: 1
        legend:
          type: object
          additionalProperties: true
        probabilities:
          type: object
          additionalProperties:
            type: number
            minimum: 0
            maximum: 1
    DecisionsNoulAnswer:
      type: object
      required:
        - type
        - noul
      properties:
        type:
          type: string
          const: noul
        noul:
          type: number
          minimum: 0
          maximum: 1
    DecisionsStructuredDescription:
      description: >-
        A non-empty string, JSON object, or JSON array used to describe a
        question or outcome.
      oneOf:
        - type: string
          minLength: 1
        - type: object
          minProperties: 1
          additionalProperties: true
        - type: array
          minItems: 1
          items: {}
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