> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Video Generation

> Generate videos using supported text-to-video, image-to-video, and video-to-video models. The response includes a runId and pending status; poll the status endpoint for completion. See the docs for the current model list and required inputs.

> Image-conditioned models accept either `imageDataUrl` (base64) or a public `imageUrl`. The service uses the explicit value you provide before checking any saved attachments.

## Overview

`POST /generate-video` submits an asynchronous job to create, extend, or edit a video. The endpoint responds immediately with `runId`, `id`, `model`, and `status: "pending"`. `runId` and `id` are the same NanoGPT job identifier (format `vid_...`). Poll the unified Video Status endpoint with that job ID until you receive final assets. Duration-based billing is assessed after completion.

Errors include descriptive JSON payloads. Surface the `error.message` (and HTTP status) to help users correct content-policy or validation issues.

## Extend Workflows

* **Midjourney extend (task-based)**: use `POST /api/generate-video/extend` with `runId` (preferred) or `taskId` (legacy alias) plus `index` (0-3). This flow does not accept `video`, `videoUrl`, `videoDataUrl`, or `videoAttachmentId`.
* **Source video extend (extend models)**: use `POST /api/generate-video` with an extend model plus `prompt` and a source video (`videoUrl`, `videoDataUrl`, or `videoAttachmentId`). `video` is only accepted by select models (for example, `wan-wavespeed-25-extend`). Max source video length: 120 seconds.

## Request Schema

Only include the fields required by your chosen `model`. Unknown keys are ignored, but some models fail when extra media fields are present.

### Core Fields

| field | type | required | details |
| - | - | - | - |
| `model` | string | yes | Video model ID. Model availability changes; discover models via `GET /api/v1/models?detailed=true`. |
| `conversationUUID` | string | no | Attach the request to a conversation thread. |
| `prompt` | string | conditional | Required for text-to-video and edit models unless a structured script is supplied. |
| `negative_prompt` | string | no | Suppresses specific content. Respected by Veo, Wan, Runway, Pixverse, and other models noted below. |
| `script` | string | conditional | LongStories models accept full scripts instead of relying on `prompt`. |
| `storyConfig` | object | conditional | LongStories structured payload (e.g. scenes, narration, voice). |
| `animation` | boolean | no | Enables animation for LongStories outputs. |
| `language` | string | no | Output language for LongStories. |
| `characters` | array | no | Character definitions for LongStories. |
| `duration` | string | conditional | Seconds as a string (`"5"`, `"8"`, `"60"`). Limits vary per model; see individual entries. |
| `seconds` | string | conditional | Sora-specific duration selector (`"4"`, `"8"`, `"12"`). |
| `aspect_ratio` | string | conditional | Ratios such as `16:9`, `9:16`, `1:1`, `3:4`, `4:3`, `21:9`, `auto`. |
| `orientation` | string | conditional | `landscape` or `portrait` for Sora and Wan text/image flows. |
| `resolution` | string | conditional | Resolution tokens (`480p`, `580p`, `720p`, `1080p`, `1792x1024`, `2k`, `4k`). |
| `size` | string | conditional | Output size preset (supported by select models). |
| `mode` | string | no | Operation mode: `text-to-video`, `image-to-video`, `reference-to-video`, `video-edit`. |
| `generateAudio` | boolean | no | Adds AI audio on Veo 3 and Lightricks models. Defaults to `false`. |
| `enhancePrompt` | boolean | no | Optional Veo 3 prompt optimizer. Defaults to `false`. |
| `pro_mode` / `pro` | boolean | no | High-quality toggle for Sora and Hunyuan families. Defaults to `false`. |
| `enable_prompt_expansion` | boolean | no | Prompt booster for Wan/Seedance/Minimax variants. Disabled by default. |
| `enable_safety_checker` | boolean | no | Optional safety checker toggle (supported by select models). |
| `camera_fix` / `camera_fixed` / `cameraFixed` | boolean | no | Locks the virtual camera for Seedance and Wan variants. |
| `seed` | number or string | no | Optional seed forwarded on model/provider routes that support it. This may improve reproducibility but does not guarantee identical output. |
| `voiceId` | string | conditional | Alternate voice selector for lipsync models. |
| `voice_id` | string | conditional | Required by `kling-lipsync-t2v`. |
| `voice_language` | string | conditional | `en` or `zh` for `kling-lipsync-t2v`. |
| `voice_speed` | number | conditional | Range `0.8-2.0` for `kling-lipsync-t2v`. |
| `videoDuration` / `billedDuration` | number | no | Optional overrides for upscaler billing calculations. |
| `adjust_fps_for_interpolation` | boolean | no | Optional toggle for interpolation-aware upscaling. Defaults to `false`. |

### Media Inputs

| field | type | required | details |
| - | - | - | - |
| `imageDataUrl` | string | conditional | Base64-encoded data URL. Recommended for private assets or files larger than 4 MB. |
| `imageUrl` | string | conditional | HTTPS link to a source image. |
| `imageAttachmentId` | string | conditional | Reference to a library-stored image. |
| `image` | string | conditional | Alternate image field accepted by select models. Prefer `imageUrl` unless the model explicitly requires `image`. |
| `reference_image` | string | conditional | Optional still image guiding `runwayml-gen4-aleph`. |
| `referenceImages` | array | conditional | Multiple reference images for reference-to-video flows. |
| `referenceVideos` | array | conditional | Multiple reference videos. |
| `audioDataUrl` | string | conditional | Base64 data URL for audio-driven models. |
| `audioDuration` | number | conditional | Duration of provided audio in seconds. |
| `audioUrl` | string | conditional | HTTPS audio input. |
| `audio` | string | conditional | Alternate audio field accepted by select models. Prefer `audioUrl` unless the model explicitly requires `audio`. |
| `videoUrl` | string | conditional | HTTPS link to a source video (edit, extend, upscaler, or lipsync jobs). |
| `videoDataUrl` | string | conditional | Base64 data URL for a source video. |
| `video` | string | conditional | Alternate video field accepted by select models. Prefer `videoUrl` unless the model explicitly requires `video`. |
| `videoAttachmentId` | string | conditional | Reference to a library-stored video. |
| `swapImage` | string | conditional | Swap image (face-swap models). |
| `targetVideo` | string | conditional | Target video (face-swap models). |
| `targetFaceIndex` | number | no | Optional face index (face-swap models). |

> Provide only the media fields that your target model expects. Extra media inputs often trigger validation errors.
> Prefer `videoUrl` (camelCase) for source videos; only send `video` when the model explicitly requires it.

### Advanced Controls

| field | type | models |
| - | - | - |
| `num_frames` | integer | Wan 2.2 families, Seedance 22 5B, Wan image-to-video. |
| `frames_per_second` | integer | Wan 2.2 5B. |
| `num_inference_steps` | integer | Wan 2.2 families. |
| `guidance_scale` | number | Wan 2.2 5B. |
| `shift` | number | Wan 2.2 5B. |
| `interpolator_model` | string | Wan 2.2 5B. |
| `num_interpolated_frames` | integer | Wan 2.2 5B. |
| `movementAmplitude` | string | Select models (for example `auto`, `small`, `medium`, `large`). |
| `motion` | string | Select models (for example `low`, `high`). |
| `style` | string | Select models (style/preset strings). |
| `effectType`, `effect`, `cameraMovement`, `motionMode`, `soundEffectSwitch`, `soundEffectPrompt` | varies | Pixverse v4.5/v5. |
| `mode` | string | Select models (for example `animate`, `replace`). |
| `prompt_optimizer` | boolean | Select models. |

## Model Discovery

Video model IDs and supported fields change over time. Use `GET /api/v1/models?detailed=true` to discover the current list and select a model intended for video generation.

Notes:

* Different models accept different media inputs (for example `imageUrl` vs a source `videoUrl`) and may support different duration / resolution options.
* If you see validation errors, first retry with only the minimal required fields for your chosen model.

## Async Processing & Status Polling

* The submission response includes `{ runId, id, model, status: "pending" }` where `id` and `runId` are identical.
* Poll `/api/video/status?requestId=<runId>` (or `runId`) until the job reaches `status: "COMPLETED"` or `status: "FAILED"`. The legacy `/api/generate-video/status` endpoint is deprecated.
* Many jobs emit intermediate states (`queued`, `processing`, `generating`, `delivering`). Persist them if you need audit trails.
* Failed jobs include an `error` object. Surface the message and adjust prompts or inputs before retrying.
* Duration and resolution determine credit usage.

### Response example

```json theme={null}
{
  "runId": "vid_m1abc123def456",
  "id": "vid_m1abc123def456",
  "status": "pending",
  "model": "veo2-video",
  "cost": 0.35,
  "paymentSource": "XNO",
  "remainingBalance": 12.5,
  "prechargeLabel": "string"
}
```

## Content & Safety Notes

Some models may block prompts that violate content policies. Non-200 responses describe the violation reason; relay these messages verbatim to users or implement automated prompt adjustments.

## Next Steps

* Poll the Video Status endpoint after every submission to retrieve final assets.
* Keep customer-facing pricing tables in sync with the API behavior you observe in production.


## OpenAPI

````yaml POST /generate-video
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
  /generate-video:
    post:
      description: >-
        Generate videos using supported text-to-video, image-to-video, and
        video-to-video models. The response includes a runId and pending status;
        poll the status endpoint for completion. See the docs for the current
        model list and required inputs.
      requestBody:
        description: Parameters for video generation across different models and providers
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/VideoGenerationRequest'
        required: true
      responses:
        '202':
          description: >-
            Video generation request submitted successfully (asynchronous
            processing)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/VideoGenerationResponse'
        '400':
          description: Bad Request - Invalid parameters or safety filter triggered
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '500':
          description: Server Error - Video generation failed
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - apiKeyAuth: []
components:
  schemas:
    VideoGenerationRequest:
      type: object
      required:
        - model
      properties:
        model:
          type: string
          description: >-
            The video model to use for generation. See the docs for the current
            model list and required inputs.
        prompt:
          type: string
          description: Text prompt describing the video to generate
          example: A serene lake at sunset with gentle ripples on the water
        script:
          type: string
          description: >-
            Fully-written script for LongStories models (takes precedence over
            prompt)
        conversationUUID:
          type: string
          description: UUID for conversation tracking
        projectId:
          type: string
          description: Project identifier for LongStories models
        framework:
          type: string
          description: Story framework for LongStories models
          enum:
            - default
            - emotional_story
            - product_showcase
            - tutorial
          default: default
        shortRequestEnhancer:
          type: boolean
          description: >-
            Smart Enhancement: if true, automatically choose better framework
            and add Director Notes if necessary
          default: false
        targetLengthInWords:
          type: integer
          description: Target length in words for LongStories models (legacy parameter)
          default: 70
        targetLengthInSeconds:
          type: integer
          description: Target length in seconds (alternative to words)
        directorNotes:
          type: string
          description: >-
            Prompt for the image generation engine (LongStories). Example: 'Warm
            lighting' or 'Make the first image very impactful'
          example: Warm, cozy lighting with focus on people interacting
        aspectRatio:
          type: string
          description: Video aspect ratio for LongStories
          enum:
            - '9:16'
            - '16:9'
          default: '9:16'
        scriptConfig:
          type: object
          description: Script generation configuration for LongStories
          properties:
            style:
              type: string
              description: Sets the tone & voice of the generated script
              enum:
                - default
                - no_style
                - engaging_conversational
                - dixit_biography
                - kind_biography
                - hero_journey
                - emotional_story
                - dramatic_reveal
                - heartwarming_stories
                - educational_history
                - news_brief
              default: default
            targetLengthInSeconds:
              type: integer
              description: >-
                Approx. time length of the script in seconds. The actual length
                may vary slightly.
              minimum: 5
              maximum: 600
              default: 30
        imageConfig:
          type: object
          description: Image generation configuration for LongStories
          properties:
            model:
              type: string
              description: Which image model to use for generating images
              enum:
                - flux_schnell
                - flux_lora
                - flux_pro
                - flux_pro_ultra
                - flux-kontext
                - recraft
                - sdxl
                - sdxl_lora
                - sd35_large
                - sd35_medium
                - sd35_large_turbo
                - leonardo_flux_precision
                - leonardo_phoenix_quality
                - leonardo_phoenix_ultra
                - reve-v1
                - hidream_fast
                - hidream_dev
                - hidream_full
                - gpt_image_1
                - imagen4_preview
                - midjourney
              default: hidream_dev
            loraConfig:
              type: object
              description: Style configuration (only applies when using Flux LoRA model)
              properties:
                loraSlug:
                  type: string
                  description: Specialized style to apply
                  enum:
                    - ghibsky-comic-book
                    - colour-sketches
                    - sketch-paint
                    - 90s-anime
                    - 2000s-crime-thrillers
                    - xno-symbol-flux
                  default: ghibsky-comic-book
        videoConfig:
          type: object
          description: Video generation configuration for LongStories
          properties:
            enabled:
              type: boolean
              description: Generate video motion from images instead of using static images
              default: true
            model:
              type: string
              description: Which video model to use for motion generation
              enum:
                - ltx_video_13b_distilled
                - ltx_video
                - stable_video
                - motion
                - kling_v1_6_std_5s
                - kling_v2_1_std_5s
                - ltx_video_13b_dev
                - skyreels
                - vidu
                - kling_v1_6_std_10s
                - kling_v2_1_std_10s
                - kling_v2_1_pro_5s
                - luma_ray2
                - kling_pro_5s
                - minimax
                - wan_i2v
                - motion_2
                - kling_v2_1_pro_10s
                - wan_pro
                - luma_ray2_hd
                - kling_pro_10s
                - kling_v2_1_master_5s
                - kling_v2_master_5s
                - veo2
                - kling_v2_1_master_10s
                - kling_v2_master_10s
              default: kling_v2_1_std_5s
        voiceoverConfig:
          type: object
          description: Voiceover configuration for LongStories
          properties:
            enabled:
              type: boolean
              description: Enable AI voiceover for the video
              default: true
            voiceId:
              type: string
              description: Voice for video narration
              enum:
                - 9BWtsMINqrJLrRacOk9x
                - CwhRBWXzGAHq8TQ4Fs17
                - EXAVITQu4vr4xnSDxMaL
                - FGY2WhTYpPnrIDTdsKH5
                - IKne3meq5aSn9XLyUdCD
                - JBFqnCBsd6RMkjVDRZzb
                - N2lVS1w4EtoT3dr4eOWO
                - SAz9YHcvj6GT2YYXdXww
                - TX3LPaxmHKxFdv7VOQHJ
                - XB0fDUnXU5powFXDhCwa
                - Xb7hH8MSUJpSbSDYk0k2
                - XrExE9yKIg1WjnnlVkGX
                - bIHbv24MWmeRgasZH58o
                - cgSgspJ2msm6clMCkdW9
                - cjVigY5qzO86Huf0OWal
                - nPczCjzI2devNBz1zQrb
                - onwK4e9ZLuTAKqWW03F9
                - pqHfZKP75CvOlQylNhV4
                - pFZP5JQG7iQjIQuC4Bku
                - KHCvMklQZZo0O30ERnVn
                - Nh2zY9kknu6z4pZy6FhD
                - LlZr3QuzbW4WrPjgATHG
                - YExhVa4bZONzeingloMX
                - m1VE7dnwBN0zMer3LcKv
                - zWDA589rUKXuLnPRDtAG
                - YYHkBdgrAwQWIaH6m2ai
              default: zWDA589rUKXuLnPRDtAG
        captionsConfig:
          type: object
          description: Captions configuration for LongStories
          properties:
            captionsEnabled:
              type: boolean
              description: Show text captions in the video
              default: true
            captionsStyle:
              type: string
              description: Style of video captions
              enum:
                - default
                - minimal
                - neon
                - cinematic
                - fancy
                - tiktok
                - highlight
                - gradient
                - intellectual
                - vida
                - manuscripts
                - subtitle
                - modern
                - bounce
                - popcorn
                - typewriter
                - handwritten
                - karaoke
                - retro
                - gaming
              default: tiktok
        effectsConfig:
          type: object
          description: Effects configuration for LongStories
          properties:
            transition:
              type: string
              description: Transition style between different images
              enum:
                - fade
                - random
                - slide
                - wipe
                - flip
                - none
              default: fade
            floating:
              type: boolean
              description: Make the images move around slightly with floating effects
              default: true
        musicConfig:
          type: object
          description: Music configuration for LongStories
          properties:
            enabled:
              type: boolean
              description: Add background music to the video
              default: true
            musicSlug:
              type: string
              description: Choose background music for your video
              enum:
                - ''
                - temple_of_treasures
                - gentle_ambient_loop
                - serene_ambience
                - soothing_ambience
                - soothing_ambient_backdrop
                - tranquil_ambience
                - dreamscape
                - belonging_resonance
                - vivid_memories
                - cinematic_intro
                - cinematic_teaser
                - dramatic_cinematic_score
                - thriller_cinema_trailer
                - fractured_paintings
                - promise_of_tomorrow
                - spooky_orchestral_theme
                - light_upbeat_melody
                - puzzle_time
                - stomping_drums_rhythm
                - stomps_and_claps_rhythm_track
                - news_theme
                - adventurous_intro
                - burlesque_sweetheart
                - highway_nocturne_national_sweetheart
                - haptic_sensation
              default: gentle_ambient_loop
            volume:
              type: number
              description: Volume level for background music
              minimum: 0
              maximum: 1
              default: 0.3
            loop:
              type: boolean
              description: Whether to loop the background music
              default: true
        voice:
          type: string
          description: 'Legacy: Voice ID for narration (use voiceoverConfig.voiceId instead)'
          example: pNInz6obpgDQGcFmaJgB
        captionsShow:
          type: boolean
          description: >-
            Legacy: Whether to show captions (use captionsConfig.captionsEnabled
            instead)
          default: true
        captionsStyle:
          type: string
          description: >-
            Legacy: Style for captions (use captionsConfig.captionsStyle
            instead)
          enum:
            - default
            - minimal
            - neon
            - cinematic
            - fancy
            - tiktok
            - highlight
            - gradient
            - instagram
            - vida
            - manuscripts
          default: default
        effects:
          type: object
          description: 'Legacy: Video effects configuration (use effectsConfig instead)'
          properties:
            transition:
              type: string
              default: fade
            floating:
              type: boolean
              default: false
        quality:
          type: string
          description: 'Legacy: Video quality (handled by videoConfig now)'
          enum:
            - low
            - medium
            - high
          default: medium
        motion:
          type: object
          description: 'Legacy: Motion configuration (handled by videoConfig now)'
          properties:
            enabled:
              type: boolean
              default: false
            strength:
              type: integer
              minimum: 1
              maximum: 10
              default: 3
        music:
          type: string
          description: 'Legacy: Music track (use musicConfig instead)'
          example: video-creation/music/dramatic_cinematic_score.mp3
        duration:
          oneOf:
            - type: string
            - type: integer
          description: >-
            Video duration (format varies by model - '5s' for Veo2, '5' for
            Kling, etc.)
          example: 5s
        aspect_ratio:
          type: string
          description: Aspect ratio (supported by select models)
          enum:
            - '16:9'
            - '9:16'
            - '1:1'
            - '4:3'
            - '3:4'
          default: '16:9'
        negative_prompt:
          type: string
          description: Negative prompt to avoid certain elements
          example: blur, distort, and low quality
        cfg_scale:
          type: number
          description: Classifier-free guidance scale
          minimum: 0
          maximum: 20
          default: 0.5
        imageDataUrl:
          type: string
          description: >-
            Base64 data URL of input image for image-to-video models. Aliases
            `image_data_url` and `image` are also accepted and normalized.
          example: data:image/jpeg;base64,/9j/4AAQ...
        imageUrl:
          type: string
          description: >-
            Public HTTPS URL of the input image (interchangeable with
            imageDataUrl). The service will prioritize whichever field you
            supply before falling back to library attachments.
          example: https://images.unsplash.com/photo-1504196606672-aef5c9cefc92?w=1024
        imageAttachmentId:
          type: string
          description: Library attachment ID for input image
        videoUrl:
          type: string
          description: >-
            Public HTTPS URL of the input video (extend/edit/upscale). Preferred
            field name for source videos.
        videoDataUrl:
          type: string
          description: Base64 data URL of the input video.
        video:
          type: string
          description: Alternate video field accepted by select providers.
        videoAttachmentId:
          type: string
          description: Library attachment ID for input video.
        prompt_optimizer:
          type: boolean
          description: Whether to optimize the prompt (MiniMax model)
          default: true
        num_inference_steps:
          type: integer
          description: Number of inference steps
          minimum: 1
          maximum: 50
          default: 30
        pro_mode:
          type: boolean
          description: Enable pro mode for Hunyuan Video
          default: false
        resolution:
          type: string
          description: Video resolution
          enum:
            - 720p
            - 1080p
            - 540p
          default: 720p
        num_frames:
          oneOf:
            - type: integer
            - type: string
          description: Number of frames to generate
          default: 81
        frames_per_second:
          type: integer
          description: Frames per second
          minimum: 5
          maximum: 24
          default: 16
        seed:
          type: integer
          description: >-
            Optional seed forwarded on model/provider routes that support it.
            This may improve reproducibility but does not guarantee identical
            output.
        enable_safety_checker:
          type: boolean
          description: Enable safety content filtering
          default: true
        showExplicitContent:
          type: boolean
          description: Allow explicit content (inverse of safety checker)
          default: false
        enable_prompt_expansion:
          type: boolean
          description: Enable automatic prompt expansion
        acceleration:
          type: boolean
          description: Enable acceleration for faster processing
        shift:
          type: number
          description: Shift parameter for certain models
        age_slider:
          type: integer
          description: Age setting for PromptChan model
          minimum: 18
          maximum: 60
          default: 18
        audioEnabled:
          type: boolean
          description: Enable audio for PromptChan model
          default: false
        video_quality:
          type: string
          description: Video quality for PromptChan model
          enum:
            - Standard
            - High
          default: Standard
        aspect:
          type: string
          description: Aspect setting for PromptChan model
          enum:
            - Portrait
            - Landscape
            - Square
          default: Portrait
    VideoGenerationResponse:
      type: object
      required:
        - runId
        - status
        - model
      properties:
        runId:
          type: string
          description: Unique identifier for the video generation request
        projectId:
          type: string
          description: Project identifier (for LongStories models)
        status:
          type: string
          description: Current status of the generation
          enum:
            - pending
            - processing
            - completed
            - failed
          default: pending
        model:
          type: string
          description: The model used for generation
        cost:
          type: number
          description: Cost of the video generation
        paymentSource:
          type: string
          description: Payment source used (USD or XNO)
        remainingBalance:
          type: number
          description: Remaining balance after the generation
        prechargeLabel:
          type: string
          description: Provider label for the precharge
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