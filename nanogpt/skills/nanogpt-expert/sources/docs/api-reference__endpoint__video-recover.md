> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Video Recover

> Recover recent video generation runs for a user.

## Overview

Recover recent video generation runs for a user.

### Endpoint

```
GET /api/generate-video/recover
```

### Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `model` | string | No | Filter by model |
| `limit` | number | No | Max results (default 10, max 50) |
| `conversationUUID` | string | No | Filter by conversation |

### Rate limit

20 requests/minute per IP

## Usage

```bash theme={null}
curl -s "https://api.nano-gpt.com/api/generate-video/recover?limit=10" \
  -H "x-api-key: YOUR_API_KEY" | jq .
```

## Response

```json theme={null}
{
  "data": [
    {
      "runId": "vid_m1abc123def456",
      "id": "vid_m1abc123def456",
      "model": "sora-2",
      "status": "completed",
      "createdAt": "2025-01-17T12:34:56.000Z",
      "conversationUUID": "b7c75a5e-1e2a-4d4f-9e5b-6c6e2e2f9a17"
    }
  ]
}
```

Notes:

* New runs return NanoGPT job IDs (`vid_...`); legacy runs may return provider request IDs.


## OpenAPI

````yaml GET /generate-video/recover
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
  /generate-video/recover:
    get:
      description: Recover recent video generation runs for a user.
      parameters:
        - name: model
          in: query
          description: Optional model filter
          required: false
          schema:
            type: string
        - name: limit
          in: query
          description: Max results (default 10, max 50)
          required: false
          schema:
            type: integer
            minimum: 1
            maximum: 50
        - name: conversationUUID
          in: query
          description: Filter by conversation
          required: false
          schema:
            type: string
      responses:
        '200':
          description: Recovered runs
          content:
            application/json:
              schema:
                type: object
                additionalProperties: true
        '400':
          description: >-
            Bad Request - Invalid parameters. Video errors include
            video_input_not_supported, invalid_video_url_scheme,
            invalid_video_data_url, invalid_video_base64,
            invalid_video_mime_type, missing_video_source,
            video_file_id_not_supported, video_attachment_too_large,
            video_attachment_limit_exceeded, invalid_video_segment,
            video_segment_not_supported, and youtube_video_route_not_supported.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '500':
          description: Server Error - Failed to recover runs
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - apiKeyAuth: []
components:
  schemas:
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
    apiKeyAuth:
      type: apiKey
      in: header
      name: x-api-key

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.