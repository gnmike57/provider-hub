> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Speech-to-Text Transcription

> Transcribe audio (and supported video formats) into text using speech recognition models. Supports multiple languages, diarization (model-dependent), and various formats. Most models return synchronous results; some models (for example Elevenlabs-STT and voice cloning workflows) return asynchronous job IDs.

## Overview

The Speech-to-Text transcription endpoint converts audio files into text using state-of-the-art speech recognition models. Supports multiple languages, speaker diarization, and various audio formats.

Looking for a drop-in OpenAI-compatible STT endpoint? Use `POST /api/v1/audio/transcriptions`. See `api-reference/endpoint/audio-transcriptions.mdx`.

## Supported Models

* **Whisper-Large-V3**: High-accuracy transcription (\~\$0.0005/min) - Synchronous
* **Wizper**: Fast and efficient transcription (\$0.01/min) - Synchronous
* **Elevenlabs-STT**: Premium transcription with diarization (\$0.03/min) - Asynchronous
* **gpt-4o-mini-transcribe**: Efficient OpenAI transcription (\$0.003/min) - Synchronous
* **gpt-4o-mini-transcribe-2025-03-20**: Snapshot (\$0.003/min) - Synchronous
* **gpt-4o-mini-transcribe-2025-12-15**: Snapshot (\$0.003/min) - Synchronous
* **gpt-4o-mini-transcribe-latest**: Alias (\$0.003/min) - Synchronous
* **openai-whisper-with-video**: Video-to-text transcription (\$0.06/min) - Synchronous
* **qwen-voice-clone**: Voice cloning (\$0.25/run) - Asynchronous
* **minimax-voice-clone**: Voice cloning (\$1.00/run) - Asynchronous

## Upload Methods

### Direct File Upload (≤3MB)

<CodeGroup>
  ```python Python theme={null}
  import requests

  def transcribe_file(file_path):
      headers = {"x-api-key": "YOUR_API_KEY"}
      
      with open(file_path, 'rb') as audio_file:
          files = {'audio': ('audio.mp3', audio_file, 'audio/mpeg')}
          data = {
              'model': 'Whisper-Large-V3',
              'language': 'en'
          }
          
          response = requests.post(
              "https://api.nano-gpt.com/api/transcribe",
              headers=headers,
              files=files,
              data=data
          )
          
          return response.json()

  result = transcribe_file("meeting.mp3")
  print(result['transcription'])
  ```

  ```javascript JavaScript theme={null}
  const formData = new FormData();
  formData.append('audio', audioFile);
  formData.append('model', 'Whisper-Large-V3');
  formData.append('language', 'auto');

  const response = await fetch('https://api.nano-gpt.com/api/transcribe', {
      method: 'POST',
      headers: {
          'x-api-key': 'YOUR_API_KEY'
      },
      body: formData
  });

  const result = await response.json();
  console.log(result.transcription);
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/transcribe \
    -H "x-api-key: YOUR_API_KEY" \
    -F "audio=@meeting.mp3" \
    -F "model=Whisper-Large-V3" \
    -F "language=en"
  ```
</CodeGroup>

### URL Upload (≤500MB)

<CodeGroup>
  ```python Python theme={null}
  import requests

  def transcribe_url(audio_url):
      headers = {
          "x-api-key": "YOUR_API_KEY",
          "Content-Type": "application/json"
      }
      
      data = {
          "audioUrl": audio_url,
          "model": "Wizper",
          "language": "auto"
      }
      
      response = requests.post(
          "https://api.nano-gpt.com/api/transcribe",
          headers=headers,
          json=data
      )
      
      return response.json()

  result = transcribe_url("https://example.com/audio.mp3")
  print(result['transcription'])
  ```

  ```javascript JavaScript theme={null}
  const response = await fetch('https://api.nano-gpt.com/api/transcribe', {
      method: 'POST',
      headers: {
          'x-api-key': 'YOUR_API_KEY',
          'Content-Type': 'application/json'
      },
      body: JSON.stringify({
          audioUrl: 'https://example.com/audio.mp3',
          model: 'Wizper',
          language: 'auto'
      })
  });

  const result = await response.json();
  console.log(result.transcription);
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/transcribe \
    -H "x-api-key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "audioUrl": "https://example.com/audio.mp3",
      "model": "Wizper",
      "language": "auto"
    }'
  ```
</CodeGroup>

## Advanced Features - Speaker Diarization

Use Elevenlabs-STT for speaker identification (asynchronous processing):

<CodeGroup>
  ```python Python theme={null}
  import requests
  import time

  def transcribe_with_speakers(audio_url):
      headers = {
          "x-api-key": "YOUR_API_KEY",
          "Content-Type": "application/json"
      }
      
      # Submit transcription job
      data = {
          "audioUrl": audio_url,
          "model": "Elevenlabs-STT",
          "diarize": True,
          "tagAudioEvents": True
      }
      
      response = requests.post(
          "https://api.nano-gpt.com/api/transcribe",
          headers=headers,
          json=data
      )
      
      if response.status_code == 202:
          job_data = response.json()
          
          # Poll for results
          status_data = {
              "runId": job_data['runId'],
              "cost": job_data.get('cost'),
              "paymentSource": job_data.get('paymentSource'),
              "isApiRequest": True
          }
          
          while True:
              status_response = requests.post(
                  "https://api.nano-gpt.com/api/transcribe/status",
                  headers=headers,
                  json=status_data
              )
              
              result = status_response.json()
              if result.get('status') == 'completed':
                  return result
              elif result.get('status') == 'failed':
                  raise Exception(f"Transcription failed: {result.get('error')}")
              
              time.sleep(5)

  result = transcribe_with_speakers("https://example.com/meeting.mp3")

  # Access speaker segments
  for segment in result['diarization']['segments']:
      print(f"{segment['speaker']}: {segment['text']}")
  ```
</CodeGroup>

## Language Support

Supports 97+ languages with auto-detection:

```python theme={null}
# Common language codes
languages = {
    "auto": "Auto-detect",
    "en": "English", 
    "es": "Spanish",
    "fr": "French",
    "de": "German", 
    "zh": "Chinese",
    "ja": "Japanese",
    "ar": "Arabic"
}
```

## Response Examples

### Synchronous Response (most models)

```json theme={null}
{
  "transcription": "Hello, this is a test transcription.",
  "metadata": {
    "fileName": "audio.mp3",
    "fileSize": 1234567,
    "chargedDuration": 2.5,
    "actualDuration": 2.5,
    "language": "en",
    "cost": 0.0012,
    "currency": "USD",
    "model": "Whisper-Large-V3"
  }
}
```

### Asynchronous Response (Elevenlabs-STT and voice cloning)

Initial response (202):

```json theme={null}
{
  "runId": "abc123def456",
  "status": "pending",
  "model": "Elevenlabs-STT",
  "cost": 0.075,
  "paymentSource": "USD"
}
```

Final response (when completed):

```json theme={null}
{
  "status": "completed",
  "transcription": "Speaker 1: Hello everyone. Speaker 2: Hi there!",
  "metadata": { ... },
  "diarization": {
    "segments": [
      {
        "speaker": "Speaker 1",
        "text": "Hello everyone",
        "start": 0.5,
        "end": 1.5
      }
    ]
  },
  "words": [
    {
      "text": "Hello",
      "start": 0.5,
      "end": 0.9,
      "type": "word",
      "speaker_id": "speaker_0"
    }
  ]
}
```


## OpenAPI

````yaml POST /transcribe
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
  /transcribe:
    post:
      description: >-
        Transcribe audio (and supported video formats) into text using speech
        recognition models. Supports multiple languages, diarization
        (model-dependent), and various formats. Most models return synchronous
        results; some models (for example Elevenlabs-STT and voice cloning
        workflows) return asynchronous job IDs.
      requestBody:
        description: >-
          Audio transcription parameters. Use multipart/form-data for file
          uploads or application/json for URL-based requests.
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/TranscribeFormRequest'
          application/json:
            schema:
              $ref: '#/components/schemas/TranscribeJsonRequest'
        required: true
      responses:
        '200':
          description: Synchronous transcription response (Whisper/Wizper models)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TranscribeResponse'
        '202':
          description: Asynchronous transcription job started (Elevenlabs-STT model)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TranscribeAsyncResponse'
        '400':
          description: Bad Request - Invalid parameters or file format
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
          description: Payload Too Large - File exceeds size limit
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
      security:
        - apiKeyAuth: []
components:
  schemas:
    TranscribeFormRequest:
      type: object
      properties:
        audio:
          type: string
          format: binary
          description: >-
            Direct file upload (max 3MB). Supported formats: MP3, WAV, M4A, OGG,
            AAC
        audioUrl:
          type: string
          format: uri
          description: >-
            URL to audio file (alternative to direct upload, supports up to
            500MB)
        model:
          type: string
          description: The STT model to use for transcription
          enum:
            - Whisper-Large-V3
            - Wizper
            - Elevenlabs-STT
            - gpt-4o-mini-transcribe
            - gpt-4o-mini-transcribe-2025-03-20
            - gpt-4o-mini-transcribe-2025-12-15
            - gpt-4o-mini-transcribe-latest
            - openai-whisper-with-video
            - qwen-voice-clone
            - minimax-voice-clone
          default: Whisper-Large-V3
        language:
          type: string
          description: >-
            Language code for transcription (ISO 639-1 or ISO 639-3). Use 'auto'
            for auto-detection
          default: auto
          example: en
        actualDuration:
          type: string
          description: Actual audio duration in minutes for accurate billing
        diarize:
          type: string
          description: Enable speaker diarization (Elevenlabs-STT only)
          enum:
            - 'true'
            - 'false'
          default: 'false'
        tagAudioEvents:
          type: string
          description: >-
            Tag non-speech audio events like [laughter], [applause]
            (Elevenlabs-STT only)
          enum:
            - 'true'
            - 'false'
          default: 'false'
    TranscribeJsonRequest:
      type: object
      properties:
        audioUrl:
          type: string
          format: uri
          description: URL to audio file to transcribe
          example: https://example.com/audio.mp3
        model:
          type: string
          description: The STT model to use for transcription
          enum:
            - Whisper-Large-V3
            - Wizper
            - Elevenlabs-STT
            - gpt-4o-mini-transcribe
            - gpt-4o-mini-transcribe-2025-03-20
            - gpt-4o-mini-transcribe-2025-12-15
            - gpt-4o-mini-transcribe-latest
            - openai-whisper-with-video
            - qwen-voice-clone
            - minimax-voice-clone
          default: Whisper-Large-V3
        language:
          type: string
          description: >-
            Language code for transcription (ISO 639-1 or ISO 639-3). Use 'auto'
            for auto-detection
          default: auto
          example: en
        actualDuration:
          type: string
          description: Actual audio duration in minutes for accurate billing
        diarize:
          type: boolean
          description: Enable speaker diarization (Elevenlabs-STT only)
          default: false
        tagAudioEvents:
          type: boolean
          description: >-
            Tag non-speech audio events like [laughter], [applause]
            (Elevenlabs-STT only)
          default: false
      required:
        - audioUrl
    TranscribeResponse:
      type: object
      required:
        - transcription
        - metadata
      properties:
        transcription:
          type: string
          description: The transcribed text
          example: Hello, this is a test transcription.
        metadata:
          type: object
          required:
            - model
            - cost
            - currency
          properties:
            fileName:
              type: string
              description: Original file name
            fileSize:
              type: integer
              description: File size in bytes
            chargedDuration:
              type: number
              description: Duration charged for billing (in minutes)
            actualDuration:
              type: number
              description: Actual audio duration (in minutes)
            language:
              type: string
              description: Detected or specified language code
            cost:
              type: number
              description: Cost of the transcription
            currency:
              type: string
              description: Currency of the cost
              default: USD
            model:
              type: string
              description: Model used for transcription
    TranscribeAsyncResponse:
      type: object
      required:
        - runId
        - status
        - model
      properties:
        runId:
          type: string
          description: Unique identifier for the transcription job
          example: abc123def456
        status:
          type: string
          description: Current status of the transcription job
          enum:
            - pending
            - processing
            - completed
            - failed
          default: pending
        model:
          type: string
          description: Model used for transcription
        cost:
          type: number
          description: Cost of the transcription
        paymentSource:
          type: string
          description: Payment source used (USD or XNO)
        isApiRequest:
          type: boolean
          description: Whether this is an API request
        fileName:
          type: string
          description: Original file name
        fileSize:
          type: integer
          description: File size in bytes
        chargedDuration:
          type: number
          description: Duration charged for billing (in minutes)
        diarize:
          type: boolean
          description: Whether speaker diarization is enabled
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