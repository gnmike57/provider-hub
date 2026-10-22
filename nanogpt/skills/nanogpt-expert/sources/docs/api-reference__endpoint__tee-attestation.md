> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# TEE Attestation

> Fetch TEE attestation report for a model

Fetch a TEE attestation report for a given model.


## OpenAPI

````yaml GET /v1/tee/attestation
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
  /v1/tee/attestation:
    servers:
      - url: https://api.nano-gpt.com
        description: Root server for TEE endpoints
    get:
      description: Fetch TEE attestation report for a model
      parameters:
        - name: model
          in: query
          description: TEE model to attest
          required: true
          schema:
            type: string
      responses:
        '200':
          description: TEE attestation report
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TEEAttestationResponse'
        '400':
          description: Bad Request
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized
        '500':
          description: Server Error
      security:
        - bearerAuth: []
components:
  schemas:
    TEEAttestationResponse:
      type: object
      properties:
        attestation:
          type: string
          description: The attestation report
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
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.