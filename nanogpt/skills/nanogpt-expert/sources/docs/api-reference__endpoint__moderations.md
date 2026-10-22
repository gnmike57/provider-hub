> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Moderations

> Classify text and image content for safety

## Overview

Use `POST /api/v1/moderations` to classify text, image, or mixed content for safety before you store, display, or send user-generated content to another model endpoint.

If you want NanoGPT to run a paid input safety preflight automatically before supported generation requests, use [Inline Moderation](/api-reference/miscellaneous/inline-moderation) instead.

The endpoint is synchronous and returns an OpenAI-compatible moderation response shape where practical. It is a paid API feature and bills proportionally to usage with no separate minimum charge.

## Endpoint

```text theme={null}
POST https://api.nano-gpt.com/api/v1/moderations
```

## Authentication

An API key is required.

* `Authorization: Bearer YOUR_API_KEY`
* `x-api-key: YOUR_API_KEY`

## Model Selection

The `model` field is optional. If omitted, NanoGPT uses the default moderation model.

Available input types, batch support, context limits, and pricing depend on the selected model. Use [Moderation Models](/api-reference/endpoint/moderation-models) before choosing a model instead of hardcoding capabilities.

## Request Body

| Field | Type | Required | Description |
| - | - | - | - |
| `model` | string | No | Moderation model ID. Omit to use the default moderation model. |
| `input` | string, array, or content parts | Yes | Content to classify. |

## Input Examples

### Single Text Input

```json theme={null}
{
  "model": "moderation-model-id",
  "input": "Text to classify."
}
```

### Batch Text Input

```json theme={null}
{
  "model": "moderation-model-id",
  "input": [
    "First item to classify.",
    "Second item to classify."
  ]
}
```

Batch support can vary by model. If a selected model does not support batched input, the API returns an error before billing.

### Text Content Part

```json theme={null}
{
  "model": "moderation-model-id",
  "input": [
    {
      "type": "text",
      "text": "Text to classify."
    }
  ]
}
```

### Image Input

```json theme={null}
{
  "model": "moderation-model-id",
  "input": [
    {
      "type": "image_url",
      "image_url": {
        "url": "https://example.com/image.png"
      }
    }
  ]
}
```

Image support depends on the selected model. Text-only models reject image input before billing.

## Example

```bash theme={null}
curl https://api.nano-gpt.com/api/v1/moderations \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "moderation-model-id",
    "input": "Text to classify for safety."
  }'
```

## Response

```json theme={null}
{
  "id": "modr_...",
  "model": "moderation-model-id",
  "results": [
    {
      "flagged": false,
      "categories": {
        "category_name": false
      },
      "category_scores": {
        "category_name": 0.01
      }
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 100,
    "total_tokens": 112
  }
}
```

| Field | Description |
| - | - |
| `flagged` | `true` when the selected model classifies the content as unsafe. |
| `categories` | Category-level boolean results. Exact category names are model-dependent. |
| `category_scores` | Category-level confidence scores when available. Exact category names are model-dependent. |
| `usage` | Token usage used for billing and diagnostics. |

## Billing

The endpoint is paid and bills proportionally to usage. There is no extra minimum charge.

General billing behavior:

* Input tokens are billed according to the selected moderation model's input rate.
* Output tokens may be billed when the selected model returns billable classification output.
* NanoGPT performs a preflight balance check before dispatching the request.
* The final charge is based on measured or estimated usage recorded for the completed request.
* Pricing details are returned by `GET /api/v1/moderation-models`.

## Rate Limits And Access Controls

The endpoint uses standard NanoGPT API authentication, balance checks, API-key limits, and account/team access controls.

* API keys can be subject to model allowlists.
* API keys can be subject to spending and token limits.
* Team billing and team restrictions apply where configured.
* Requests can be rate limited.

## Errors

Errors follow the standard NanoGPT/OpenAI-compatible error shape:

```json theme={null}
{
  "error": {
    "message": "Invalid request parameters. Please check your input and try again.",
    "type": "invalid_request_error",
    "code": "unsupported_input_modality",
    "param": "input"
  }
}
```

| Status | Code | Meaning |
| - | - | - |
| 400 | `empty_input` | The request did not include moderatable text or image content. |
| 400 | `unsupported_input_modality` | The selected model does not support the submitted input type. |
| 400 | `unsupported_batch_input` | The selected model does not support batched input. |
| 400 | `context_length_exceeded` | The input is too large for the selected model. |
| 401 | `missing_api_key` or `invalid_api_key` | Authentication failed. |
| 402 | varies | The account does not have enough balance. |
| 403 | `paid_features_disabled` | Paid API features are disabled for the account. |
| 404 | `model_not_found` | The requested moderation model does not exist or is unavailable. |
| 429 | `rate_limit_exceeded` | The caller exceeded a rate limit. |
| 503 | `provider_error` or similar | The upstream moderation service was temporarily unavailable or returned an invalid response. |


## OpenAPI

````yaml POST /v1/moderations
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
  /v1/moderations:
    post:
      description: Classify text, image, or mixed content for safety
      requestBody:
        description: Parameters for creating a moderation classification
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ModerationRequest'
        required: true
      responses:
        '200':
          description: Moderation classification response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationResponse'
        '400':
          description: >-
            Bad Request - Missing input, unsupported modality, unsupported batch
            input, or context length exceeded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationErrorResponse'
        '401':
          description: Unauthorized - Invalid or missing API key
        '402':
          description: Payment Required - Insufficient balance
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationErrorResponse'
        '403':
          description: Forbidden - Paid API features are disabled for the account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationErrorResponse'
        '404':
          description: Model not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationErrorResponse'
        '429':
          description: Rate limit exceeded
        '503':
          description: >-
            Upstream moderation service unavailable or returned an invalid
            response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationErrorResponse'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    ModerationRequest:
      type: object
      required:
        - input
      properties:
        model:
          type: string
          description: Moderation model ID. Omit to use the default moderation model.
          example: moderation-model-id
        input:
          description: Content to classify
          oneOf:
            - type: string
              description: Single text string to classify
              example: Text to classify for safety.
            - type: array
              description: >-
                Array of text strings or content parts to classify. Batch
                support and supported modalities depend on the selected model.
              items:
                oneOf:
                  - type: string
                  - $ref: '#/components/schemas/ModerationTextContentPart'
                  - $ref: '#/components/schemas/ModerationImageContentPart'
              minItems: 1
    ModerationResponse:
      type: object
      required:
        - id
        - model
        - results
      properties:
        id:
          type: string
          description: Moderation request identifier
          example: modr_...
        model:
          type: string
          description: Moderation model used for classification
          example: moderation-model-id
        results:
          type: array
          description: Moderation results for each classified input
          items:
            type: object
            required:
              - flagged
              - categories
            properties:
              flagged:
                type: boolean
                description: Whether the selected model classified the content as unsafe
                example: false
              categories:
                type: object
                description: Model-dependent category-level boolean results
                additionalProperties:
                  type: boolean
                example:
                  category_name: false
              category_scores:
                type: object
                description: >-
                  Model-dependent category-level confidence scores when
                  available
                additionalProperties:
                  type: number
                example:
                  category_name: 0.01
        usage:
          type: object
          description: Token usage used for billing and diagnostics
          properties:
            prompt_tokens:
              type: integer
              description: Input tokens billed or recorded
              example: 12
            completion_tokens:
              type: integer
              description: Output tokens billed or recorded, when applicable
              example: 100
            total_tokens:
              type: integer
              description: Total tokens billed or recorded
              example: 112
    ModerationErrorResponse:
      type: object
      required:
        - error
      properties:
        error:
          type: object
          required:
            - message
            - type
          properties:
            message:
              type: string
              description: Human-readable error message
              example: >-
                Invalid request parameters. Please check your input and try
                again.
            type:
              type: string
              description: OpenAI-compatible error type
              example: invalid_request_error
            code:
              type:
                - string
                - 'null'
              description: Machine-readable error code
              example: unsupported_input_modality
            param:
              type:
                - string
                - 'null'
              description: Request parameter related to the error, when available
              example: input
    ModerationTextContentPart:
      type: object
      required:
        - type
        - text
      properties:
        type:
          type: string
          enum:
            - text
          description: Text content part
        text:
          type: string
          description: Text to classify
          example: Text to classify.
    ModerationImageContentPart:
      type: object
      required:
        - type
        - image_url
      properties:
        type:
          type: string
          enum:
            - image_url
          description: Image URL content part
        image_url:
          type: object
          required:
            - url
          properties:
            url:
              type: string
              format: uri
              description: Public image URL to classify
              example: https://example.com/image.png
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