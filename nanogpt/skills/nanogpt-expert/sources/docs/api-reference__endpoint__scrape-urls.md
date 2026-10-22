> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Web Scraping

> Extract clean, formatted content from web pages. Returns both raw HTML content and formatted markdown.

## Overview

The NanoGPT Web Scraping API allows you to extract clean, formatted content from web pages. It uses the Firecrawl service to scrape URLs and returns both raw HTML content and formatted markdown.

You can also call this tool through the unified [Data API](/api-reference/endpoint/data-api) at `POST /api/v1/data/url/scrape`. The Data API preserves this endpoint's request body, response body, billing, and validation behavior while adding discovery and dispatch metadata.

## Authentication

The API supports two authentication methods:

### 1. API Key Authentication (Recommended)

Include your API key in the request header:

```
x-api-key: YOUR_API_KEY
```

### 2. Bearer Token Authentication

```
Authorization: Bearer YOUR_API_KEY
```

## Accountless x402 Payment

For accountless payment, prefer the public Data API path:

```bash theme={null}
curl -i https://api.nano-gpt.com/api/v1/data/url/scrape \
  -H "Content-Type: application/json" \
  -H "x-x402: true" \
  -d '{
    "urls": ["https://nano-gpt.com"],
    "stealthMode": false
  }'
```

To request an accountless x402 quote, send the API request without `Authorization` or `x-api-key`, and include `x-x402: true`. NanoGPT will return `402 Payment Required` with available payment options. This endpoint supports accountless x402 payments where listed by `GET /api/v1/x402/endpoints`, including Lightning L402 when advertised. See [Accountless x402 API Payments](/api-reference/miscellaneous/x402) for the full flow.

If you receive `401 missing_api_key` immediately, check that the initial quote request includes `x-x402: true`. Without that header, NanoGPT does not enter the x402 quote flow.

## Request Format

### Headers

```
Content-Type: application/json
x-api-key: YOUR_API_KEY
```

### Request Body

```json theme={null}
{
  "urls": [
    "https://example.com/article",
    "https://blog.com/post",
    "https://news.site.com/story"
  ],
  "stealthMode": false
}
```

### Parameters

| Parameter | Type | Required | Description |
| - | - | - | - |
| urls | string\[] | Yes | Array of URLs to scrape. Maximum 5 URLs per request. |
| stealthMode | boolean | No | Optional. Default `false`. When `true`, multiplies the upfront per-URL charge by 5 and routes requests through the stealth proxy. |

#### Stealth scraping (optional)

Set `stealthMode: true` to run requests through Firecrawl’s stealth proxy for tougher targets. Stealth scraping costs 5× the standard per-URL rate and still counts toward the configured URL cap. The web UI exposes the same toggle, so use this field to mirror that behavior from the API.

```jsonc theme={null}
POST /api/scrape-urls
{
  "urls": ["https://example.com/restricted"],
  "stealthMode": true
}
```

The response `summary` includes `stealthModeUsed` so you can track when the surcharge applied.

### URL Requirements

* Must be valid HTTP or HTTPS URLs
* Must have standard web ports (80, 443, or default)
* Cannot be localhost, private IPs, or metadata endpoints
* YouTube URLs are not supported (use the YouTube transcription endpoint instead)

## Response Format

### Success Response (200 OK)

```json theme={null}
{
  "results": [
    {
      "url": "https://example.com/article",
      "success": true,
      "title": "Article Title",
      "content": "Raw HTML content...",
      "markdown": "# Article Title\n\nFormatted markdown content..."
    },
    {
      "url": "https://invalid.site.com",
      "success": false,
      "error": "Failed to scrape URL"
    }
  ],
  "summary": {
    "requested": 3,
    "processed": 3,
    "successful": 2,
    "failed": 1,
    "totalCost": 0.002,
    "stealthModeUsed": false
  }
}
```

### Response Fields

#### results

Array of scraping results for each URL:

* `url` (string): The URL that was scraped
* `success` (boolean): Whether the scraping was successful
* `title` (string, optional): Page title if successfully scraped
* `content` (string, optional): Raw HTML content
* `markdown` (string, optional): Formatted markdown version of the content
* `error` (string, optional): Error message if scraping failed

#### summary

Summary statistics for the request:

* `requested` (number): Number of URLs in the original request
* `processed` (number): Number of valid URLs that were processed
* `successful` (number): Number of URLs successfully scraped
* `failed` (number): Number of URLs that failed to scrape
* `totalCost` (number): Total cost in USD (only for successful scrapes)
* `stealthModeUsed` (boolean): Indicates whether stealth mode was enabled for any processed URLs

## Error Responses

### 400 Bad Request

```json theme={null}
{
  "error": "Please provide an array of URLs to scrape"
}
```

### 401 Unauthorized

```json theme={null}
{
  "error": "Invalid session"
}
```

### 402 Payment Required

```json theme={null}
{
  "error": "Insufficient balance"
}
```

### 429 Too Many Requests

```json theme={null}
{
  "error": "Rate limit exceeded. Please wait before sending another request."
}
```

### 500 Internal Server Error

```json theme={null}
{
  "error": "An error occurred while processing your request"
}
```

## Pricing

* **Cost**: \$0.001 per successfully scraped URL
* **Billing**: You are only charged for URLs that are successfully scraped
* **Payment Methods**: USD balance or Nano (XNO) cryptocurrency
* **Note (inline chat scraping)**: Inline URL scraping inside `POST /api/v1/chat/completions` (via `scraping: true`) is billed separately at **\$0.0015 per successfully scraped URL**. Use this endpoint when you want explicit URL lists and the lower standalone price.

## Rate Limits

* **Default**: 30 requests per minute per IP address
* **With API Key**: 30 requests per minute per API key

## Code Examples

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST https://api.nano-gpt.com/api/scrape-urls \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_API_KEY" \
    -d '{
      "urls": [
        "https://example.com/article",
        "https://blog.com/post"
      ]
    }'
  ```

  ```python Python theme={null}
  import requests

  api_key = "YOUR_API_KEY"
  urls = [
      "https://example.com/article",
      "https://blog.com/post"
  ]

  response = requests.post(
      "https://api.nano-gpt.com/api/scrape-urls",
      headers={
          "Content-Type": "application/json",
          "x-api-key": api_key
      },
      json={"urls": urls}
  )

  data = response.json()
  for result in data["results"]:
      if result["success"]:
          print(f"Title: {result['title']}")
          print(f"Markdown: {result['markdown'][:200]}...")
      else:
          print(f"Failed to scrape {result['url']}: {result['error']}")
  ```

  ```javascript JavaScript/TypeScript theme={null}
  const apiKey = 'YOUR_API_KEY';
  const urls = [
    'https://example.com/article',
    'https://blog.com/post'
  ];

  const response = await fetch('https://api.nano-gpt.com/api/scrape-urls', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey
    },
    body: JSON.stringify({ urls })
  });

  const data = await response.json();
  data.results.forEach(result => {
    if (result.success) {
      console.log(`Title: ${result.title}`);
      console.log(`Markdown: ${result.markdown.substring(0, 200)}...`);
    } else {
      console.log(`Failed to scrape ${result.url}: ${result.error}`);
    }
  });
  ```
</CodeGroup>

## Best Practices

1. **Batch Requests**: Send multiple URLs in a single request (up to 5) to minimize API calls
2. **Error Handling**: Always check the `success` field for each result before accessing content
3. **Content Size**: Scraped content is limited to 100KB per URL
4. **URL Validation**: Validate URLs on your end before sending to reduce failed requests
5. **Markdown Format**: Use the markdown field for better readability and formatting

## Limitations

* Maximum 5 URLs per request
* Maximum content size: 100KB per URL
* No JavaScript rendering (static content only)

## FAQ

**Q: Why was my URL rejected?**
A: URLs can be rejected for several reasons:

* Invalid format (not HTTP/HTTPS)
* Pointing to localhost or private IPs
* Using non-standard ports
* Being a YouTube URL (use the YouTube transcription endpoint)

**Q: Can I scrape JavaScript-heavy sites?**
A: The scraper fetches static HTML content. Sites that rely heavily on JavaScript may not return complete content.

**Q: What happens if a URL fails to scrape?**
A: You are not charged for failed URLs. The response will include an error message for that specific URL.

**Q: Is there a sandbox/test environment?**
A: You can test with your regular API key. Since you're only charged for successful scrapes, failed attempts during testing won't cost anything.


## OpenAPI

````yaml POST /scrape-urls
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
  /scrape-urls:
    post:
      description: >-
        Extract clean, formatted content from web pages. Returns both raw HTML
        content and formatted markdown.
      requestBody:
        description: Web scraping parameters
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ScrapeUrlsRequest'
        required: true
      responses:
        '200':
          description: Web scraping response with results for each URL
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ScrapeUrlsResponse'
        '400':
          description: Bad Request - Please provide an array of URLs to scrape
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
          description: >-
            Internal Server Error - An error occurred while processing your
            request
      security:
        - apiKeyAuth: []
        - bearerAuth: []
components:
  schemas:
    ScrapeUrlsRequest:
      type: object
      required:
        - urls
      properties:
        urls:
          type: array
          description: Array of URLs to scrape (maximum 5 URLs per request)
          items:
            type: string
            format: uri
            description: URL to scrape
          minItems: 1
          maxItems: 5
          example:
            - https://example.com/article
            - https://blog.com/post
    ScrapeUrlsResponse:
      type: object
      required:
        - results
        - summary
      properties:
        results:
          type: array
          description: Array of scraping results for each URL
          items:
            type: object
            required:
              - url
              - success
            properties:
              url:
                type: string
                description: The URL that was scraped
              success:
                type: boolean
                description: Whether the scraping was successful
              title:
                type: string
                description: Page title if successfully scraped
              content:
                type: string
                description: Raw HTML content
              markdown:
                type: string
                description: Formatted markdown version of the content
              error:
                type: string
                description: Error message if scraping failed
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
              type: number
              description: Number of URLs in the original request
            processed:
              type: number
              description: Number of valid URLs that were processed
            successful:
              type: number
              description: Number of URLs successfully scraped
            failed:
              type: number
              description: Number of URLs that failed to scrape
            totalCost:
              type: number
              description: Total cost in USD (only for successful scrapes)
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