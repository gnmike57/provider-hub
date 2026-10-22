> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Context Memory (Standalone)

> Compress a conversation with Context Memory and return compressed messages and usage (no model inference)

## Overview

The standalone Context Memory endpoint compresses an entire conversation into a single memory message. This endpoint does not run a model. It returns the compressed memory message and usage so you can pipe it into your own chat completion request or store it.

* No model inference is performed
* Pass your `messages` array and optional settings

## Authentication

* `Authorization: Bearer YOUR_API_KEY` or
* `x-api-key: YOUR_API_KEY`

## Request

### Headers

* `Content-Type: application/json`
* `Authorization: Bearer YOUR_API_KEY` or `x-api-key: YOUR_API_KEY`
* `memory_expiration_days: <1..365>` (optional) — overrides body; defaults to 30

### Body

```json theme={null}
{
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "Summarize our previous discussion and continue." }
  ],
  "expiration_days": 45,            
  "model_context_limit": 128000     
}
```

* `messages` (required): OpenAI-style messages. `user`, `assistant`, `system`, `tool`, and `function` roles are accepted. Assistant `tool_calls` are ignored during compression.
* `expiration_days` (optional): 1..365; default 30. If both header and body are provided, the header takes precedence.
* `model_context_limit` (optional): Context target for compression. Default 128k; values below 10k are clamped internally.

## Response

### Success (200)

```json theme={null}
{
  "messages": [
    { "role": "system", "content": "<compressed-context>..." }
  ],
  "usage": {
    "prompt_tokens": 51234,
    "completion_tokens": 1234,
    "total_tokens": 52468,
    "prompt_tokens_details": {
      "cached_tokens": 4096
    }
  }
}
```

* `messages`: The single memory-compressed message array to use as your full context in a chat completion request
* `usage`: Token usage. When available, `prompt_tokens_details.cached_tokens` indicates discounted cached input tokens

### Error Examples

```json 400 Bad Request theme={null}
{ "error": "messages must be a non-empty array" }
```

```json 401 Unauthorized theme={null}
{ "error": "Invalid session" }
```

```json 402 Payment Required theme={null}
{ "error": "Insufficient balance" }
```

```json 429 Too Many Requests theme={null}
{ "error": "Rate limit exceeded. Please wait before sending another request." }
```

## Pricing & Billing

* Non-cached input tokens: \$5.00 / 1M
* Cached input tokens: \$2.50 / 1M (when applicable)
* Output tokens: \$10.00 / 1M

Note: This endpoint only charges for memory compression. If you later call `/v1/chat/completions`, model costs are billed separately.

## Retention

* Default retention: 30 days
* Configure via body `expiration_days` or header `memory_expiration_days`
* Header value takes precedence over body when both are supplied

## Examples

<CodeGroup>
  ```javascript JavaScript theme={null}
  const res = await fetch('https://api.nano-gpt.com/api/v1/memory', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer YOUR_API_KEY',
      'Content-Type': 'application/json',
      'memory_expiration_days': '45'
    },
    body: JSON.stringify({
      messages: [
        { role: 'system', content: 'You are a helpful assistant.' },
        { role: 'user', content: 'Optimize our previous plan and continue.' }
      ]
    })
  });

  const { messages, usage } = await res.json();
  // Use `messages` as the full context for a subsequent /v1/chat/completions call
  ```

  ```python Python theme={null}
  import requests

  url = 'https://api.nano-gpt.com/api/v1/memory'
  headers = {
      'Authorization': 'Bearer YOUR_API_KEY',
      'Content-Type': 'application/json'
  }

  data = {
      'messages': [
          { 'role': 'system', 'content': 'You are a helpful assistant.' },
          { 'role': 'user', 'content': 'Summarize and continue.' }
      ],
      'expiration_days': 30,
      'model_context_limit': 128000
  }

  r = requests.post(url, headers=headers, json=data)
  result = r.json()
  print(result['messages'][0]['content'][:200])
  print(result['usage'])
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/v1/memory \
    -H "Authorization: Bearer YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -H "memory_expiration_days: 90" \
    -d '{
      "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Compress our conversation and continue."}
      ]
    }'
  ```
</CodeGroup>


## OpenAPI

````yaml POST /v1/memory
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
  /v1/memory:
    post:
      description: >-
        Compress a conversation with Context Memory and return compressed
        messages and usage (no model inference)
      requestBody:
        description: Parameters for memory compression
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/MemoryRequest'
      responses:
        '200':
          description: Memory compression response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MemoryResponse'
        '400':
          description: Bad Request - Missing or invalid messages
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '402':
          description: Payment Required - Insufficient balance
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '429':
          description: Too Many Requests - Rate limit exceeded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    MemoryRequest:
      type: object
      required:
        - messages
      properties:
        messages:
          type: array
          description: OpenAI-style messages array to compress
          items:
            type: object
            properties:
              role:
                type: string
                enum:
                  - system
                  - user
                  - assistant
                  - tool
                  - function
              content:
                oneOf:
                  - type: string
                  - type: array
            required:
              - role
              - content
        expiration_days:
          type: integer
          description: Retention in days (1..365). Defaults to 30 if not provided.
          minimum: 1
          maximum: 365
          default: 30
        model_context_limit:
          type: integer
          description: Target context size for compression (minimum enforced 10,000)
          default: 128000
    MemoryResponse:
      type: object
      required:
        - messages
        - usage
      properties:
        messages:
          type: array
          description: Compressed memory message array
          items:
            type: object
            properties:
              role:
                type: string
              content:
                type: string
            required:
              - role
              - content
        usage:
          type: object
          properties:
            prompt_tokens:
              type: integer
            completion_tokens:
              type: integer
            total_tokens:
              type: integer
            prompt_tokens_details:
              type: object
              properties:
                cached_tokens:
                  type: integer
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