> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# List All Batches

> List all authenticated batches with filters and bidirectional cursor pagination

This OpenAI-compatible list includes both inline and file-backed jobs. Items retain the standard batch shape, including file IDs, lifecycle timestamps, request counts, metadata, usage, and errors where applicable.

See the [Batch API guide](/api-reference/endpoint/batches#list-batches) for pagination examples, filter rules, and error behavior.


## OpenAPI

````yaml GET /api/v1/batches
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
  /api/v1/batches:
    servers:
      - url: https://api.nano-gpt.com
    get:
      tags:
        - Batch
      summary: List all batches
      description: >-
        Lists all batches visible to the authenticated credential in the
        OpenAI-compatible batch shape, including inline and file-backed jobs.
        Results are newest first. Preserve the same filters on every paginated
        request.
      operationId: listFileBatches
      parameters:
        - name: limit
          in: query
          description: Number of batches to return.
          schema:
            type: integer
            minimum: 1
            maximum: 100
            default: 20
        - name: after
          in: query
          description: >-
            Return the next page of batches older than this batch ID. Use the
            current page's last_id. Cannot be combined with before.
          schema:
            type: string
        - name: before
          in: query
          description: >-
            Return the adjacent page of batches newer than this batch ID, still
            ordered newest first. Use the current page's first_id. Cannot be
            combined with after.
          schema:
            type: string
        - name: status
          in: query
          description: >-
            Filter by one or more statuses. Repeat the parameter or provide
            comma-separated values.
          style: form
          explode: true
          schema:
            type: array
            items:
              $ref: '#/components/schemas/BatchStatus'
        - name: created_after
          in: query
          description: >-
            Return batches created strictly after this boundary. Accepts Unix
            seconds or a timezone-qualified ISO 8601/RFC 3339 timestamp with at
            most millisecond precision.
          schema:
            oneOf:
              - type: integer
                format: int64
              - type: string
        - name: created_before
          in: query
          description: >-
            Return batches created strictly before this boundary. Accepts Unix
            seconds or a timezone-qualified ISO 8601/RFC 3339 timestamp with at
            most millisecond precision.
          schema:
            oneOf:
              - type: integer
                format: int64
              - type: string
      responses:
        '200':
          description: A page of all visible batches ordered newest first.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/FileBatchList'
        '400':
          description: Invalid filters, timestamp range, or cursor.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Missing or invalid authentication.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - bearerAuth: []
components:
  schemas:
    BatchStatus:
      type: string
      enum:
        - validating
        - in_progress
        - finalizing
        - completed
        - failed
        - expired
        - cancelling
        - cancelled
    FileBatchList:
      type: object
      required:
        - object
        - data
        - first_id
        - last_id
        - has_more
      properties:
        object:
          type: string
          const: list
        data:
          type: array
          description: >-
            All visible batches ordered newest first, including inline and
            file-backed jobs.
          items:
            $ref: '#/components/schemas/FileBatchListItem'
        first_id:
          type:
            - string
            - 'null'
          description: >-
            First batch ID in this page, or null for an empty page. Pass as
            before to return to the adjacent newer page.
        last_id:
          type:
            - string
            - 'null'
          description: >-
            Last batch ID in this page, or null for an empty page. Pass as after
            to fetch the next older page.
        has_more:
          type: boolean
          description: Whether more records exist in the direction being paged.
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
    FileBatchListItem:
      type: object
      required:
        - id
        - object
        - endpoint
        - input_file_id
        - completion_window
        - status
        - created_at
        - request_counts
      properties:
        id:
          type: string
          description: File-backed batch ID.
        object:
          type: string
          const: batch
        endpoint:
          type: string
          enum:
            - /v1/chat/completions
            - /v1/responses
        input_file_id:
          type: string
        output_file_id:
          type:
            - string
            - 'null'
        error_file_id:
          type:
            - string
            - 'null'
        completion_window:
          type: string
          const: 24h
        status:
          $ref: '#/components/schemas/BatchStatus'
        created_at:
          type: integer
          format: int64
        in_progress_at:
          type:
            - integer
            - 'null'
          format: int64
        finalizing_at:
          type:
            - integer
            - 'null'
          format: int64
        completed_at:
          type:
            - integer
            - 'null'
          format: int64
        failed_at:
          type:
            - integer
            - 'null'
          format: int64
        expired_at:
          type:
            - integer
            - 'null'
          format: int64
        cancelling_at:
          type:
            - integer
            - 'null'
          format: int64
        cancelled_at:
          type:
            - integer
            - 'null'
          format: int64
        request_counts:
          $ref: '#/components/schemas/BatchRequestCounts'
        metadata:
          type:
            - object
            - 'null'
          additionalProperties: true
        usage:
          oneOf:
            - $ref: '#/components/schemas/BatchUsage'
            - type: 'null'
        errors:
          type:
            - object
            - 'null'
          additionalProperties: true
      additionalProperties: true
    BatchRequestCounts:
      type: object
      required:
        - total
        - completed
        - failed
      properties:
        total:
          type: integer
          minimum: 0
        completed:
          type: integer
          minimum: 0
        failed:
          type: integer
          minimum: 0
    BatchUsage:
      type: object
      properties:
        prompt_tokens:
          type: integer
          minimum: 0
        completion_tokens:
          type: integer
          minimum: 0
        total_tokens:
          type: integer
          minimum: 0
      additionalProperties: true
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.