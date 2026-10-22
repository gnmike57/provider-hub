> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Invitation

> Create an invitation or referral link with an optional credit amount.

## Overview

Create an invitation or referral link with an optional credit amount. Invitation links can include a fixed credit amount, while referral links always have a zero amount.

## Authentication

This endpoint supports two authentication methods:

* Session-based authentication (browser session cookie)
* API key authentication via request headers

### API Key Headers

* `x-api-key: YOUR_API_KEY` or
* `Authorization: Bearer YOUR_API_KEY`

## Request

### Headers

* `Content-Type: application/json`
* `x-api-key: YOUR_API_KEY` (required for API key auth)

### Body

| Field | Type | Required | Description |
| - | - | - | - |
| `type` | string | No | Either `"invitation"` or `"referralLink"`. Defaults to `"invitation"`. |
| `amount` | number | No | Credit amount to include with the invitation. Must be non-negative. Ignored for referral links (always 0). |
| `currency` | string | No | Currency for the amount. Required if `amount > 0`. Use `"USD"` for US dollars. |
| `recipientName` | string | No | Name of the invitation recipient. |
| `issuerName` | string | No | Name of the person sending the invitation. |
| `issuerNote` | string | No | Personal note to include with the invitation. |

## Response

### Success (200 OK)

```json theme={null}
{
  "insertId": "12345",
  "redeemCode": "ABC123XY",
  "url": "https://example.com/invite/ABC123XY",
  "type": "invitation",
  "amount": 10,
  "currency": "USD"
}
```

| Field | Type | Description |
| - | - | - |
| `insertId` | string | Database ID of the created invitation. |
| `redeemCode` | string | Unique code the recipient uses to redeem the invitation. |
| `url` | string | Full URL to share with the recipient. |
| `type` | string | The invitation type (`"invitation"` or `"referralLink"`). |
| `amount` | number | Credit amount attached to this invitation. |
| `currency` | string \| null | Currency of the amount, or `null` if amount is 0 (recipient chooses currency). |

## Errors

| Status | Body | Description |
| - | - | - |
| 400 | `"Invalid request body"` | Request body is not valid JSON. |
| 400 | `"InvalidAmount"` | The provided amount is negative. |
| 400 | `"InsufficientBalance"` | Your account balance is insufficient for the specified amount. |
| 401 | `"Invalid session"` | Session is missing required data. |
| 401 | `"Unable to get session"` | Authentication failed. |
| 500 | `"Failed to create invitation"` | Server error during invitation creation. |

## Notes

* When `amount` is 0 or not provided, the `currency` in the response is `null`, allowing the recipient to choose their preferred currency upon redemption.
* Referral links always have an amount of 0, regardless of what value is passed.
* The `redeemCode` uses a URL-safe alphabet that avoids ambiguous characters (no 0, O, 1, l).
* Ensure your account has sufficient balance before creating invitations with credit amounts.

## Examples

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST https://nano-gpt.com/api/invitations/create \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_API_KEY" \
    -d '{
      "amount": 10,
      "currency": "USD",
      "recipientName": "Jane Doe",
      "issuerName": "John Smith",
      "issuerNote": "Welcome to the platform!"
    }'
  ```

  ```bash cURL theme={null}
  curl -X POST https://nano-gpt.com/api/invitations/create \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_API_KEY" \
    -d '{
      "type": "referralLink",
      "issuerName": "John Smith"
    }'
  ```

  ```bash cURL theme={null}
  curl -X POST https://nano-gpt.com/api/invitations/create \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_API_KEY" \
    -d '{
      "recipientName": "Jane Doe"
    }'
  ```
</CodeGroup>


## OpenAPI

````yaml POST /invitations/create
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
  /invitations/create:
    post:
      description: Create an invitation or referral link with an optional credit amount.
      requestBody:
        description: Invitation creation parameters
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InvitationCreateRequest'
      responses:
        '200':
          description: Invitation created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InvitationCreateResponse'
        '400':
          description: >-
            Bad Request - Invalid request body, invalid amount, or insufficient
            balance
          content:
            text/plain:
              schema:
                type: string
        '401':
          description: Unauthorized - Invalid session or unable to get session
          content:
            text/plain:
              schema:
                type: string
        '500':
          description: Internal Server Error - Failed to create invitation
          content:
            text/plain:
              schema:
                type: string
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    InvitationCreateRequest:
      type: object
      properties:
        type:
          type: string
          description: Either "invitation" or "referralLink". Defaults to "invitation".
          enum:
            - invitation
            - referralLink
        amount:
          type: number
          description: >-
            Credit amount to include with the invitation. Must be non-negative.
            Ignored for referral links (always 0).
          minimum: 0
        currency:
          type: string
          description: Currency for the amount. Required if amount > 0.
        recipientName:
          type: string
          description: Name of the invitation recipient.
        issuerName:
          type: string
          description: Name of the person sending the invitation.
        issuerNote:
          type: string
          description: Personal note to include with the invitation.
    InvitationCreateResponse:
      type: object
      required:
        - insertId
        - redeemCode
        - url
        - type
        - amount
        - currency
      properties:
        insertId:
          type: string
          description: Database ID of the created invitation.
        redeemCode:
          type: string
          description: Unique code the recipient uses to redeem the invitation.
        url:
          type: string
          format: uri
          description: Full URL to share with the recipient.
        type:
          type: string
          description: The invitation type.
          enum:
            - invitation
            - referralLink
        amount:
          type: number
          description: Credit amount attached to this invitation.
        currency:
          type:
            - string
            - 'null'
          description: Currency of the amount, or null if amount is 0.
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