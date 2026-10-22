> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# NSFW Image Classification

> Binary NSFW classification for up to 10 image URLs or data URLs per request

## Overview

The NSFW Image Classification endpoint performs **binary classification** on image URLs (or base64 data URLs) and returns whether each image contains NSFW concepts. Send up to **10 images per request**.

## Authentication

Include your API key in the request header:

```
x-api-key: YOUR_API_KEY
```

Alternatively, you can use Bearer token authentication:

```
Authorization: Bearer YOUR_API_KEY
```

## Request

### Headers

```
Content-Type: application/json
x-api-key: YOUR_API_KEY
```

### Body parameters

You may provide images in **any** of the following fields. The endpoint accepts **up to 10 images per request**.

| Parameter | Type | Required | Description |
| - | - | - | - |
| `image_urls` | string \| string\[] | No | Primary input field. One URL or an array of URLs. |
| `imageUrls` | string \| string\[] | No | Alias for `image_urls`. |
| `imageUrl` | string | No | Alias for a single image URL. |
| `imageDataUrl` | string | No | Base64 data URL for a single image. |
| `imageDataUrls` | string\[] | No | Base64 data URLs for multiple images. |
| `model` | string | No | Only supported value is `nsfw-classifier` (default). |

At least one image field is required. If more than 10 images are provided, only the **first 10** are processed and billed.

### Example request

```json theme={null}
{
  "image_urls": [
    "https://example.com/image-1.jpg",
    "https://example.com/image-2.jpg"
  ]
}
```

## Response

### Success (200)

```json theme={null}
{
  "model": "nsfw-classifier",
  "requestId": "<request-id>",
  "inputCount": 2,
  "cost": 0.003,
  "currency": "USD",
  "truncated": false,
  "has_nsfw_concepts": [false, true],
  "is_nsfw": true
}
```

### Response fields

* `model`: The classifier model used.
* `requestId`: Request ID (if available; helpful for support).
* `inputCount`: Number of images processed (max 10).
* `cost`: Final charged amount (after discounts and currency conversion).
* `currency`: `USD` or `XNO` depending on payment source.
* `truncated`: `true` if more than 10 images were provided.
* `has_nsfw_concepts`: List of booleans (one per image, in input order).
* `is_nsfw`: `true` if any image was flagged.

## Errors

### 400 – Invalid or policy violation

* Missing or invalid image URLs
* JSON parsing error
* Policy violation (returns a safety error message)

```json theme={null}
{ "error": "No valid image URLs provided" }
```

### 401 – Unauthorized

```json theme={null}
{ "error": "Unauthorized" }
```

### 429 – Rate limit or API key usage limits

```json theme={null}
{ "error": "Rate limit exceeded" }
```

### 500 – Server or provider failure

```json theme={null}
{ "error": "NSFW classification failed" }
```

## Billing Notes

* Charged **\$0.0015 per image** actually sent to the classifier.
* If more than 10 images are provided, only the **first 10** are billed/processed.
* Discounts and referral policies apply as with other endpoints.

## Code Examples

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/nsfw/image \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_API_KEY" \
    -d '{
      "image_urls": [
        "https://example.com/image-1.jpg",
        "https://example.com/image-2.jpg"
      ]
    }'
  ```

  ```python Python theme={null}
  import requests

  api_key = "YOUR_API_KEY"

  payload = {
      "image_urls": [
          "https://example.com/image-1.jpg",
          "https://example.com/image-2.jpg"
      ]
  }

  response = requests.post(
      "https://api.nano-gpt.com/api/nsfw/image",
      headers={
          "Content-Type": "application/json",
          "x-api-key": api_key
      },
      json=payload
  )

  print(response.json())
  ```

  ```javascript JavaScript theme={null}
  const apiKey = 'YOUR_API_KEY';

  const response = await fetch('https://api.nano-gpt.com/api/nsfw/image', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey
    },
    body: JSON.stringify({
      image_urls: [
        'https://example.com/image-1.jpg',
        'https://example.com/image-2.jpg'
      ]
    })
  });

  const data = await response.json();
  console.log(data);
  ```
</CodeGroup>


## OpenAPI

````yaml POST /nsfw/image
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
  /nsfw/image:
    post:
      description: Binary NSFW classification for image URLs or data URLs
      requestBody:
        description: NSFW image classification request
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/NsfwImageRequest'
        required: true
      responses:
        '200':
          description: NSFW classification response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NsfwImageResponse'
        '400':
          description: >-
            Bad Request - Invalid image URLs, JSON parsing error, or policy
            violation
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid session or API key
        '429':
          description: Too Many Requests - Rate limit exceeded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: Internal Server Error - NSFW classification failed
      security:
        - apiKeyAuth: []
        - bearerAuth: []
components:
  schemas:
    NsfwImageRequest:
      type: object
      description: NSFW image classification request payload
      properties:
        image_urls:
          description: >-
            Primary input field. One URL or an array of URLs (only the first 10
            are processed).
          oneOf:
            - type: string
              format: uri
              example: https://example.com/image.jpg
            - type: array
              items:
                type: string
                format: uri
              minItems: 1
              example:
                - https://example.com/image-1.jpg
                - https://example.com/image-2.jpg
        imageUrls:
          description: >-
            Alias for image_urls. One URL or an array of URLs (only the first 10
            are processed).
          oneOf:
            - type: string
              format: uri
              example: https://example.com/image.jpg
            - type: array
              items:
                type: string
                format: uri
              minItems: 1
        imageUrl:
          type: string
          format: uri
          description: Alias for a single image URL
          example: https://example.com/image.jpg
        imageDataUrl:
          type: string
          description: >-
            Base64 data URL for a single image (format:
            data:image/[type];base64,[data])
          example: data:image/jpeg;base64,/9j/4AAQ...
        imageDataUrls:
          type: array
          description: >-
            Base64 data URLs for multiple images (only the first 10 are
            processed)
          items:
            type: string
          minItems: 1
        model:
          type: string
          description: Only supported value is nsfw-classifier
          default: nsfw-classifier
    NsfwImageResponse:
      type: object
      properties:
        model:
          type: string
          description: The classifier model used
          example: nsfw-classifier
        requestId:
          type: string
          description: Request ID (if available; helpful for support)
        inputCount:
          type: integer
          description: Number of images processed (max 10)
          example: 2
        cost:
          type: number
          description: Final charged amount (after discounts and currency conversion)
          example: 0.003
        currency:
          type: string
          description: Currency of the charge
          example: USD
        truncated:
          type: boolean
          description: True if more than 10 images were provided
          example: false
        has_nsfw_concepts:
          type: array
          description: Per-image NSFW flags in input order
          items:
            type: boolean
          example:
            - false
            - true
        is_nsfw:
          type: boolean
          description: True if any image was flagged
          example: true
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
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.