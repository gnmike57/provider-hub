> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Moderation Models

> List available content moderation models

## Overview

Use `GET /api/v1/moderation-models` to list the moderation models currently available to your account. The response includes model capabilities, context limits, and pricing.

Model availability and capabilities can change over time. Use this endpoint as the source of truth before choosing a model for `POST /api/v1/moderations` or [Inline Moderation](/api-reference/miscellaneous/inline-moderation).

## Endpoint

```text theme={null}
GET https://api.nano-gpt.com/api/v1/moderation-models
```

## Authentication

An API key is required.

* `Authorization: Bearer YOUR_API_KEY`
* `x-api-key: YOUR_API_KEY`

## Query Parameters

| Parameter | Type | Default | Description |
| - | - | - | - |
| `detailed` | boolean | `true` | When `false`, returns a compact OpenAI-style model list. |

## Examples

```bash theme={null}
curl https://api.nano-gpt.com/api/v1/moderation-models \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/moderation-models?detailed=false" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

## Response

The detailed response returns a model list with capability and pricing metadata. Exact fields can vary by model.

```json theme={null}
{
  "object": "list",
  "data": [
    {
      "id": "moderation-model-id",
      "object": "model",
      "created": 1704067200,
      "owned_by": "model-owner",
      "context_length": 128000,
      "capabilities": {
        "text": true,
        "image": true,
        "batch": true
      },
      "pricing": {
        "prompt": 0.10,
        "completion": 0.00,
        "currency": "USD",
        "unit": "per_million_tokens"
      }
    }
  ]
}
```

## Notes

* This is a paid API feature.
* Some moderation models support text only; others support both text and image inputs.
* Batch support can vary by model.
* Pricing details are returned by this endpoint and can vary by selected model.


## OpenAPI

````yaml GET /v1/moderation-models
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
  /v1/moderation-models:
    get:
      description: >-
        List available moderation models, capabilities, context limits, and
        pricing
      parameters:
        - name: detailed
          in: query
          description: When false, returns a compact OpenAI-style model list
          required: false
          schema:
            type: boolean
            default: true
      responses:
        '200':
          description: List of available moderation models
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationModelsResponse'
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModerationErrorResponse'
        '401':
          description: Unauthorized - Invalid or missing API key
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    ModerationModelsResponse:
      type: object
      required:
        - object
        - data
      properties:
        object:
          type: string
          description: Always 'list'
          example: list
        data:
          type: array
          description: Array of moderation model objects
          items:
            type: object
            required:
              - id
              - object
              - created
              - owned_by
            properties:
              id:
                type: string
                description: Unique moderation model identifier
                example: moderation-model-id
              object:
                type: string
                description: Always 'model'
                example: model
              created:
                type: integer
                description: Unix timestamp
                example: 1704067200
              owned_by:
                type: string
                description: Model owner
                example: model-owner
              context_length:
                type: integer
                description: Maximum input tokens supported by the model
                example: 128000
              capabilities:
                type: object
                description: Model-dependent moderation capabilities
                properties:
                  text:
                    type: boolean
                    description: Supports text inputs
                    example: true
                  image:
                    type: boolean
                    description: Supports image inputs
                    example: true
                  batch:
                    type: boolean
                    description: Supports batched inputs
                    example: true
                additionalProperties: true
              pricing:
                type: object
                description: Pricing information for the moderation model
                properties:
                  prompt:
                    type: number
                    description: Cost per million input tokens in USD
                    example: 0.1
                  completion:
                    type: number
                    description: >-
                      Cost per million output tokens in USD, when billable
                      classification output applies
                    example: 0
                  currency:
                    type: string
                    description: Pricing currency
                    example: USD
                  unit:
                    type: string
                    description: Pricing unit
                    example: per_million_tokens
                additionalProperties: true
            additionalProperties: true
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