> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Text-to-Speech

> Convert text into natural-sounding speech using various TTS models from different providers. Supports multiple languages, voices, and customization options including speed control, voice instructions, and audio format selection.

## Overview

Convert text into natural-sounding speech using various TTS models. Supports multiple languages, voices, and customization options including speed control and voice instructions.

Looking for synchronous, low‑latency TTS that returns audio bytes directly? See [Speech](/api-reference/endpoint/speech) (POST `/v1/audio/speech`).

Want to clone a custom voice from a reference audio clip? See [Voice Cloning](/api-reference/endpoint/voice-cloning).

## Supported Models

* **Kokoro-82m**: 44 multilingual voices (\$0.001/1k chars)
* **Elevenlabs-Turbo-V2.5**: Premium quality with style controls (\$0.06/1k chars)
* **tts-1**: OpenAI standard quality (\$0.015/1k chars)
* **tts-1-hd**: OpenAI high definition (\$0.030/1k chars)
* **gpt-4o-mini-tts**: Ultra-low cost (\$0.0006/1k chars)
* **MiniMax Speech models**: Supports cloned voices via custom voice IDs (see [Voice Cloning](/api-reference/endpoint/voice-cloning))
* **Qwen-3-TTS-1.7B**: Supports cloned voices via speaker embeddings (see [Voice Cloning](/api-reference/endpoint/voice-cloning))

## Basic Usage

<CodeGroup>
  ```python Python theme={null}
  import requests

  def text_to_speech(text, model="Kokoro-82m", voice=None, **kwargs):
      headers = {
          "x-api-key": "YOUR_API_KEY",
          "Content-Type": "application/json"
      }
      
      payload = {
          "text": text,
          "model": model
      }
      
      if voice:
          payload["voice"] = voice
      
      payload.update(kwargs)
      
      response = requests.post(
          "https://api.nano-gpt.com/api/tts",
          headers=headers,
          json=payload
      )
      
      if response.status_code == 200:
          content_type = response.headers.get('content-type', '')
          
          if 'application/json' in content_type:
              # JSON response with audio URL
              data = response.json()
              audio_response = requests.get(data['audioUrl'])
              with open('output.wav', 'wb') as f:
                  f.write(audio_response.content)
          else:
              # Binary audio data (OpenAI models)
              with open('output.mp3', 'wb') as f:
                  f.write(response.content)
          
          return response
      else:
          raise Exception(f"Error: {response.status_code}")

  # Basic usage
  text_to_speech(
      "Hello! Welcome to our service.",
      model="Kokoro-82m",
      voice="af_bella"
  )
  ```

  ```javascript JavaScript theme={null}
  async function textToSpeech(text, options = {}) {
      const payload = {
          text: text,
          model: options.model || 'Kokoro-82m',
          ...options
      };
      
      const response = await fetch('https://api.nano-gpt.com/api/tts', {
          method: 'POST',
          headers: {
              'x-api-key': 'YOUR_API_KEY',
              'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
      });
      
      if (response.ok) {
          const contentType = response.headers.get('content-type');
          
          if (contentType.includes('application/json')) {
              const data = await response.json();
              console.log('Audio URL:', data.audioUrl);
              return data;
          } else {
              // Binary audio data
              const audioBlob = await response.blob();
              const url = URL.createObjectURL(audioBlob);
              console.log('Audio blob URL:', url);
              return { audioBlob, url };
          }
      } else {
          throw new Error(`Error: ${response.status}`);
      }
  }

  // Usage
  textToSpeech('Hello world!', {
      model: 'Kokoro-82m',
      voice: 'af_bella',
      speed: 1.1
  });
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/tts \
    -H "x-api-key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "text": "Hello! Welcome to our service.",
      "model": "Kokoro-82m",
      "voice": "af_bella",
      "speed": 1.0
    }'
  ```
</CodeGroup>

## Async Status and Result Retrieval

Some TTS models run asynchronously. When queued, the API returns HTTP 202 with a ticket containing a `runId` and `model`. Use the TTS Status endpoint to poll until the job is complete. Synchronous models return audio immediately and do not require status polling.

### Endpoints

* Submit TTS: `POST /api/tts`
* Check TTS Status (async only): `GET /api/tts/status?runId=...&model=...`

### When you see status: "pending"

If your initial `POST /api/tts` returns HTTP 202 with a body like:

```json theme={null}
{
  "status": "pending",
  "runId": "98b0d593-fe8d-49b8-89c9-233022232297",
  "model": "Elevenlabs-Turbo-V2.5",
  "charged": true,
  "cost": 0.0050388,
  "paymentSource": "USD",
  "isApiRequest": true
}
```

…the request is queued. Poll the Status endpoint using the `runId` and `model`. If present, include `cost`, `paymentSource`, and `isApiRequest` from the ticket when polling to help with automatic refunds if the upstream provider later rejects content.

### cURL — Submit, then Poll

<CodeGroup>
  ```bash cURL theme={null}
  # 1) Submit TTS
  curl -X POST https://api.nano-gpt.com/api/tts \
    -H 'x-api-key: YOUR_API_KEY' \
    -H 'Content-Type: application/json' \
    -d '{
      "text": "Hello there!",
      "model": "Elevenlabs-Turbo-V2.5",
      "voice": "Rachel",
      "speed": 1.0
    }'

  # 2) If response is 202/pending, poll using returned values
  curl "https://api.nano-gpt.com/api/tts/status?runId=98b0d593-fe8d-49b8-89c9-233022232297&model=Elevenlabs-Turbo-V2.5&cost=0.0050388&paymentSource=USD&isApiRequest=true" \
    -H 'x-api-key: YOUR_API_KEY'

  # 3) On completion, you'll receive an audioUrl
  # {
  #   "status": "completed",
  #   "audioUrl": "https://.../file.mp3",
  #   "contentType": "audio/mpeg",
  #   "model": "Elevenlabs-Turbo-V2.5"
  # }
  ```

  ```javascript JavaScript theme={null}
  async function submitTTS({ text, model = 'Elevenlabs-Turbo-V2.5', voice = 'Rachel', speed = 1 }) {
    const res = await fetch('https://api.nano-gpt.com/api/tts', {
      method: 'POST',
      headers: {
        'x-api-key': 'YOUR_API_KEY',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ text, model, voice, speed })
    });

    if (res.status === 202) {
      const ticket = await res.json();
      return await pollTTSStatus(ticket);
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'TTS request failed');
    }

    // Synchronous: either JSON with URL or binary audio
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      const json = await res.json();
      return json.audioUrl;
    }

    const blob = await res.blob();
    return URL.createObjectURL(blob); // play via <audio src={...}>
  }

  async function pollTTSStatus({ runId, model, cost, paymentSource, isApiRequest }) {
    const maxAttempts = 60; // ~3 minutes at 3s interval
    const intervalMs = 3000;

    for (let i = 0; i < maxAttempts; i++) {
      const qs = new URLSearchParams({ runId, model });
      if (typeof cost === 'number') qs.set('cost', String(cost));
      if (paymentSource) qs.set('paymentSource', String(paymentSource));
      if (typeof isApiRequest === 'boolean') qs.set('isApiRequest', String(isApiRequest));

      const res = await fetch(`https://api.nano-gpt.com/api/tts/status?${qs.toString()}`, {
        headers: { 'x-api-key': 'YOUR_API_KEY' }
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Polling failed (${res.status})`);
      }

      const data = await res.json();
      if (data.status === 'completed' && data.audioUrl) return data.audioUrl;
      if (data.status === 'error') throw new Error(data.error || 'TTS generation failed');

      await new Promise(r => setTimeout(r, intervalMs));
    }

    throw new Error('Polling timeout');
  }
  ```
</CodeGroup>

### Synchronous vs. Asynchronous Models

* Synchronous models (examples: `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts`, `Kokoro-82m`) return immediately from `POST /api/tts` with either binary audio or JSON containing `{ audioUrl, contentType }` depending on the provider.
* Asynchronous models (examples: `Elevenlabs-Turbo-V2.5`, `Elevenlabs-V3`, `Elevenlabs-Music-V1`) return HTTP 202 with a polling ticket. Use `GET /api/tts/status` until completed.

For OpenAI-compatible music generation via `POST /api/v1/audio/speech`, see [Music Generation](/api-reference/music-generation).

### Best Practices

* Poll every 2–3 seconds; stop after 2–3 minutes and show a timeout error.
* Always include `runId` and `model`. If available, include `cost`, `paymentSource`, and `isApiRequest` from the ticket for better error handling and refund automation.
* On `completed`, prefer using the `audioUrl` directly (streaming or download). Cache URLs client‑side if you plan to replay.
* If you receive `CONTENT_POLICY_VIOLATION`, do not retry the same content; surface a clear message to the user.

### FAQ

* Why did I get 202/pending? The selected model runs asynchronously; your request was queued and billed after a successful queue submission.
* Can I cancel a pending TTS? Not currently. Let it complete or time out client‑side.
* Do all TTS models require polling? No. Only async models. Synchronous models return immediately.

## Model-Specific Examples

### Kokoro-82m - Multilingual Voices

44 voices across 13 language groups:

<CodeGroup>
  ```python Python theme={null}
  # Popular voice examples by category
  voices = {
      "american_female": ["af_bella", "af_nova", "af_aoede"],
      "american_male": ["am_adam", "am_onyx", "am_eric"],
      "british_female": ["bf_alice", "bf_emma"],
      "british_male": ["bm_daniel", "bm_george"],
      "japanese_female": ["jf_alpha", "jf_gongitsune"],
      "chinese_female": ["zf_xiaoxiao", "zf_xiaoyi"],
      "french_female": ["ff_siwis"],
      "italian_male": ["im_nicola"]
  }

  # Generate multilingual samples
  samples = [
      {"text": "Hello, welcome!", "voice": "af_bella", "lang": "English"},
      {"text": "Bonjour et bienvenue!", "voice": "ff_siwis", "lang": "French"},
      {"text": "こんにちは！", "voice": "jf_alpha", "lang": "Japanese"},
      {"text": "你好，欢迎！", "voice": "zf_xiaoxiao", "lang": "Chinese"}
  ]

  for sample in samples:
      text_to_speech(
          text=sample["text"],
          model="Kokoro-82m",
          voice=sample["voice"]
      )
  ```
</CodeGroup>

### Elevenlabs-Turbo-V2.5 - Advanced Voice Controls

Premium quality with style adjustments:

<CodeGroup>
  ```python Python theme={null}
  # Stable, consistent voice
  text_to_speech(
      text="This is a professional announcement.",
      model="Elevenlabs-Turbo-V2.5",
      voice="Rachel",
      stability=0.9,
      similarity_boost=0.8,
      style=0
  )

  # Expressive, dynamic voice  
  text_to_speech(
      text="This is so exciting!",
      model="Elevenlabs-Turbo-V2.5",
      voice="Rachel",
      stability=0.3,
      similarity_boost=0.7,
      style=0.8,
      speed=1.2
  )

  # Available voices: Rachel, Adam, Bella, Brian, etc.
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/tts \
    -H "x-api-key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "text": "Welcome to our premium service!",
      "model": "Elevenlabs-Turbo-V2.5",
      "voice": "Rachel",
      "stability": 0.7,
      "similarity_boost": 0.8,
      "style": 0.3
    }'
  ```
</CodeGroup>

### OpenAI Models - Multiple Formats & Instructions

<CodeGroup>
  ```python Python theme={null}
  # High-definition with voice instructions
  text_to_speech(
      text="Welcome to customer service.",
      model="tts-1-hd",
      voice="nova",
      instructions="Speak warmly and professionally like a customer service representative",
      response_format="flac"
  )

  # Ultra-low cost option
  text_to_speech(
      text="This is a cost-effective option.",
      model="gpt-4o-mini-tts",
      voice="alloy",
      instructions="Speak clearly and cheerfully",
      response_format="mp3"
  )

  # Different format examples
  formats = ["mp3", "wav", "opus", "flac", "aac"]
  for fmt in formats:
      text_to_speech(
          text=f"This is {fmt.upper()} format.",
          model="tts-1",
          voice="echo",
          response_format=fmt
      )
  ```

  ```bash cURL theme={null}
  # With voice instructions
  curl -X POST https://api.nano-gpt.com/api/tts \
    -H "x-api-key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "text": "Breaking news update!",
      "model": "tts-1-hd",
      "voice": "nova",
      "instructions": "Speak with the urgency of a news reporter",
      "response_format": "wav"
    }'

  # Ultra-low cost
  curl -X POST https://api.nano-gpt.com/api/tts \
    -H "x-api-key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "text": "Budget-friendly text-to-speech.",
      "model": "gpt-4o-mini-tts",
      "voice": "alloy"
    }'
  ```
</CodeGroup>

## Response Examples

### JSON Response (Most Models)

```json theme={null}
{
  "audioUrl": "https://storage.url/audio-file.wav",
  "contentType": "audio/wav",
  "model": "Kokoro-82m",
  "text": "Hello world",
  "voice": "af_bella",
  "speed": 1,
  "duration": 2.3,
  "cost": 0.001,
  "currency": "USD"
}
```

### Binary Response (OpenAI Models)

OpenAI models return audio data directly as binary with appropriate headers:

```http theme={null}
Content-Type: audio/mp3
Content-Length: 123456
[Binary audio data]
```

## Voice Options

### Kokoro-82m Voices

* **American Female**: af\_bella, af\_nova, af\_aoede, af\_jessica, af\_sarah
* **American Male**: am\_adam, am\_onyx, am\_eric, am\_liam
* **British**: bf\_alice, bf\_emma, bm\_daniel, bm\_george
* **Asian Languages**: jf\_alpha (Japanese), zf\_xiaoxiao (Chinese)
* **European**: ff\_siwis (French), im\_nicola (Italian)

### Elevenlabs-Turbo-V2.5 Voices

Rachel, Adam, Bella, Brian, Sarah, Michael, Emily, James, Nicole, and 37 more

### OpenAI Voices

alloy, echo, fable, onyx, nova, shimmer, ash, ballad, coral, sage, verse

## Error Handling

<CodeGroup>
  ```python Python theme={null}
  try:
      result = text_to_speech("Hello world!", model="Kokoro-82m")
      print("Success!")
  except Exception as e:
      if "400" in str(e):
          print("Bad request - check parameters")
      elif "401" in str(e):
          print("Unauthorized - check API key")
      elif "413" in str(e):
          print("Text too long for model")
      else:
          print(f"Error: {e}")
  ```
</CodeGroup>

Common errors:

* **400**: Invalid parameters or missing text
* **401**: Invalid or missing API key
* **413**: Text exceeds model character limit
* **429**: Rate limit exceeded


## OpenAPI

````yaml POST /tts
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
  /tts:
    post:
      description: >-
        Convert text into natural-sounding speech using various TTS models from
        different providers. Supports multiple languages, voices, and
        customization options including speed control, voice instructions, and
        audio format selection.
      requestBody:
        description: Text-to-speech generation parameters
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TTSRequest'
        required: true
      responses:
        '200':
          description: >-
            Text-to-speech response. Returns either JSON with audio URL or
            binary audio data depending on the model.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TTSResponse'
            audio/mp3:
              schema:
                type: string
                format: binary
                description: Binary audio data (for OpenAI models)
            audio/wav:
              schema:
                type: string
                format: binary
                description: Binary audio data
            audio/opus:
              schema:
                type: string
                format: binary
                description: Binary audio data (OpenAI models)
            audio/aac:
              schema:
                type: string
                format: binary
                description: Binary audio data (OpenAI models)
            audio/flac:
              schema:
                type: string
                format: binary
                description: Binary audio data (OpenAI models)
        '400':
          description: Bad Request - Invalid parameters or missing text
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '402':
          description: Payment Required - Insufficient balance
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '413':
          description: Payload Too Large - Text exceeds model limits
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '429':
          description: Too Many Requests - Rate limit exceeded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '500':
          description: Internal Server Error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '501':
          description: Not Implemented - Model not yet implemented
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - apiKeyAuth: []
components:
  schemas:
    TTSRequest:
      type: object
      required:
        - text
      properties:
        text:
          type: string
          description: The text to convert to speech
          example: Hello! This is a test of the text-to-speech API.
        model:
          type: string
          description: The TTS model to use for generation
          enum:
            - Kokoro-82m
            - Elevenlabs-Turbo-V2.5
            - tts-1
            - tts-1-hd
            - gpt-4o-mini-tts
            - Minimax-Speech-02-HD
            - Minimax-Speech-2.6-HD
            - Minimax-Speech-2.6-Turbo
            - Minimax-Speech-2.8-HD
            - Minimax-Speech-2.8-Turbo
            - Qwen-3-TTS-1.7B
          default: Kokoro-82m
        voice:
          type: string
          description: >-
            The voice to use for synthesis (available voices depend on selected
            model)
          example: af_bella
        speaker_voice_embedding_file_url:
          type: string
          description: >-
            Speaker embedding file URL for Qwen TTS voice cloning
            (Qwen-3-TTS-1.7B only)
        reference_text:
          type: string
          description: Optional transcript of the reference clip (Qwen TTS)
        language:
          type: string
          description: >-
            Language hint (Qwen TTS). Example values: Auto, English, Chinese,
            Japanese
        prompt:
          type: string
          description: Optional style prompt (Qwen TTS)
        speed:
          type: number
          description: Speech speed multiplier (0.1-5, not supported for gpt-4o-mini-tts)
          minimum: 0.1
          maximum: 5
          default: 1
        response_format:
          type: string
          description: Audio output format (OpenAI models only)
          enum:
            - mp3
            - opus
            - aac
            - flac
            - wav
            - pcm
          default: mp3
        instructions:
          type: string
          description: >-
            Voice instructions for fine-tuning (gpt-4o-mini-tts and tts-1-hd
            only)
          example: speak with enthusiasm
        stability:
          type: number
          description: Voice stability (Elevenlabs-Turbo-V2.5 only, 0-1)
          minimum: 0
          maximum: 1
          default: 0.5
        similarity_boost:
          type: number
          description: Voice similarity boost (Elevenlabs-Turbo-V2.5 only, 0-1)
          minimum: 0
          maximum: 1
          default: 0.75
        style:
          type: number
          description: Style exaggeration (Elevenlabs-Turbo-V2.5 only, 0-1)
          minimum: 0
          maximum: 1
          default: 0
    TTSResponse:
      type: object
      properties:
        audioUrl:
          type: string
          format: uri
          description: URL to the generated audio file
          example: https://storage.url/audio-file.wav
        contentType:
          type: string
          description: MIME type of the audio file
          example: audio/wav
        model:
          type: string
          description: Model used for generation
        text:
          type: string
          description: The input text that was synthesized
        voice:
          type: string
          description: Voice used for synthesis
        speed:
          type: number
          description: Speed multiplier used
        duration:
          type: number
          description: Duration of the generated audio in seconds
        cost:
          type: number
          description: Cost of the generation
        currency:
          type: string
          description: Currency of the cost
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