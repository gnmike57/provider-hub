> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Check Balance

> Check the account balance



## OpenAPI

````yaml POST /check-balance
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
  /check-balance:
    post:
      description: Check the account balance
      responses:
        '200':
          description: Account balance information
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BalanceResponse'
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - apiKeyAuth: []
components:
  schemas:
    BalanceResponse:
      type: object
      properties:
        usd_balance:
          type: string
          description: Account balance in USD
          example: '129.46956147'
        nano_balance:
          type: string
          description: Account balance in Nano
          example: '26.71801147'
        nanoDepositAddress:
          type: string
          description: Nano deposit address for the account
          example: nano_1gx385nnj7rw67hsksa3pyxwnfr48zu13t35ncjmtnqb9zdebtjhh7ahks34
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