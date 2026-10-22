> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Video Extend

> Extend a Midjourney video using a task-based flow (taskId + index).

## Overview

This endpoint is the task-based extension flow for Midjourney videos. For all other extend models, use `POST /api/generate-video` with a source video.

### Endpoint

```
POST /api/generate-video/extend
```

### Rate limit

20 requests/minute per IP

### Supported models (task-based)

* `midjourney-video` (extend a Midjourney video created via `POST /api/generate-video`)

### Required fields (Midjourney extend)

* `runId` (preferred) or `taskId` (legacy alias): the job ID from the original Midjourney video request
* `index` (0-3)

`index` maps to the 4 videos returned by the original Midjourney request.

### Request notes

* Send the same authentication headers as `/api/generate-video`.
* Session ownership is enforced; requests for jobs you do not own return `403`.
* This endpoint does not accept `video`, `videoUrl`, `videoDataUrl`, or `videoAttachmentId`.
* The response format matches the standard generation response (`runId`, `id`, `status`, `model`, `cost`).

## Source video extend (use `/api/generate-video`)

Use `POST /api/generate-video` with an extend model and a source video input.

**Extend model examples**:

* `wan-wavespeed-22-spicy-extend`
* `wan-wavespeed-25-extend`
* `veo3-1-extend`
* `veo3-1-fast-extend`
* `bytedance-seedance-v1.5-pro-extend`

**Required fields**:

* `prompt`
* `videoUrl` (or `videoDataUrl` / `videoAttachmentId`)

**Notes**:

* `video` is only accepted by specific models (for example, `wan-wavespeed-25-extend`).
* `wan-wavespeed-22-spicy-extend` accepts `videoUrl`, `videoDataUrl`, or `videoAttachmentId` only.
* Max source video length: 120 seconds.

### Example: Midjourney extend (task-based)

```json theme={null}
{
  "runId": "vid_m1abc123def456",
  "index": 0
}
```

### Example response

```json theme={null}
{
  "success": true,
  "runId": "vid_m1abc123def456",
  "id": "vid_m1abc123def456",
  "taskId": "vid_m1abc123def456",
  "status": "pending",
  "model": "midjourney-video",
  "message": "Extending video 1 by 5 seconds...",
  "eta": 60
}
```

### Example: Source video extend (`/api/generate-video`)

```json theme={null}
{
  "model": "wan-wavespeed-22-spicy-extend",
  "prompt": "Extend the clip with smooth motion and warm light",
  "videoUrl": "https://example.com/source.mp4",
  "resolution": "480p",
  "duration": 5,
  "seed": -1
}
```

`seed` is model/provider-route dependent and may improve reproducibility where supported; it does not guarantee identical output.


## OpenAPI

````yaml POST /generate-video/extend
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
  /generate-video/extend:
    post:
      description: Extend a Midjourney video using a task-based flow (taskId + index).
      requestBody:
        description: >-
          Midjourney extension request payload (taskId from the original run +
          index).
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/VideoExtendRequest'
        required: true
      responses:
        '202':
          description: >-
            Video extension request submitted successfully (asynchronous
            processing)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/VideoGenerationResponse'
        '400':
          description: Bad Request - Invalid parameters or safety filter triggered
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '500':
          description: Server Error - Video extension failed
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - apiKeyAuth: []
components:
  schemas:
    VideoExtendRequest:
      type: object
      required:
        - taskId
        - index
      properties:
        taskId:
          type: string
          description: Run ID from the original Midjourney video request.
        index:
          type: integer
          description: Zero-based index of the Midjourney video to extend (0-3).
          minimum: 0
          maximum: 3
      example:
        taskId: vid_m1abc123def456
        index: 0
    VideoGenerationResponse:
      type: object
      required:
        - runId
        - status
        - model
      properties:
        runId:
          type: string
          description: Unique identifier for the video generation request
        projectId:
          type: string
          description: Project identifier (for LongStories models)
        status:
          type: string
          description: Current status of the generation
          enum:
            - pending
            - processing
            - completed
            - failed
          default: pending
        model:
          type: string
          description: The model used for generation
        cost:
          type: number
          description: Cost of the video generation
        paymentSource:
          type: string
          description: Payment source used (USD or XNO)
        remainingBalance:
          type: number
          description: Remaining balance after the generation
        prechargeLabel:
          type: string
          description: Provider label for the precharge
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