> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Video Status (Unified)

> Unified video status endpoint that works across all video backends. Check the status of a video generation request using only the request ID and receive normalized status information.

## Overview

Check the status of an asynchronous video generation job using a single, provider-agnostic endpoint. This endpoint accepts NanoGPT job IDs (`vid_...`) and legacy provider request IDs. No `model` parameter is required. Session ownership is enforced (returns `403` when the job is not yours).

### Query parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `requestId` | string | Yes\* | The job ID (`vid_...`) or a legacy provider request ID |
| `runId` | string | Yes\* | Alias for `requestId` |

\*Send either `requestId` or `runId`.

### Authentication

Provide `x-api-key` or a valid session cookie.

## Usage

<CodeGroup>
  ```python Python theme={null}
  import requests
  import time

  BASE = "https://api.nano-gpt.com/api"

  def get_video_status(request_id: str, api_key: str) -> dict:
      resp = requests.get(
          f"{BASE}/video/status",
          headers={"x-api-key": api_key},
          params={"requestId": request_id},
          timeout=30,
      )
      resp.raise_for_status()
      return resp.json()

  def wait_for_video(request_id: str, api_key: str, max_attempts: int = 120, delay_s: int = 5) -> str:
      for _ in range(max_attempts):
          payload = get_video_status(request_id, api_key)
          status = payload.get("data", {}).get("status")
          if status == "COMPLETED":
              return payload["data"]["output"]["video"]["url"]
          if status == "FAILED":
              raise RuntimeError(payload.get("data", {}).get("error", "Video generation failed"))
          time.sleep(delay_s)
      raise TimeoutError("Video generation timed out")
  ```

  ```javascript JavaScript theme={null}
  const BASE = 'https://api.nano-gpt.com/api';

  async function getVideoStatus(requestId, apiKey) {
    const url = new URL(`${BASE}/video/status`);
    url.searchParams.set('requestId', requestId);
    const res = await fetch(url, {
      headers: { 'x-api-key': apiKey }
    });
    if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
    return res.json();
  }

  export async function waitForVideo(requestId, apiKey, maxAttempts = 120, delayMs = 5000) {
    for (let i = 0; i < maxAttempts; i++) {
      const payload = await getVideoStatus(requestId, apiKey);
      const status = payload?.data?.status;
      if (status === 'COMPLETED') return payload.data.output.video.url;
      if (status === 'FAILED') throw new Error(payload?.data?.error || 'Video generation failed');
      await new Promise((r) => setTimeout(r, delayMs));
    }
    throw new Error('Video generation timed out');
  }
  ```

  ```bash cURL theme={null}
  # Single status check
  curl -s "https://api.nano-gpt.com/api/video/status?requestId=vid_m1abc123def456" \
    -H "x-api-key: YOUR_API_KEY" | jq .

  # Poll until complete (~10 minutes max)
  for i in {1..120}; do
    RESP=$(curl -s "https://api.nano-gpt.com/api/video/status?requestId=vid_m1abc123def456" -H "x-api-key: YOUR_API_KEY")
    STATUS=$(echo "$RESP" | jq -r '.data.status // empty')
    echo "Attempt $i: status=$STATUS"
    if [ "$STATUS" = "COMPLETED" ]; then
      echo "$RESP" | jq .
      VIDEO_URL=$(echo "$RESP" | jq -r '.data.output.video.url')
      echo "Video URL: $VIDEO_URL"
      break
    fi
    sleep 5
  done
  ```
</CodeGroup>

## Status values

* `IN_QUEUE`: Request queued
* `IN_PROGRESS`: Generation in progress
* `COMPLETED`: Video ready
* `FAILED`: Generation failed
* `CANCELED`: Request canceled

## Response examples

### In progress

```json theme={null}
{
  "requestId": "vid_m1abc123def456",
  "model": "sora-2",
  "data": {
    "status": "IN_PROGRESS",
    "requestId": "vid_m1abc123def456"
  }
}
```

### Completed

```json theme={null}
{
  "requestId": "vid_m1abc123def456",
  "model": "sora-2",
  "data": {
    "status": "COMPLETED",
    "requestId": "vid_m1abc123def456",
    "output": {
      "video": {
        "url": "https://storage.example.com/video.mp4"
      }
    },
    "cost": 0.35
  }
}
```

### Failed

```json theme={null}
{
  "requestId": "vid_m1abc123def456",
  "model": "sora-2",
  "data": {
    "status": "FAILED",
    "requestId": "vid_m1abc123def456",
    "error": "Content policy violation",
    "isNSFWError": true,
    "userFriendlyError": "Content flagged as inappropriate. Please modify your prompt and try again."
  }
}
```

Notes:

* Terminal results are cached in `video_jobs` for faster subsequent status checks.


## OpenAPI

````yaml GET /video/status
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
  /video/status:
    get:
      description: >-
        Unified video status endpoint that works across all video backends.
        Check the status of a video generation request using only the request ID
        and receive normalized status information.
      parameters:
        - name: requestId
          in: query
          description: The unique request ID returned from any video generation endpoint
          required: true
          schema:
            type: string
          example: vid_m1abc123def456
      responses:
        '200':
          description: Unified video generation status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnifiedVideoStatusResponse'
        '400':
          description: Bad Request - Missing requestId parameter
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '404':
          description: Video generation request not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: Server Error - Failed to check video generation status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - apiKeyAuth: []
components:
  schemas:
    UnifiedVideoStatusResponse:
      type: object
      required:
        - requestId
        - status
        - videoUrl
        - error
        - createdAt
        - completedAt
      properties:
        requestId:
          type: string
          description: The unique request ID for the video generation
        status:
          type: string
          description: Current normalized status of the video generation
          enum:
            - queued
            - processing
            - completed
            - failed
            - cancelled
            - unknown
        progress:
          type: number
          nullable: true
          description: Generation progress as a percentage (0-100), if available
        estimatedTimeRemaining:
          type: number
          nullable: true
          description: Estimated time remaining in seconds, if available
        videoUrl:
          type: string
          nullable: true
          description: URL to the generated video (available when status is 'completed')
        error:
          type: string
          nullable: true
          description: Error message if the generation failed
        createdAt:
          type: string
          nullable: true
          description: ISO timestamp when the request was created
        completedAt:
          type: string
          nullable: true
          description: ISO timestamp when the generation completed
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