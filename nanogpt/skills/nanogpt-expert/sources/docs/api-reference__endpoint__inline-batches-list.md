> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# List Inline Batches

> List authenticated inline batches with filters and bidirectional cursor pagination

Inline list responses contain metadata only. The `results` field is always `null`, including for completed batches. Retrieve `GET /api/beta/batches/{batch_id}` to obtain completed inline results.

See the [Batch API guide](/api-reference/endpoint/batches#list-batches) for pagination examples, filter rules, and error behavior.


## OpenAPI

````yaml GET /api/beta/batches
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
  /api/beta/batches:
    servers:
      - url: https://api.nano-gpt.com
    get:
      tags:
        - Batch
      summary: List inline batches
      description: >-
        Lists inline batches visible to the authenticated credential, newest
        first. The response is metadata-only: results is always null, including
        for completed batches. Use GET /api/beta/batches/{id} to retrieve
        completed inline results. Preserve the same filters on every paginated
        request.
      operationId: listInlineBatches
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
          description: A page of inline batch metadata ordered newest first.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InlineBatchList'
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
    InlineBatchList:
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
          description: Inline batch metadata ordered newest first.
          items:
            $ref: '#/components/schemas/InlineBatchListItem'
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
    InlineBatchListItem:
      type: object
      required:
        - id
        - object
        - endpoint
        - model
        - completion_window
        - status
        - created_at
        - request_counts
        - results
      properties:
        id:
          type: string
          description: Inline batch ID.
        object:
          type: string
          const: batch
        endpoint:
          type: string
          enum:
            - /v1/chat/completions
            - /v1/responses
        model:
          type: string
        completion_window:
          type: string
          const: 24h
        status:
          $ref: '#/components/schemas/BatchStatus'
        created_at:
          type: integer
          format: int64
          description: Unix timestamp in seconds.
        finalized_at:
          type:
            - integer
            - 'null'
          format: int64
          description: Unix timestamp in seconds, or null before finalization.
        request_counts:
          $ref: '#/components/schemas/BatchRequestCounts'
        usage:
          oneOf:
            - $ref: '#/components/schemas/BatchUsage'
            - type: 'null'
        results:
          type: 'null'
          description: >-
            Always null in list responses. Retrieve the individual inline batch
            to obtain completed results.
        error:
          type:
            - object
            - 'null'
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