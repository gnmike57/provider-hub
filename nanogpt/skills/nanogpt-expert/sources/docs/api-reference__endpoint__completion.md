> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Completions

> Creates a completion for the provided prompt. This endpoint is available on a best-effort basis for legacy compatibility, and performance may be less consistent than /v1/chat/completions because not all upstream providers support the legacy completions API.

<Note>
  `POST /api/v1/completions` is available on a best-effort basis for legacy OpenAI compatibility. Performance and behavior may be less consistent than `POST /api/v1/chat/completions` because not all upstream providers support the legacy completions API.
</Note>

<Note>
  `POST /api/v1/completions` supports the same model suffix parser for provider routing (`:fast`, `:cheap`, etc.) and `:reasoning-exclude`, but this endpoint remains best-effort legacy compatibility. Prefer Chat Completions for new integrations. See [Model Suffixes](/api-reference/miscellaneous/model-suffixes).
</Note>

<Note>
  The body `provider` field accepts either the existing provider ID string or a structured routing object with fields such as `order`, `only`, `ignore`, `sort`, `max_price`, `allow_fallbacks`, and `require_parameters`. See [Provider Selection > Provider Routing Object](/api-reference/miscellaneous/provider-selection#provider-routing-object).
</Note>


## OpenAPI

````yaml POST /v1/completions
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
  /v1/completions:
    servers:
      - url: https://nano-gpt.com/api
        description: Website API (current model examples)
      - url: https://api.nano-gpt.com/api
        description: Direct API; choose a model listed by this host
    post:
      description: >-
        Creates a completion for the provided prompt. This endpoint is available
        on a best-effort basis for legacy compatibility, and performance may be
        less consistent than /v1/chat/completions because not all upstream
        providers support the legacy completions API.
      parameters:
        - name: X-Provider
          in: header
          description: >-
            Optional explicit provider override for supported open-source models
            (case-insensitive). Explicit provider selection is billed
            pay-as-you-go at the selected provider's price, including
            provider-selection markup; for subscription users it bypasses
            subscription coverage for that request.
          required: false
          schema:
            type: string
        - name: X-Billing-Mode
          in: header
          description: >-
            Optional billing override to force pay-as-you-go without an explicit
            provider, or to apply saved provider preferences to
            subscription-included traffic (e.g., paygo). Header name is
            case-insensitive.
          required: false
          schema:
            type: string
      requestBody:
        description: Parameters for text completion
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CompletionRequest'
        required: true
      responses:
        '200':
          description: Text completion response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CompletionResponse'
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - bearerAuth: []
components:
  schemas:
    CompletionRequest:
      type: object
      required:
        - model
        - prompt
      properties:
        model:
          type: string
          description: >-
            The model to use for completion. The model value may include
            supported model suffixes, including web search (':online',
            ':online/<provider>'), memory (':memory', ':memory-<days>'),
            reasoning visibility (':reasoning-exclude'), thinking variants where
            listed by the model catalog (':thinking'), and provider routing
            preferences for eligible models (':fast', ':cheap', ':caching',
            etc.).
          default: minimax/minimax-m2.7
          examples:
            - minimax/minimax-m2.7
            - zai-org/glm-5:fast
            - zai-org/glm-5:cheap
            - openai/gpt-6.1-sol:online/exa-instant
            - openai/gpt-6.1-sol:online/exa-deep-reasoning
        billing_mode:
          type: string
          description: >-
            Billing override to force pay-as-you-go without an explicit
            provider, or to apply saved provider preferences to
            subscription-included traffic. Accepted values (case-insensitive):
            paygo, pay-as-you-go, pay_as_you_go, paid, payg.
        billingMode:
          type: string
          description: Alias for billing_mode.
        provider:
          description: >-
            Optional provider override or structured provider routing controls
            for provider-selection-capable models. A string explicitly selects
            one provider. An object can set soft order, hard pins, exclusions,
            sort preference, price caps, fallback behavior, and
            parameter-capability requirements.
          oneOf:
            - type: string
              description: Provider ID or accepted provider display name/alias.
            - $ref: '#/components/schemas/ProviderRoutingObject'
        prompt:
          type: string
          description: The text prompt to complete
        max_tokens:
          type: integer
          description: >-
            Upper bound on generated tokens. If omitted, NanoGPT does not
            enforce an explicit default and the routed provider/model default
            applies
          minimum: 1
        temperature:
          type: number
          description: >-
            Classic randomness control. Accepts any decimal between 0-2. If
            omitted, NanoGPT does not force a value and the routed
            provider/model default applies
          minimum: 0
          maximum: 2
        top_p:
          type: number
          description: >-
            Nucleus sampling. When set below 1.0, trims candidate tokens to the
            smallest set whose cumulative probability exceeds top_p. Works well
            as an alternative to tweaking temperature
          minimum: 0
          maximum: 1
          default: 1
        stream:
          type: boolean
          description: Whether to stream the response
          default: false
        stop:
          description: >-
            Stop sequences. Accepts string or array of strings. Values are
            passed directly to upstream providers
          oneOf:
            - type: string
            - type: array
              items:
                type: string
        frequency_penalty:
          type: number
          description: >-
            Penalizes tokens proportionally to how often they appeared
            previously. Negative values encourage repetition; positive values
            discourage it
          minimum: -2
          maximum: 2
          default: 0
        presence_penalty:
          type: number
          description: >-
            Penalizes tokens based on whether they appeared at all. Good for
            keeping the model on topic without outright banning words
          minimum: -2
          maximum: 2
          default: 0
        repetition_penalty:
          type: number
          description: >-
            Provider-agnostic repetition modifier (distinct from OpenAI
            penalties). Values >1 discourage repetition
          minimum: -2
          maximum: 2
        top_k:
          type: integer
          description: Caps sampling to the top-k highest probability tokens per step
        top_a:
          type: number
          description: >-
            Combines top-p and temperature behavior; leave unset unless a model
            description explicitly calls for it
        min_p:
          type: number
          description: >-
            Ensures each candidate token probability exceeds a floor (0-1).
            Helpful for stopping models from collapsing into low-entropy loops
          minimum: 0
          maximum: 1
        tfs:
          type: number
          description: >-
            Tail free sampling. Values between 0-1 let you shave the long tail
            of the distribution; 1.0 disables the feature
          minimum: 0
          maximum: 1
        eta_cutoff:
          type: number
          description: >-
            Cut probabilities as soon as they fall below the specified tail
            threshold
        epsilon_cutoff:
          type: number
          description: >-
            Cut probabilities as soon as they fall below the specified tail
            threshold
        typical_p:
          type: number
          description: >-
            Typical sampling (aka entropy-based nucleus). Works like top_p but
            preserves tokens whose surprise matches the expected entropy
          minimum: 0
          maximum: 1
        mirostat_mode:
          type: integer
          description: >-
            Enables Mirostat sampling for models that support it. Set to 1 or 2
            to activate
          enum:
            - 0
            - 1
            - 2
        mirostat_tau:
          type: number
          description: >-
            Mirostat target entropy parameter. Used when mirostat_mode is
            enabled
        mirostat_eta:
          type: number
          description: Mirostat learning rate parameter. Used when mirostat_mode is enabled
        min_tokens:
          type: integer
          description: >-
            For providers that support it, enforces a minimum completion length
            before stop conditions fire
          default: 0
          minimum: 0
        stop_token_ids:
          type: array
          description: >-
            Numeric array that lets callers stop generation on specific token
            IDs. Not supported by many providers
          items:
            type: integer
        include_stop_str_in_output:
          type: boolean
          description: >-
            When true, keeps the stop sequence in the final text. Not supported
            by many providers
          default: false
        ignore_eos:
          type: boolean
          description: >-
            Allows completions to continue even if the model predicts EOS
            internally. Useful for long creative writing runs
          default: false
        no_repeat_ngram_size:
          type: integer
          description: >-
            Extension that forbids repeating n-grams of the given size. Not
            supported by many providers
          minimum: 0
        custom_token_bans:
          type: array
          description: List of token IDs to fully block
          items:
            type: integer
        logit_bias:
          type: object
          description: >-
            Object mapping token IDs to additive logits. Works just like
            OpenAI's version
          additionalProperties:
            type: number
        logprobs:
          description: >-
            When true or a number, forwards the request to providers that
            support returning token-level log probabilities
          oneOf:
            - type: boolean
            - type: integer
        prompt_logprobs:
          type: boolean
          description: >-
            Requests logprobs on the prompt itself when the upstream API allows
            it
        seed:
          type: integer
          description: >-
            Optional integer forwarded on model/provider routes that support
            seeded sampling. This may improve reproducibility but does not
            guarantee identical output. Results can change if NanoGPT selects a
            different automatic or fallback route, or if the provider changes
            its backend.
    CompletionResponse:
      type: object
      properties:
        id:
          type: string
          description: Unique identifier for the completion
        object:
          type: string
          description: Object type, always 'text_completion'
        created:
          type: integer
          description: Unix timestamp of when the completion was created
        model:
          type: string
          description: Model used for completion
        choices:
          type: array
          description: Array of completion choices
          items:
            type: object
            properties:
              text:
                type: string
                description: The completed text
              index:
                type: integer
                description: Index of the choice
              logprobs:
                type: object
                nullable: true
                description: Log probabilities of tokens (if requested)
              finish_reason:
                type: string
                description: Reason why the completion finished
                enum:
                  - stop
                  - length
                  - content_filter
        usage:
          type: object
          properties:
            prompt_tokens:
              type: integer
              description: Number of tokens in the prompt
            completion_tokens:
              type: integer
              description: Number of tokens in the completion
            total_tokens:
              type: integer
              description: Total number of tokens used
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
    ProviderRoutingObject:
      type: object
      description: >-
        Structured per-request provider routing controls. Per-request controls
        take precedence over saved provider preferences and are not merged with
        them.
      properties:
        order:
          type: array
          description: >-
            Soft provider preference order. NanoGPT tries these providers first
            when possible, but this does not hard-pin routing to only these
            providers. Unknown providers are ignored.
          items:
            type: string
        only:
          type: array
          description: >-
            Hard provider pin. NanoGPT restricts routing to these providers and
            fails instead of silently routing elsewhere. Unknown providers
            return a structured 400 error with code provider_unknown_provider.
          items:
            type: string
        ignore:
          type: array
          description: Providers to exclude from routing. Unknown providers are ignored.
          items:
            type: string
        sort:
          type: string
          description: >-
            Routing preference. speed, throughput, latency, and price actively
            request that strategy. auto, none, and default are accepted to
            suppress stored/default routing preferences without requesting a
            provider sort.
          enum:
            - speed
            - throughput
            - latency
            - price
            - auto
            - none
            - default
        quantizations:
          type: array
          description: >-
            Hard allowlist of model weight quantization levels. Providers
            without matching known quantization metadata are excluded unless
            unknown is included explicitly.
          minItems: 1
          items:
            type: string
            enum:
              - int4
              - fp4
              - fp6
              - int8
              - fp8
              - fp16
              - bf16
              - fp32
              - unknown
        min_quantization:
          type: string
          description: >-
            Minimum model weight quantization precision floor. Quantizations are
            ordered by bit width; integer and floating-point formats with the
            same bit width are treated as equivalent. unknown is not valid
            because it cannot be compared to a precision floor.
          enum:
            - int4
            - fp4
            - fp6
            - int8
            - fp8
            - fp16
            - bf16
            - fp32
        max_price:
          type: object
          description: >-
            Optional provider price caps in USD per 1 million tokens. Pricing
            checks are best-effort when provider pricing is unknown.
          properties:
            prompt:
              type: number
              description: Maximum prompt/input price in USD per 1 million tokens.
              minimum: 0
            completion:
              type: number
              description: Maximum completion/output price in USD per 1 million tokens.
              minimum: 0
        allow_fallbacks:
          type: boolean
          description: When false, disables cross-provider fallback for this request.
        require_parameters:
          type: boolean
          description: >-
            When true, requires the selected provider to support the requested
            parameters on routes that support parameter-level capability checks.
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.