> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Usage

> Retrieve aggregate spend, request, and token usage for the authenticated API key

## Overview

The Usage API returns bounded aggregate usage for the API key used to authenticate the request. Use it to answer:

* What did this API key spend?
* Which models was that spend on?
* How many requests and tokens were used?
* What happened over a specific UTC date range?

The endpoint returns aggregate usage only. It does not return raw transaction rows, request payloads, prompts, responses, provider routing details, or account-wide usage across multiple API keys.

For one recent request, use [Request Billing](/api-reference/endpoint/request-billing)
with its captured `X-Request-ID` and the same inference API key. That lookup has
a rolling 24-hour window and returns the original primary charge; it does not
subtract refunds or include separately billed extras.

## Base URL

```text theme={null}
https://api.nano-gpt.com/api/v1/usage
```

## Authentication

Use the same NanoGPT API key authentication as other API routes:

```http theme={null}
Authorization: Bearer $NANOGPT_API_KEY
```

Example:

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/usage" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

## Default Request

If no date range is provided, the endpoint returns the authenticated API key's last 30 UTC days, grouped by both day and model.

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/usage" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

## Date Ranges

Use `from` and `to` to request an explicit UTC date range. Both values must be `YYYY-MM-DD` dates. `to` is inclusive.

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/usage?from=2026-05-01&to=2026-05-31" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

Rules:

* `from` and `to` must be provided together.
* `to` must be on or after `from`.
* `to` cannot be in the future.
* Ranges are capped at 366 days.
* All dates are interpreted in UTC.

## Grouping

Use `group_by` to control which aggregate arrays are returned.

| Value | Returned arrays |
| - | - |
| `day` | `byDay` |
| `model` | `byModel` |
| `day,model` | `byDay`, `byModel`, `byDayModel` |

`day,model` is the default. `model,day` is accepted as an alias for `day,model`.

Example:

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/usage?from=2026-05-01&to=2026-05-31&group_by=model" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

## Scope

The endpoint is scoped to the authenticated API key.

| Parameter | Default | Notes |
| - | - | - |
| `scope` | `current_key` | `current_key` and `api_key` both return the authenticated API key's usage. |
| `api_key_id` | current key | Optional current API key ID. Requests for another API key are rejected. |

This endpoint does not return account-wide usage across all API keys.

## Response Shape

```json theme={null}
{
  "object": "usage",
  "scope": "current_key",
  "apiKey": {
    "id": 123
  },
  "from": "2026-05-01",
  "to": "2026-05-31",
  "timezone": "UTC",
  "groupBy": "day,model",
  "asOf": "2026-05-31T12:00:00.000Z",
  "source": {
    "rollupDays": ["2026-05-01"],
    "liveDays": ["2026-05-31"],
    "missingRollupDays": []
  },
  "totals": {
    "requests": 1284,
    "costUsd": 42.18,
    "refundedUsd": 1.25,
    "netCostUsd": 40.93,
    "inputTokens": 1234567,
    "outputTokens": 456789,
    "reasoningTokens": 12000,
    "totalTokens": 1691356
  },
  "byDay": [
    {
      "date": "2026-05-01",
      "requests": 61,
      "costUsd": 1.94,
      "refundedUsd": 0,
      "netCostUsd": 1.94,
      "inputTokens": 78000,
      "outputTokens": 21000,
      "reasoningTokens": 0,
      "totalTokens": 99000
    }
  ],
  "byModel": [
    {
      "model": "GPT-4.1 mini",
      "requests": 812,
      "costUsd": 18.92,
      "refundedUsd": 0.5,
      "netCostUsd": 18.42,
      "inputTokens": 900000,
      "outputTokens": 220000,
      "reasoningTokens": 0,
      "totalTokens": 1120000
    }
  ],
  "byDayModel": [
    {
      "date": "2026-05-01",
      "model": "GPT-4.1 mini",
      "requests": 20,
      "costUsd": 0.64,
      "refundedUsd": 0,
      "netCostUsd": 0.64,
      "inputTokens": 30000,
      "outputTokens": 8000,
      "reasoningTokens": 0,
      "totalTokens": 38000
    }
  ]
}
```

## Field Reference

Top-level fields:

| Field | Description |
| - | - |
| `object` | Always `usage`. |
| `scope` | Echoes the requested scope, either `current_key` or `api_key`. |
| `apiKey.id` | Numeric ID of the authenticated API key. |
| `from` | UTC start date. |
| `to` | UTC end date, inclusive. |
| `timezone` | Always `UTC`. |
| `groupBy` | The effective grouping mode. |
| `asOf` | Timestamp when the aggregate response was generated. Cached responses can be up to 60 seconds old. |
| `source.rollupDays` | Days served from precomputed daily rollups. |
| `source.liveDays` | Days served from live aggregation. Usually today or days not rolled up yet. |
| `source.missingRollupDays` | Closed UTC days that were not available in the rollup table and had to be served live. |

Usage counter fields:

| Field | Description |
| - | - |
| `requests` | Number of billable usage requests in the aggregate bucket. |
| `costUsd` | Gross USD usage cost before refunds. |
| `refundedUsd` | USD amount refunded in the aggregate bucket. |
| `netCostUsd` | `max(0, costUsd - refundedUsd)` for that aggregate bucket. |
| `inputTokens` | Input tokens counted for the bucket. |
| `outputTokens` | Output tokens counted for the bucket. |
| `reasoningTokens` | Reasoning tokens counted separately when available. |
| `totalTokens` | `inputTokens + outputTokens`. Reasoning tokens are reported separately and are not added to `totalTokens`. |

Model fields:

* `model` values are public model labels.
* Internal routing providers are not exposed.
* Variants that share the same public label may be combined under that label.

## Refund Notes

Refunds are applied at each returned aggregation level with:

```text theme={null}
netCostUsd = max(0, costUsd - refundedUsd)
```

Because net cost is floored per bucket, sums of `byModel` or `byDayModel` rows may differ slightly from `totals.netCostUsd` when refunds cross buckets.

## Errors

Errors use the standard NanoGPT API error shape:

```json theme={null}
{
  "error": {
    "message": "from and to must use YYYY-MM-DD UTC dates.",
    "type": "invalid_request_error"
  }
}
```

Common errors:

| Status | Type | Meaning |
| - | - | - |
| `400` | `invalid_request_error` | Invalid date range, unsupported parameter, invalid grouping, or request for a different API key. |
| `401` | `missing_api_key` / `invalid_api_key` | Missing or invalid API key. |
| `429` | `rate_limit_exceeded` | Too many usage requests. |
| `503` | `usage_not_ready` | The requested range needs rollup data that is not ready yet. Try a shorter range or retry after rollup sync completes. |
| `503` | `service_unavailable` | Usage API temporarily unavailable. |
| `500` | `server_error` | Unexpected usage retrieval failure. |

## Legacy Parameter Behavior

The usage endpoint is aggregate-first and rejects legacy row-history parameters.

Rejected legacy parameters include:

* `duration`
* `page`
* `pageSize`
* `sort`
* `dir`
* `filter`
* `weekOffset`
* `tz`
* `include_summary`

Use explicit UTC `from` and `to` dates instead.


## OpenAPI

````yaml GET /v1/usage
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
  /v1/usage:
    get:
      description: >-
        Retrieve aggregate spend, request, and token usage for the authenticated
        API key, grouped by UTC day, model, or both.
      parameters:
        - name: from
          in: query
          description: >-
            UTC start date in YYYY-MM-DD format. Must be provided together with
            `to`.
          required: false
          schema:
            type: string
            format: date
            example: '2026-05-01'
        - name: to
          in: query
          description: >-
            UTC end date in YYYY-MM-DD format, inclusive. Must be on or after
            `from` and cannot be in the future.
          required: false
          schema:
            type: string
            format: date
            example: '2026-05-31'
        - name: group_by
          in: query
          description: >-
            Controls which aggregate arrays are returned. `model,day` is
            accepted as an alias for `day,model`.
          required: false
          schema:
            type: string
            enum:
              - day
              - model
              - day,model
              - model,day
            default: day,model
            example: day,model
        - name: scope
          in: query
          description: >-
            Usage scope. `current_key` and `api_key` both return usage for the
            authenticated API key.
          required: false
          schema:
            type: string
            enum:
              - current_key
              - api_key
            default: current_key
        - name: api_key_id
          in: query
          description: >-
            Optional current API key ID. Requests for another API key are
            rejected.
          required: false
          schema:
            type: integer
            example: 123
      responses:
        '200':
          description: Aggregate usage for the authenticated API key
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageResponse'
        '400':
          description: >-
            Invalid date range, unsupported parameter, invalid grouping, or
            request for a different API key
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageError'
        '401':
          description: Missing or invalid API key
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageError'
        '429':
          description: Too many usage requests
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageError'
        '500':
          description: Unexpected usage retrieval failure
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageError'
        '503':
          description: >-
            Usage API temporarily unavailable or requested rollup data is not
            ready yet
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageError'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    UsageResponse:
      type: object
      required:
        - object
        - scope
        - apiKey
        - from
        - to
        - timezone
        - groupBy
        - asOf
        - source
        - totals
      properties:
        object:
          type: string
          enum:
            - usage
          description: Always usage.
        scope:
          type: string
          enum:
            - current_key
            - api_key
          description: Echoes the requested usage scope.
        apiKey:
          type: object
          required:
            - id
          properties:
            id:
              type: integer
              description: Numeric ID of the authenticated API key.
              example: 123
        from:
          type: string
          format: date
          description: UTC start date.
          example: '2026-05-01'
        to:
          type: string
          format: date
          description: UTC end date, inclusive.
          example: '2026-05-31'
        timezone:
          type: string
          enum:
            - UTC
          description: Always UTC.
        groupBy:
          type: string
          enum:
            - day
            - model
            - day,model
          description: The effective grouping mode.
          example: day,model
        asOf:
          type: string
          format: date-time
          description: >-
            Timestamp when the aggregate response was generated. Cached
            responses can be up to 60 seconds old.
          example: '2026-05-31T12:00:00.000Z'
        source:
          $ref: '#/components/schemas/UsageSource'
        totals:
          $ref: '#/components/schemas/UsageCounterBucket'
        byDay:
          type: array
          description: Returned when grouped by day.
          items:
            $ref: '#/components/schemas/UsageCounterBucket'
        byModel:
          type: array
          description: Returned when grouped by model.
          items:
            $ref: '#/components/schemas/UsageCounterBucket'
        byDayModel:
          type: array
          description: Returned when grouped by both day and model.
          items:
            $ref: '#/components/schemas/UsageCounterBucket'
    UsageError:
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
              example: from and to must use YYYY-MM-DD UTC dates.
            type:
              type: string
              example: invalid_request_error
    UsageSource:
      type: object
      required:
        - rollupDays
        - liveDays
        - missingRollupDays
      properties:
        rollupDays:
          type: array
          description: Days served from precomputed daily rollups.
          items:
            type: string
            format: date
          example:
            - '2026-05-01'
        liveDays:
          type: array
          description: >-
            Days served from live aggregation, usually today or days not rolled
            up yet.
          items:
            type: string
            format: date
          example:
            - '2026-05-31'
        missingRollupDays:
          type: array
          description: >-
            Closed UTC days that were not available in the rollup table and had
            to be served live.
          items:
            type: string
            format: date
          example: []
    UsageCounterBucket:
      type: object
      required:
        - requests
        - costUsd
        - refundedUsd
        - netCostUsd
        - inputTokens
        - outputTokens
        - reasoningTokens
        - totalTokens
      properties:
        date:
          type: string
          format: date
          description: UTC date for day-grouped buckets.
          example: '2026-05-01'
        model:
          type: string
          description: Public model label for model-grouped buckets.
          example: GPT-4.1 mini
        requests:
          type: integer
          description: Number of billable usage requests in the aggregate bucket.
          example: 1284
        costUsd:
          type: number
          description: Gross USD usage cost before refunds.
          example: 42.18
        refundedUsd:
          type: number
          description: USD amount refunded in the aggregate bucket.
          example: 1.25
        netCostUsd:
          type: number
          description: max(0, costUsd - refundedUsd) for the aggregate bucket.
          example: 40.93
        inputTokens:
          type: integer
          description: Input tokens counted for the bucket.
          example: 1234567
        outputTokens:
          type: integer
          description: Output tokens counted for the bucket.
          example: 456789
        reasoningTokens:
          type: integer
          description: Reasoning tokens counted separately when available.
          example: 12000
        totalTokens:
          type: integer
          description: >-
            inputTokens + outputTokens. Reasoning tokens are reported separately
            and are not added to totalTokens.
          example: 1691356
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