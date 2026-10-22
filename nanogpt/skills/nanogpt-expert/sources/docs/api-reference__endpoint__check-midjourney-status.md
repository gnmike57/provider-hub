> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve Midjourney Generation Status

> Check the status of an asynchronous Midjourney image generation task



## OpenAPI

````yaml POST /check-midjourney-status
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
  /check-midjourney-status:
    post:
      description: Check the status of an asynchronous Midjourney image generation task
      requestBody:
        description: Task ID to check status for
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CheckMidjourneyStatusRequest'
        required: true
      responses:
        '200':
          description: Midjourney task status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CheckMidjourneyStatusResponse'
        '400':
          description: Bad Request (e.g., missing task_id)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized (invalid API key)
      security:
        - apiKeyAuth: []
components:
  schemas:
    CheckMidjourneyStatusRequest:
      type: object
      required:
        - task_id
      properties:
        task_id:
          type: string
          description: The unique identifier for the Midjourney generation task.
          example: '1744449927914205'
    CheckMidjourneyStatusResponse:
      type: object
      required:
        - status
        - task_id
      properties:
        status:
          type: string
          description: The current status of the Midjourney task.
          enum:
            - SUCCESS
            - FAILED
            - PENDING
            - RUNNING
            - IN_PROGRESS
            - submitted
            - NOT_START
            - unknown
          example: SUCCESS
        task_id:
          type: string
          description: The unique identifier for the Midjourney generation task.
          example: '1744449927914205'
        progress:
          type: string
          description: Optional progress indicator (e.g., "0%")
          example: 50%
          nullable: true
        imageUrl:
          type: string
          format: uri
          description: The URL of the generated image (present on SUCCESS).
          example: https://image-url.com/generated_image.png
          nullable: true
        failReason:
          type: string
          description: The reason for failure (present on FAILED).
          example: Content moderation filter triggered.
          nullable: true
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