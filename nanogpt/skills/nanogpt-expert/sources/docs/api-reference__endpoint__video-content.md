> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Video Content

> Proxy content retrieval for Sora 2 videos.

## Overview

Proxy content retrieval for Sora 2 videos.

### Endpoint

```
GET /api/generate-video/content
```

### Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `runId` | string | Yes | The run ID |
| `model` | string | Yes | Must be `sora-2` |
| `variant` | string | No | `video`, `thumbnail`, or `spritesheet` |

## Usage

```bash theme={null}
curl -s "https://api.nano-gpt.com/api/generate-video/content?runId=RUN_ID&model=sora-2&variant=video" \
  -H "x-api-key: YOUR_API_KEY" | jq .
```


## OpenAPI

````yaml GET /generate-video/content
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
  /generate-video/content:
    get:
      description: Proxy content retrieval for Sora 2 videos.
      parameters:
        - name: runId
          in: query
          description: Run ID returned from the POST /generate-video response
          required: true
          schema:
            type: string
        - name: model
          in: query
          description: Must be sora-2
          required: true
          schema:
            type: string
        - name: variant
          in: query
          description: video, thumbnail, or spritesheet
          required: false
          schema:
            type: string
      responses:
        '200':
          description: Content response
          content:
            application/json:
              schema:
                type: object
                additionalProperties: true
        '400':
          description: Bad Request - Missing or invalid parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '500':
          description: Server Error - Failed to retrieve content
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