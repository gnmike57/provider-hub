> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Speech-to-Text Status

> Check the status of an asynchronous transcription job (Elevenlabs-STT). Poll this endpoint to get the transcription results when the job is completed.

## Overview

Check the status of an asynchronous transcription job (Elevenlabs-STT). Poll this endpoint to get transcription results when the job is completed.

## Usage

This endpoint is used with the Elevenlabs-STT model which processes transcriptions asynchronously. After submitting a transcription job, you'll receive a `runId` that you use to check the status.

<CodeGroup>
  ```python Python theme={null}
  import requests
  import time

  def check_transcription_status(run_id, job_data):
      headers = {
          "x-api-key": "YOUR_API_KEY",
          "Content-Type": "application/json"
      }
      
      status_data = {
          "runId": run_id,
          "cost": job_data.get('cost'),
          "paymentSource": job_data.get('paymentSource'),
          "isApiRequest": True,
          "fileName": job_data.get('fileName'),
          "fileSize": job_data.get('fileSize'),
          "chargedDuration": job_data.get('chargedDuration'),
          "diarize": job_data.get('diarize', False)
      }
      
      response = requests.post(
          "https://api.nano-gpt.com/api/transcribe/status",
          headers=headers,
          json=status_data
      )
      
      return response.json()

  def wait_for_completion(run_id, job_data, max_attempts=60):
      for attempt in range(max_attempts):
          result = check_transcription_status(run_id, job_data)
          status = result.get('status')
          
          if status == 'completed':
              return result
          elif status == 'failed':
              raise Exception(f"Transcription failed: {result.get('error')}")
          
          print(f"Status: {status} (attempt {attempt + 1}/{max_attempts})")
          time.sleep(5)
      
      raise Exception("Transcription timed out")

  # Usage
  job_data = {"runId": "abc123", "cost": 0.075, "paymentSource": "USD"}
  result = wait_for_completion("abc123", job_data)
  print(result['transcription'])
  ```

  ```javascript JavaScript theme={null}
  async function checkTranscriptionStatus(runId, jobData) {
      const response = await fetch('https://api.nano-gpt.com/api/transcribe/status', {
          method: 'POST',
          headers: {
              'x-api-key': 'YOUR_API_KEY',
              'Content-Type': 'application/json'
          },
          body: JSON.stringify({
              runId: runId,
              cost: jobData.cost,
              paymentSource: jobData.paymentSource,
              isApiRequest: true,
              fileName: jobData.fileName,
              fileSize: jobData.fileSize,
              chargedDuration: jobData.chargedDuration,
              diarize: jobData.diarize || false
          })
      });
      
      return await response.json();
  }

  async function waitForCompletion(runId, jobData, maxAttempts = 60) {
      for (let attempt = 0; attempt < maxAttempts; attempt++) {
          const result = await checkTranscriptionStatus(runId, jobData);
          const status = result.status;
          
          if (status === 'completed') {
              return result;
          } else if (status === 'failed') {
              throw new Error(`Transcription failed: ${result.error}`);
          }
          
          console.log(`Status: ${status} (attempt ${attempt + 1}/${maxAttempts})`);
          await new Promise(resolve => setTimeout(resolve, 5000));
      }
      
      throw new Error('Transcription timed out');
  }

  // Usage
  const jobData = {runId: "abc123", cost: 0.075, paymentSource: "USD"};
  const result = await waitForCompletion("abc123", jobData);
  console.log(result.transcription);
  ```

  ```bash cURL theme={null}
  # Check status
  curl -X POST https://api.nano-gpt.com/api/transcribe/status \
    -H "x-api-key: YOUR_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "runId": "abc123def456",
      "cost": 0.075,
      "paymentSource": "USD",
      "isApiRequest": true,
      "fileName": "meeting.mp3",
      "fileSize": 2345678,
      "chargedDuration": 2.5,
      "diarize": true
    }'
  ```
</CodeGroup>

## Status Values

* **`pending`**: Job is queued for processing
* **`processing`**: Transcription is in progress
* **`completed`**: Transcription finished successfully
* **`failed`**: Transcription failed (check error field)

## Response Examples

### Pending/Processing

```json theme={null}
{
  "status": "processing"
}
```

### Completed

```json theme={null}
{
  "status": "completed",
  "transcription": "Speaker 1: Hello everyone. Speaker 2: Hi there!",
  "metadata": {
    "fileName": "meeting.mp3",
    "fileSize": 2345678,
    "chargedDuration": 2.5,
    "actualDuration": 2.47,
    "language": "en",
    "cost": 0.075,
    "currency": "USD",
    "model": "Elevenlabs-STT"
  },
  "words": [
    {
      "text": "Hello",
      "start": 0.5,
      "end": 0.9,
      "type": "word",
      "speaker_id": "speaker_0"
    }
  ],
  "diarization": {
    "segments": [
      {
        "speaker": "Speaker 1",
        "text": "Hello everyone",
        "start": 0.5,
        "end": 1.5
      }
    ]
  }
}
```

### Failed

```json theme={null}
{
  "status": "failed",
  "error": "Audio file could not be processed"
}
```


## OpenAPI

````yaml POST /transcribe/status
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
  /transcribe/status:
    post:
      description: >-
        Check the status of an asynchronous transcription job (Elevenlabs-STT).
        Poll this endpoint to get the transcription results when the job is
        completed.
      requestBody:
        description: >-
          Status check parameters including runId from the initial transcription
          request
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TranscribeStatusRequest'
        required: true
      responses:
        '200':
          description: Transcription status response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TranscribeStatusResponse'
        '400':
          description: Bad Request - Missing required parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid or missing API key
        '404':
          description: Not Found - Transcription job not found
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
    TranscribeStatusRequest:
      type: object
      required:
        - runId
      properties:
        runId:
          type: string
          description: Unique identifier for the transcription job
          example: abc123def456
        cost:
          type: number
          description: Cost of the transcription (from initial response)
        paymentSource:
          type: string
          description: Payment source used (from initial response)
        isApiRequest:
          type: boolean
          description: Whether this is an API request (from initial response)
        fileName:
          type: string
          description: Original file name (from initial response)
        fileSize:
          type: integer
          description: File size in bytes (from initial response)
        chargedDuration:
          type: number
          description: Duration charged for billing (from initial response)
        diarize:
          type: boolean
          description: Whether speaker diarization is enabled (from initial response)
    TranscribeStatusResponse:
      type: object
      required:
        - status
      properties:
        status:
          type: string
          description: Current status of the transcription job
          enum:
            - pending
            - processing
            - completed
            - failed
        transcription:
          type: string
          description: The transcribed text (available when status is 'completed')
          example: 'Speaker 1: Hello everyone. Speaker 2: Hi there!'
        metadata:
          type: object
          description: Transcription metadata (available when status is 'completed')
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
              description: Detected language code
            cost:
              type: number
              description: Cost of the transcription
            currency:
              type: string
              description: Currency of the cost
            model:
              type: string
              description: Model used for transcription
        words:
          type: array
          description: Word-level timestamps and speaker information (Elevenlabs-STT only)
          items:
            type: object
            properties:
              text:
                type: string
                description: The word or text segment
              start:
                type: number
                description: Start time in seconds
              end:
                type: number
                description: End time in seconds
              type:
                type: string
                description: Type of segment
                enum:
                  - word
                  - punctuation
              speaker_id:
                type: string
                description: Speaker identifier (when diarization is enabled)
        diarization:
          type: object
          description: Speaker diarization results (when enabled)
          properties:
            segments:
              type: array
              description: Speaker segments with timestamps
              items:
                type: object
                properties:
                  speaker:
                    type: string
                    description: Speaker label (e.g., 'Speaker 1')
                  text:
                    type: string
                    description: Text spoken by this speaker
                  start:
                    type: number
                    description: Start time in seconds
                  end:
                    type: number
                    description: End time in seconds
        error:
          type: string
          description: Error message (available when status is 'failed')
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