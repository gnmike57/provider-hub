> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# YouTube Transcription

> Extract transcripts from YouTube videos programmatically. Supports multiple URLs per request and provides detailed response information including success/failure status for each video.

## Overview

The YouTube Transcription API allows you to extract transcripts from YouTube videos programmatically. This is useful for content analysis, accessibility, research, or any application that needs to work with YouTube video content in text format.

## Authentication

The API supports two authentication methods:

### 1. API Key Authentication (Recommended)

Include your API key in the request headers:

```
x-api-key: YOUR_API_KEY
```

### 2. Session Authentication

If you're making requests from a browser with an active session, authentication will be handled automatically via cookies.

## Request Format

### Headers

```json theme={null}
{
  "Content-Type": "application/json",
  "x-api-key": "YOUR_API_KEY"
}
```

### Body

```json theme={null}
{
  "urls": [
    "https://www.youtube.com/watch?v=VIDEO_ID_1",
    "https://youtu.be/VIDEO_ID_2",
    "https://youtube.com/watch?v=VIDEO_ID_3"
  ]
}
```

### Parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| `urls` | string\[] | Yes | Array of YouTube URLs to transcribe. Maximum 10 URLs per request. |

### Supported YouTube URL Formats

* `https://www.youtube.com/watch?v=VIDEO_ID`
* `https://youtu.be/VIDEO_ID`
* `https://youtube.com/embed/VIDEO_ID`
* `https://m.youtube.com/watch?v=VIDEO_ID`
* `https://youtube.com/live/VIDEO_ID`

## Response Format

### Success Response (200 OK)

```json theme={null}
{
  "transcripts": [
    {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "success": true,
      "title": "Rick Astley - Never Gonna Give You Up",
      "transcript": "We're no strangers to love\nYou know the rules and so do I..."
    },
    {
      "url": "https://youtube.com/watch?v=invalid",
      "success": false,
      "error": "Video not found or transcripts not available"
    }
  ],
  "summary": {
    "requested": 2,
    "processed": 2,
    "successful": 1,
    "failed": 1,
    "totalCost": 0.01
  }
}
```

### Response Fields

#### `transcripts` Array

Each transcript object contains:

* `url` (string): The original YouTube URL
* `success` (boolean): Whether the transcript was successfully retrieved
* `title` (string, optional): Video title (only if successful)
* `transcript` (string, optional): The full transcript text (only if successful)
* `error` (string, optional): Error message (only if failed)

#### `summary` Object

* `requested`: Number of URLs provided in the request
* `processed`: Number of valid YouTube URLs found and processed
* `successful`: Number of transcripts successfully retrieved
* `failed`: Number of transcripts that failed
* `totalCost`: Total cost in USD for successful transcripts

### Error Responses

#### 400 Bad Request

```json theme={null}
{
  "error": "Please provide an array of YouTube URLs"
}
```

#### 401 Unauthorized

```json theme={null}
{
  "error": "Invalid session"
}
```

#### 402 Payment Required

```json theme={null}
{
  "error": "Insufficient balance. Current balance: $0.50, required: $1.00"
}
```

#### 429 Too Many Requests

```json theme={null}
{
  "error": "Rate limit exceeded. Please wait before sending another request."
}
```

## Pricing

* **Cost**: \$0.01 USD per successful transcript
* **Billing**: You are only charged for successfully retrieved transcripts
* **Failed transcripts**: No charge

## Rate Limits

* **10 requests per minute** per IP address
* **10 URLs maximum** per request

## Code Examples

<CodeGroup>
  ```javascript JavaScript/Node.js theme={null}
  const axios = require('axios');

  async function getYouTubeTranscripts() {
    try {
      const response = await axios.post('https://api.nano-gpt.com/api/youtube-transcribe', {
        urls: [
          'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          'https://youtu.be/kJQP7kiw5Fk'
        ]
      }, {
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': 'YOUR_API_KEY'
        }
      });

      console.log('Transcripts:', response.data.transcripts);
      console.log('Summary:', response.data.summary);
    } catch (error) {
      console.error('Error:', error.response?.data || error.message);
    }
  }
  ```

  ```python Python theme={null}
  import requests

  def get_youtube_transcripts():
      url = 'https://api.nano-gpt.com/api/youtube-transcribe'
      headers = {
          'Content-Type': 'application/json',
          'x-api-key': 'YOUR_API_KEY'
      }
      data = {
          'urls': [
              'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
              'https://youtu.be/kJQP7kiw5Fk'
          ]
      }
      
      try:
          response = requests.post(url, json=data, headers=headers)
          response.raise_for_status()
          
          result = response.json()
          print('Transcripts:', result['transcripts'])
          print('Summary:', result['summary'])
      except requests.exceptions.RequestException as e:
          print(f'Error: {e}')
          if hasattr(e.response, 'json'):
              print('Details:', e.response.json())
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/youtube-transcribe \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_API_KEY" \
    -d '{
      "urls": [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/kJQP7kiw5Fk"
      ]
    }'
  ```

  ```php PHP theme={null}
  <?php
  $url = 'https://api.nano-gpt.com/api/youtube-transcribe';
  $data = [
      'urls' => [
          'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          'https://youtu.be/kJQP7kiw5Fk'
      ]
  ];

  $options = [
      'http' => [
          'header' => [
              "Content-Type: application/json",
              "x-api-key: YOUR_API_KEY"
          ],
          'method' => 'POST',
          'content' => json_encode($data)
      ]
  ];

  $context = stream_context_create($options);
  $result = file_get_contents($url, false, $context);

  if ($result === FALSE) {
      die('Error occurred');
  }

  $response = json_decode($result, true);
  print_r($response);
  ?>
  ```
</CodeGroup>

## Best Practices

1. **Batch Requests**: Send multiple URLs in a single request (up to 10) rather than making individual requests for better efficiency.

2. **Error Handling**: Always check the `success` field for each transcript, as some videos may not have transcripts available.

3. **Rate Limiting**: Implement exponential backoff if you receive a 429 status code.

4. **URL Validation**: The API automatically detects and validates YouTube URLs, but validating on your end can save API calls.

5. **Cost Monitoring**: Use the `summary.totalCost` field to track your spending.

## Limitations

1. **Transcript Availability**: Not all YouTube videos have transcripts available. Videos may lack transcripts if:
   * The creator hasn't enabled auto-captions
   * The video is private or age-restricted
   * The video has been deleted
   * The video is a live stream without captions

2. **Language**: Transcripts are returned in their original language. The API doesn't provide translation services.

3. **Formatting**: Transcripts are returned as plain text with natural line breaks. Timestamp information is not included.

## Use Cases

* **Content Analysis**: Analyze video content for keywords, topics, or sentiment
* **Accessibility**: Create accessible versions of video content
* **Research**: Study communication patterns, language use, or content trends
* **SEO**: Extract content for search engine optimization
* **Education**: Create study materials from educational videos
* **Content Moderation**: Check video content for compliance

## Support

For technical support or questions about the YouTube Transcription API:

* Email: [support@nano-gpt.com](mailto:support@nano-gpt.com)
* Documentation: [https://docs.nano-gpt.com](https://docs.nano-gpt.com)
* Status Page: [https://status.nano-gpt.com](https://status.nano-gpt.com)


## OpenAPI

````yaml POST /youtube-transcribe
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
  /youtube-transcribe:
    post:
      description: >-
        Extract transcripts from YouTube videos programmatically. Supports
        multiple URLs per request and provides detailed response information
        including success/failure status for each video.
      requestBody:
        description: YouTube transcription parameters
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/YouTubeTranscribeRequest'
        required: true
      responses:
        '200':
          description: YouTube transcription response with results for each URL
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/YouTubeTranscribeResponse'
        '400':
          description: Bad Request - Please provide an array of YouTube URLs
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
        '401':
          description: Unauthorized - Invalid session or API key
        '402':
          description: Payment Required - Insufficient balance
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
      security:
        - apiKeyAuth: []
components:
  schemas:
    YouTubeTranscribeRequest:
      type: object
      required:
        - urls
      properties:
        urls:
          type: array
          description: Array of YouTube URLs to transcribe (maximum 10 URLs per request)
          items:
            type: string
            format: uri
            description: YouTube URL in supported format
          minItems: 1
          maxItems: 10
          example:
            - https://www.youtube.com/watch?v=dQw4w9WgXcQ
            - https://youtu.be/kJQP7kiw5Fk
    YouTubeTranscribeResponse:
      type: object
      required:
        - transcripts
        - summary
      properties:
        transcripts:
          type: array
          description: Array of transcript results for each URL
          items:
            type: object
            required:
              - url
              - success
            properties:
              url:
                type: string
                description: The original YouTube URL
              success:
                type: boolean
                description: Whether the transcript was successfully retrieved
              title:
                type: string
                description: Video title (only if successful)
              transcript:
                type: string
                description: The full transcript text (only if successful)
              error:
                type: string
                description: Error message (only if failed)
        summary:
          type: object
          required:
            - requested
            - processed
            - successful
            - failed
            - totalCost
          properties:
            requested:
              type: integer
              description: Number of URLs provided in the request
            processed:
              type: integer
              description: Number of valid YouTube URLs found and processed
            successful:
              type: integer
              description: Number of transcripts successfully retrieved
            failed:
              type: integer
              description: Number of transcripts that failed
            totalCost:
              type: number
              description: Total cost in USD for successful transcripts
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