> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Request Billing

> Look up a recorded primary charge and token usage by request ID for 24 hours.

`GET /api/v1/usage/requests/{request_id}` returns the recorded cost and token
usage for one primary charge from the **last 24 hours**. Capture `X-Request-ID`
from the inference response headers before reading SSE and use the **same API
key** for the lookup. No dates or other query parameters are accepted.

For chat completions, omit the incoming `X-Request-ID` header and capture the
server-generated ID from each response. Save it as soon as the response headers
arrive, before consuming the stream; it is the ID to use for this lookup.

```sh theme={null}
curl 'https://api.nano-gpt.com/api/v1/usage/requests/req_example' \
  -H "Authorization: Bearer $NANOGPT_API_KEY"
```

```json theme={null}
{
  "object": "request_billing",
  "request_id": "req_example",
  "created_at": "2026-09-17T10:00:01.000000Z",
  "expires_at": "2026-09-18T10:00:01.000000Z",
  "as_of": "2026-09-17T10:00:05.000000Z",
  "cost": "0.00123456",
  "currency": "USD",
  "cost_scope": "primary_charge",
  "usage": {
    "input_tokens": 123,
    "output_tokens": 45,
    "reasoning_tokens": null
  }
}
```

## What cost means

`cost` is the exact amount recorded on the matching primary charge, expressed
as a decimal **string** in `currency` (`USD` or `XNO`). The lookup does not
recalculate prices. A recorded zero is returned as zero; a missing charge is
never converted to zero.

Refunds and separately billed extras, such as a separate search charge, are
excluded. Components already incorporated in the primary charge's amount remain
included. This is the original recorded primary cost, not an all-in total or a
net amount after refunds. A later refund does not reduce this field. A completed
transaction record is also not proof that balance collection has finished.

Tokens are recorded accounting values and may have been estimated for an
interrupted stream. Missing, invalid or unsafe-sized counts are `null`.
Reasoning tokens may already be included in output tokens; do not add them again.
No prompts, responses, provider routing, internal identifiers or arbitrary
transaction metadata are returned.

## Availability and request IDs

The window is rolling, including across UTC midnight. A charge is eligible when
its accounting timestamp is no more than the database's current time and is
strictly less than 24 hours old. `expires_at` is that timestamp plus 24 hours;
access ends at that instant. This timestamp can precede insertion when delayed
billing is replayed. Replay does not reset the lookup window. Financial records
are retained; this endpoint simply stops exposing older charges.

Billing can be asynchronous, especially after a disconnect, so the charge might
not be available immediately. A charge recorded only after its window expires
cannot be recovered through this endpoint. Expired, unavailable and inaccessible
records all return the same 404; this does not prove that a request was free.

If you supply your own `X-Request-ID`, use a unique value for every execution,
including a retry that sends a new inference request. The header is a correlation
ID, **not an idempotency key**: reusing it does not prevent another charge. After a
disconnect, look up the original ID to recover its cost; retrying the lookup does
not rerun inference. If you also retry inference, keep the two execution IDs
separate. If more than one eligible primary charge matches within the window,
the endpoint returns **409 `ambiguous_request_id`**, without choosing one,
summing different attempts, or returning their details. Uniqueness is checked
within the window only; reusing an expired ID can resolve to a newer execution.
Only completed primary charges with the exact stored public request ID are
covered. Other endpoints are supported only when they persist that identity and
key/issuer attribution. Related child IDs and archived records are not followed.

## Authentication

The inference key can read only its own charges attributed to its originating
account in the same NanoGPT tenant. Team-paid charges remain visible to the originating actor's
key; team ownership or membership does not grant broader access. Missing or
inconsistent historical attribution can make a charge unavailable.

Revoked/expired keys, deleted/merged issuers, and different keys cannot retrieve
the original key's charges. Rotation does not transfer access. Authentication is
fresh and existing key Origin restrictions apply. Use `Authorization` or
`x-api-key`; cookies, management credentials and partner tokens grant no access.
Conflicting credentials are rejected; equivalent supported prefix/case forms
are accepted.

## Polling and errors

Make the first lookup about two seconds after a disconnect or completion. A 404
includes `Retry-After: 30`: wait **at least 30 seconds**, plus a small random
delay, before the next lookup. Honor `Retry-After` on 429 and 503 responses too;
do not cap a larger server-requested delay at 30 seconds. For a network failure
without a response, back off with jitter from two seconds up to 30 seconds.

Stop on 200. Stop and correct the request or seek support on 400, 401, 403 or 409;
do not automatically rerun inference to resolve a billing lookup error. This API
does not expose a `finalized` flag and clients do not need to keep polling for
later refunds. Clients are responsible for polling and honoring retry delays.

The shared budgets are **60 lookups/minute per key** and **300/minute per trusted
IP**, including unsuccessful lookups. Coordinate polling across concurrent
requests. If no charge appears, stop retries no later than 24 hours after the
original request and retain its ID for support. This is a retry limit, not a
promise that every billing record will become available within 24 hours.

| Status | Meaning |
| - | - |
| 200 | One recorded primary charge, with exact cost, currency, tokens and expiry. |
| 400 | Invalid request ID, unsupported query parameters, or conflicting credentials. |
| 401 / 403 | Credential, issuer or key-policy rejection; stop and correct access. |
| 404 | No eligible charge visible to this key. May be delayed, expired, inaccessible or absent; never assume zero cost. Wait at least the indicated 30 seconds before retrying. |
| 409 | Multiple eligible primary charges match this ID; do not automatically retry or infer a total. |
| 429 | Quota exceeded; honor `Retry-After`. |
| 503 | The billing lookup is temporarily unavailable; honor `Retry-After`. |

Every response uses `Cache-Control: private, no-store, max-age=0`, private/no-store
CDN headers and `Vary: Authorization, x-api-key`.

## Capture the ID before reading a stream

This JavaScript example saves the ID when the response headers arrive. Keep it
even if reading the body fails. `model` and `messages` are the values from your
normal chat request, and `apiKey` is your NanoGPT API key.

```js theme={null}
const response = await fetch('https://api.nano-gpt.com/api/v1/chat/completions', {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ model, messages, stream: true }),
});
const requestId = response.headers.get('x-request-id');
// Save requestId before consuming response.body with your SSE parser.
// If the stream disconnects, keep that ID and follow the polling guidance above.
```

Use the HTTP response header, not a completion ID from a JSON body or SSE event.
If the connection fails before headers arrive and no ID was captured, this
endpoint cannot identify that execution for you.

For a later lookup, use the same key and the captured ID:

```js theme={null}
if (requestId) {
  const lookup = await fetch(
    `https://api.nano-gpt.com/api/v1/usage/requests/${encodeURIComponent(requestId)}`,
    { headers: { Authorization: `Bearer ${apiKey}` } },
  );
  if (lookup.ok) {
    const billing = await lookup.json();
    // Preserve billing.cost as a decimal string, or use a decimal library.
  } else {
    // Handle lookup.status and lookup.headers.get('retry-after') as above.
  }
}
```

`Retry-After` may contain seconds or an HTTP date; respect its full delay.
For aggregate spend and refunds over a date range, use [Usage](/api-reference/endpoint/usage).


## OpenAPI

````yaml GET /v1/usage/requests/{request_id}
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
  /v1/usage/requests/{request_id}:
    get:
      tags:
        - Account
      summary: Retrieve a recorded primary request charge
      description: >-
        Look up one completed primary charge by captured X-Request-ID using the
        same inference API key. Uses database time and a rolling 24-hour window
        based on the charge accounting timestamp; no query parameters are
        accepted. Returns the exact recorded cost, currency, token usage and
        expiry. Refunds and separately billed extras are excluded; components
        already included in the primary amount remain included. Multiple
        eligible primary charges return 409 instead of selecting or summing
        attempts. No balance-collection or immutable net-cost guarantee is
        implied. A 404 never means zero cost: the charge may be delayed,
        expired, inaccessible or absent. All responses are private/no-store.
        Distributed quotas are 60/minute per key and 300/minute per trusted IP;
        required dependency failures return 503. Prefer a server-generated
        X-Request-ID captured from inference response headers. The ID is not an
        idempotency key; use a fresh ID for each inference execution, including
        retries. Make the first lookup after about two seconds; a 404 sends
        Retry-After: 30. Honor Retry-After on 404, 429 and 503, add jitter, stop
        on 200 or a permanent error, and stop retries no later than 24 hours
        after the original request. See
        https://docs.nano-gpt.com/api-reference/endpoint/request-billing for
        bounded polling.
      operationId: retrieveRequestBilling
      parameters:
        - name: request_id
          in: path
          required: true
          description: >-
            X-Request-ID captured from response headers before disconnect.
            Prefer omitting the incoming header so the server generates one.
            This is not an idempotency key: use a distinct ID for each inference
            execution, including retries; repeated IDs may return 409.
          schema:
            type: string
            minLength: 1
            maxLength: 128
            pattern: ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$
      responses:
        '200':
          description: >-
            One recorded primary charge from the last 24 hours. All responses
            use private/no-store and Vary: Authorization, x-api-key.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBilling'
              example:
                object: request_billing
                request_id: req_example
                created_at: '2026-09-17T10:00:01.000000Z'
                expires_at: '2026-09-18T10:00:01.000000Z'
                as_of: '2026-09-17T10:00:05.000000Z'
                cost: '0.00123456'
                currency: USD
                cost_scope: primary_charge
                usage:
                  input_tokens: 123
                  output_tokens: 45
                  reasoning_tokens: null
        '400':
          description: >-
            Invalid request ID, unsupported query parameters, or conflicting
            credentials.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
        '401':
          description: Missing or invalid inference API key or originating account.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
        '403':
          description: API key policy rejects access.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
        '404':
          description: >-
            No eligible charge is visible to this key. It may be delayed,
            expired, inaccessible, or absent; never assume zero cost.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
          headers:
            Retry-After:
              description: >-
                Wait at least this delay before retrying. A 404 returns 30
                seconds; honor larger delays too.
              schema:
                type: string
              example: '30'
        '409':
          description: >-
            Multiple eligible primary charges match: ambiguous_request_id. No
            charge is selected or summed.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
        '429':
          description: Lookup rate limit exceeded. Honor Retry-After.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
          headers:
            Retry-After:
              description: >-
                Wait at least this delay before retrying. A 404 returns 30
                seconds; honor larger delays too.
              schema:
                type: string
              example: '30'
        '503':
          description: Billing lookup temporarily unavailable. Honor Retry-After.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RequestBillingError'
          headers:
            Retry-After:
              description: >-
                Wait at least this delay before retrying. A 404 returns 30
                seconds; honor larger delays too.
              schema:
                type: string
              example: '30'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    RequestBilling:
      type: object
      additionalProperties: false
      required:
        - object
        - request_id
        - created_at
        - expires_at
        - as_of
        - cost
        - currency
        - cost_scope
        - usage
      properties:
        object:
          type: string
          const: request_billing
        request_id:
          type: string
          minLength: 1
          maxLength: 128
          pattern: ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$
        created_at:
          type: string
          format: date-time
          description: Ledger accounting timestamp; not necessarily insertion time.
        expires_at:
          type: string
          format: date-time
          description: >-
            24 hours after the charge accounting timestamp. The record is
            unavailable at or after this instant; financial records are
            retained.
        as_of:
          type: string
          format: date-time
          description: Database statement snapshot time.
        cost:
          type: string
          pattern: ^\d{1,80}(?:\.\d{1,40})?$
          maxLength: 121
          description: >-
            Exact nonnegative amount recorded on the primary charge. Does not
            subtract refunds or add separately billed extras; not proof of
            balance collection.
        currency:
          type: string
          enum:
            - USD
            - XNO
        cost_scope:
          type: string
          const: primary_charge
        usage:
          type: object
          additionalProperties: false
          required:
            - input_tokens
            - output_tokens
            - reasoning_tokens
          properties:
            input_tokens:
              type:
                - integer
                - 'null'
              minimum: 0
              maximum: 9007199254740991
              description: >-
                Recorded accounting count, possibly estimated. Null preserves
                absent, invalid or unsafe-sized values.
            output_tokens:
              type:
                - integer
                - 'null'
              minimum: 0
              maximum: 9007199254740991
              description: >-
                Recorded accounting count, possibly estimated. Null preserves
                absent, invalid or unsafe-sized values.
            reasoning_tokens:
              type:
                - integer
                - 'null'
              minimum: 0
              maximum: 9007199254740991
              description: >-
                Recorded accounting count, possibly estimated. Null preserves
                absent, invalid or unsafe-sized values.
    RequestBillingError:
      type: object
      required:
        - error
      properties:
        error:
          type: object
          required:
            - message
          properties:
            message:
              type: string
            type:
              type: string
            code:
              type: string
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