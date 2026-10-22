> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Image Generation (OpenAI-Compatible)

> Creates an image generation for the provided prompt (OpenAI-compatible). For unauthenticated accountless x402 quote requests, include x-x402: true.

## Overview

Generate images from text prompts or base64 image inputs using the OpenAI-compatible endpoint. Responses include base64 bytes (`b64_json`) by default or signed URLs (`url`) when `response_format: "url"`.

For new integrations that do not need OpenAI-compatible request shapes, use the dedicated [Image API](/api-reference/image-generation). It supports image model discovery, endpoint metadata, public pricing metadata, and normalized generation through `POST /api/v1/images`.

## Endpoint

* Method/Path: `POST https://api.nano-gpt.com/v1/images/generations`
* Auth: `Authorization: Bearer <API_KEY>`
* Required header: `Content-Type: application/json`

## Request Body (JSON)

Core fields:

* `prompt` (string, required): Text prompt to generate an image from.
* `model` (string, optional): Model ID (default `hidream`).
* `n` (integer, optional): Number of images to generate (default `1`).
* `size` (string, optional): Requested output size or model-specific resolution value. Use `GET /api/v1/image-models?detailed=true` and read `supported_parameters.resolutions` for the selected model's supported values.
* `response_format` (string, optional): `b64_json` (default) or `url`.
* `user` (string, optional): End-user identifier.

Image inputs (img2img/inpainting):

* `imageDataUrl` (string, optional): Base64 data URL for a single input image.
* `imageDataUrls` (array, optional): Multiple base64 data URLs for supported models.
* `maskDataUrl` (string, optional): Base64 mask data URL for inpainting.

Generation controls (model-specific):

* `strength`, `guidance_scale`, `num_inference_steps`, `kontext_max_mode`.
* `seed` is an optional model-specific hint that may improve reproducibility where supported. Identical results are not guaranteed. Check the selected model's `supported_parameters` metadata before using this field.

GPT Image output controls (`gpt-image-1`, `gpt-image-1.5`, `gpt-image-2`, and the GPT Image 2.5 Flare and Sunburst models):

* `quality` (string, optional): Model-specific quality level, for example `low`, `medium`, or `high`. GPT Image 2.5 also accepts `xhigh` and `max`.
* `output_format` (string, optional): `png`, `jpeg`, or `webp`.
* `output_compression` (integer, optional): `0`–`100`. Applies to `jpeg` and `webp` output only.
* `background` (string, optional, not supported by `gpt-image-2`): `auto` (default), `opaque`, or `transparent`. `transparent` requires `output_format` `png` or `webp`. If the prompt describes a backdrop, the model may draw it instead of leaving the background transparent. Requests with `opaque` or `transparent` are only routed to providers that support the setting, so they never fall back to one that would ignore it.

See [Supported Parameter Discovery](/api-reference/image-generation#supported-parameter-discovery) for the discovery workflow. If a model/provider route offers a stronger reproducibility guarantee, rely only on documentation for that specific route.

For OpenAI-compatible image editing, use [Image Edits](/api-reference/endpoint/image-edits).

## Response

* Each `data[i]` contains either `b64_json` (default) or `url` (when `response_format: "url"`), never both.
* When requesting `response_format: "url"`, the API may still return `b64_json` if URL generation (upload/presign) fails, as a fallback.
* Signed URLs expire after a short period (currently \~1 hour). Download promptly for long-term storage.

## Examples

<CodeGroup>
  ```bash cURL (basic) theme={null}
  curl https://api.nano-gpt.com/v1/images/generations \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "hidream",
      "prompt": "A sunset over a mountain range",
      "n": 1,
      "size": "1024x1024"
    }'
  ```

  ```bash cURL (response_format: "url") theme={null}
  curl https://api.nano-gpt.com/v1/images/generations \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "hidream",
      "prompt": "A neon city skyline at night",
      "n": 1,
      "size": "1024x1024",
      "response_format": "url"
    }'
  ```

  ```bash cURL (transparent background) theme={null}
  curl https://api.nano-gpt.com/v1/images/generations \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "openai/gpt-image-2.5/flare/text-to-image",
      "prompt": "A glossy red game controller icon, isolated object",
      "n": 1,
      "size": "1024x1024",
      "background": "transparent",
      "output_format": "png"
    }'
  ```

  ```python Python (img2img) theme={null}
  import base64
  import requests

  API_KEY = "YOUR_API_KEY"

  with open("input.jpg", "rb") as f:
      encoded = base64.b64encode(f.read()).decode("utf-8")
      image_data_url = f"data:image/jpeg;base64,{encoded}"

  response = requests.post(
      "https://api.nano-gpt.com/v1/images/generations",
      headers={
          "Authorization": f"Bearer {API_KEY}",
          "Content-Type": "application/json",
      },
      json={
          "model": "flux-kontext",
          "prompt": "Transform this image into a watercolor painting",
          "n": 1,
          "size": "1024x1024",
          "imageDataUrl": image_data_url,
      },
  )

  result = response.json()
  ```
</CodeGroup>

## Notes & Limits

* Input images must be provided as base64 data URLs; download and convert remote images before sending.
* Uploads should be 4 MB or smaller after encoding. Compress or resize large assets before sending.
* Use `GET /api/v1/image-models?detailed=true` to discover current image model capabilities and supported resolution values. For seed and other model-specific fields, also consult the [Image API supported-parameter guidance](/api-reference/image-generation#supported-parameter-discovery).


## OpenAPI

````yaml POST /v1/images/generations
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
  /v1/images/generations:
    servers:
      - url: https://api.nano-gpt.com
        description: Root server for OpenAI-compatible endpoints
    post:
      description: >-
        Creates an image generation for the provided prompt (OpenAI-compatible).
        For unauthenticated accountless x402 quote requests, include x-x402:
        true.
      parameters:
        - name: x-x402
          in: header
          description: >-
            Set to true on unauthenticated accountless x402 quote requests.
            Without this header, unauthenticated requests return 401
            missing_api_key.
          required: false
          schema:
            type: string
            enum:
              - 'true'
      requestBody:
        description: Parameters for image generation
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/OpenAIImageGenerationsRequest'
      responses:
        '200':
          description: >-
            Image generation response. Each data[i] contains either { url } or {
            b64_json }. When requesting response_format: "url", the API may fall
            back to returning { b64_json } if URL generation (upload/presign)
            fails.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OpenAIImageGenerationsResponse'
              examples:
                url:
                  summary: 'Example response (response_format: "url")'
                  value:
                    created: 123
                    data:
                      - url: https://...signed-url...
                    cost: 123
                    paymentSource: <string>
                    remainingBalance: 123
                b64_json:
                  summary: 'Example response (response_format: "b64_json")'
                  value:
                    created: 123
                    data:
                      - b64_json: <base64-encoded-image-bytes>
                    cost: 123
                    paymentSource: <string>
                    remainingBalance: 123
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '402':
          description: >-
            Payment Required - authenticated insufficient balance or opted-in
            accountless x402 quote
          content:
            application/json:
              schema:
                oneOf:
                  - $ref: '#/components/schemas/Error'
                  - $ref: '#/components/schemas/X402PaymentRequiredResponse'
      security:
        - bearerAuth: []
        - {}
components:
  schemas:
    OpenAIImageGenerationsRequest:
      type: object
      required:
        - prompt
      properties:
        model:
          type: string
          description: The model to use for generation
          default: hidream
        prompt:
          type: string
          description: The text prompt to generate an image from
        'n':
          type: integer
          description: Number of images to generate
          default: 1
        size:
          type: string
          description: >-
            Requested output size or model-specific resolution value. Use GET
            /api/v1/image-models?detailed=true and read
            supported_parameters.resolutions for the selected model's supported
            values.
          examples:
            - 1024x1024
            - 1376x768
            - auto
        response_format:
          type: string
          description: >-
            The format in which the generated images are returned. Use
            "b64_json" (default) to receive base64-encoded image bytes in
            data[i].b64_json, or "url" to receive a time-limited, signed
            download URL in data[i].url (expires after a short period, currently
            ~1 hour). Note: When requesting "url", the API may still return
            "b64_json" if URL generation (upload/presign) fails, as a fallback.
          enum:
            - url
            - b64_json
          default: b64_json
        user:
          type: string
          description: A unique identifier representing your end-user
        imageDataUrl:
          type: string
          description: >-
            Base64-encoded image data URL for img2img generation. Single image
            input for models that support image-to-image transformation. Format:
            data:image/[type];base64,[data]. Note: Direct URL input is not
            supported - images must be converted to base64 data URLs before
            submission.
          example: data:image/jpeg;base64,/9j/4AAQ...
        imageDataUrls:
          type: array
          description: >-
            Array of base64-encoded image data URLs for models supporting
            multiple image inputs (e.g., flux-kontext, gpt-4o-image,
            gpt-image-1). Each URL must follow the format:
            data:image/[type];base64,[data]
          items:
            type: string
            format: data-url
          example:
            - data:image/jpeg;base64,/9j/4AAQ...
            - data:image/png;base64,iVBORw0KGgo...
        maskDataUrl:
          type: string
          description: >-
            Base64-encoded mask image data URL for inpainting models (e.g.,
            flux-lora/inpainting). White areas indicate regions to edit. Format:
            data:image/[type];base64,[data]
          example: data:image/png;base64,iVBORw0KGgo...
        strength:
          type: number
          description: >-
            Controls how much the output differs from the input image in img2img
            mode. Lower values produce outputs closer to the input.
          minimum: 0
          maximum: 1
          default: 0.8
        guidance_scale:
          type: number
          description: >-
            How closely the model follows the text prompt. Higher values result
            in images more closely aligned with the prompt.
          minimum: 0
          maximum: 20
          default: 7.5
        num_inference_steps:
          type: integer
          description: >-
            Number of denoising steps. More steps generally produce higher
            quality but take longer.
          minimum: 1
          maximum: 100
          default: 30
        seed:
          type: integer
          description: >-
            Optional model-specific seed that may improve reproducibility where
            supported by the model/provider route. Identical results are not
            guaranteed. Check the selected model's supported_parameters metadata
            before using this field.
          example: 42
        kontext_max_mode:
          type: boolean
          description: >-
            Enable enhanced context mode for flux-kontext model. Provides better
            understanding of input images.
          default: false
    OpenAIImageGenerationsResponse:
      type: object
      properties:
        created:
          type: integer
          description: Unix timestamp of when the image was created
        data:
          type: array
          description: >-
            List of generated images. Each entry contains either a hosted URL
            (data[i].url) or base64-encoded bytes (data[i].b64_json), never
            both.
          items:
            oneOf:
              - type: object
                required:
                  - url
                properties:
                  url:
                    type: string
                    format: uri
                    description: >-
                      Time-limited, signed download URL (presigned URL) to the
                      generated image. It will expire after a short period
                      (currently ~1 hour). If you need long-term access,
                      download the image and store it yourself.
                additionalProperties: false
                example:
                  url: https://...signed-url...
              - type: object
                required:
                  - b64_json
                properties:
                  b64_json:
                    type: string
                    description: Base64 encoded image data
                additionalProperties: false
                example:
                  b64_json: <base64-encoded-image-bytes>
        cost:
          type: number
          description: Cost of the generation
        paymentSource:
          type: string
          description: Payment source used
        remainingBalance:
          type: number
          description: Remaining balance after the generation
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
    X402PaymentRequiredResponse:
      type: object
      description: >-
        402 Payment Required body for accountless x402. New clients should key
        off the top-level payment object; accepts is retained for backwards
        compatibility.
      additionalProperties: true
      properties:
        error:
          type: object
          additionalProperties: true
          properties:
            message:
              type: string
            type:
              type: string
            code:
              type: string
        payment:
          $ref: '#/components/schemas/X402PaymentQuote'
        x402Version:
          type: integer
          example: 1
        accepts:
          type: array
          items:
            $ref: '#/components/schemas/X402AcceptOption'
        requestHash:
          type: string
    X402PaymentQuote:
      type: object
      description: Canonical accountless x402 payment quote.
      additionalProperties: true
      properties:
        version:
          type: integer
          example: 1
        paymentId:
          type: string
          example: pay_abc123
        requestHash:
          type: string
          example: sha256:...
        expiresAt:
          type: string
          format: date-time
        amountUsd:
          type: string
          example: '0.0714'
        statusUrl:
          type: string
          format: uri
        completeUrl:
          type: string
          format: uri
        accepted:
          type: array
          items:
            $ref: '#/components/schemas/X402PaymentAcceptedOption'
    X402AcceptOption:
      type: object
      description: Legacy lower-level payment option offered in an x402 402 response.
      additionalProperties: true
      properties:
        scheme:
          type: string
        network:
          type: string
        asset:
          type: string
        resource:
          type: string
        description:
          type: string
        payTo:
          type: string
        paymentId:
          type: string
        expiresAt:
          type: integer
        callbackUrl:
          type: string
        completeUrl:
          type: string
        maxAmountRequired:
          type: string
        maxAmountRequiredFormatted:
          type: string
        maxAmountRequiredUSD:
          type: number
        mimeType:
          type: string
        extra:
          type: object
          additionalProperties: true
    X402PaymentAcceptedOption:
      type: object
      description: Normalized public accountless x402 payment option.
      additionalProperties: true
      properties:
        scheme:
          type: string
          enum:
            - nano
            - nano-exact
            - base-usdc
            - x402-exact
            - x402-solana-usdc
            - lightning-l402
        protocolScheme:
          type: string
        network:
          type: string
        asset:
          type: string
        amount:
          type: string
        amountFormatted:
          type: string
        amountUsd:
          type: string
        payTo:
          type: string
        invoice:
          type: string
          description: >-
            Lightning invoice for lightning-l402 quotes. Same value as payTo for
            most clients.
        paymentHash:
          type: string
          description: Lightning payment hash for lightning-l402 quotes.
        l402Token:
          type: string
          description: >-
            L402 token to pair with the Lightning payment preimage in
            Authorization: L402 <token>:<preimage>.
        discountRate:
          type: number
          description: Discount rate applied to this payment option when present.
        undiscountedAmountUsd:
          type: string
          description: Undiscounted USD quote amount when a discount is applied.
        feePayer:
          type: string
          description: >-
            Solana facilitator fee payer for x402-solana-usdc quotes. Copy from
            the quote; do not hardcode.
        paymentId:
          type: string
        statusUrl:
          type: string
          format: uri
        completeUrl:
          type: string
          format: uri
        expiresAt:
          type: string
          format: date-time
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.