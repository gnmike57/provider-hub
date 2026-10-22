> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Embedding Models

> List all available embedding models with detailed information

## Overview

The `/api/v1/embedding-models` endpoint provides a comprehensive list of available embedding models with detailed information including dimensions, max dimensions, token limits, pricing, and feature support. Use this endpoint instead of hardcoding embedding model capabilities.

This endpoint is cacheable. Refresh it periodically because model availability can change.

## Authentication

Authentication is optional but may enable user-specific features:

| Header | Format | Required | Description |
| - | - | - | - |
| `Authorization` | `Bearer {api_key}` | Optional | API key for authenticated access |
| `x-api-key` | `{api_key}` | Optional | Alternative API key header |

## Response Format

Returns a list of all available embedding models with comprehensive details:

```json theme={null}
{
  "object": "list",
  "data": [
    {
      "id": "text-embedding-3-small",
      "object": "model",
      "created": 1754480583,
      "owned_by": "openai",
      "name": "Text Embedding 3 Small",
      "description": "Most cost-effective OpenAI embedding model with dimension reduction support",
      "dimensions": 1536,
      "max_dimensions": 1536,
      "supports_dimensions": true,
      "max_tokens": 8191,
      "zero_data_retention": false,
      "pricing": {
        "per_million_tokens": 0.02,
        "currency": "USD"
      }
    },
    {
      "id": "text-embedding-3-large",
      "object": "model",
      "created": 1754480583,
      "owned_by": "openai",
      "name": "Text Embedding 3 Large",
      "description": "Highest performance OpenAI embedding model with dimension reduction support",
      "dimensions": 3072,
      "max_dimensions": 3072,
      "supports_dimensions": true,
      "max_tokens": 8191,
      "zero_data_retention": false,
      "pricing": {
        "per_million_tokens": 0.13,
        "currency": "USD"
      }
    },
    {
      "id": "BAAI/bge-m3",
      "object": "model",
      "created": 1754480583,
      "owned_by": "nanogpt",
      "name": "BGE M3",
      "description": "Multilingual embedding model with excellent performance across languages",
      "dimensions": 1024,
      "max_dimensions": 1024,
      "supports_dimensions": false,
      "max_tokens": 8192,
      "zero_data_retention": true,
      "pricing": {
        "per_million_tokens": 0.01,
        "currency": "USD"
      }
    }
    // ... more models
  ]
}
```

## Field Descriptions

| Field | Type | Description |
| - | - | - |
| `id` | string | Unique model identifier to use in embedding requests |
| `object` | string | Always "model" for OpenAI compatibility |
| `created` | number | Unix timestamp of response creation |
| `owned_by` | string | `openai` for OpenAI models, otherwise `nanogpt` |
| `name` | string | Human-readable model name |
| `description` | string | Detailed model description and use cases |
| `dimensions` | number | Default embedding vector dimensions |
| `max_dimensions` | number | Maximum embedding vector dimensions supported |
| `supports_dimensions` | boolean | Whether custom dimensions are supported |
| `max_tokens` | number | Maximum input tokens supported |
| `zero_data_retention` | boolean | Whether the model accepts requests while ZDR-only routing is on. Those requests use only providers that declare zero data retention. |
| `pricing` | object | Pricing information object |

### Pricing Object Structure

| Field | Type | Description |
| - | - | - |
| `per_million_tokens` | number | Cost per million tokens in USD |
| `currency` | string | Always "USD" |

## Model Categories

### OpenAI Models

High-quality embeddings with dimension reduction support:

* `text-embedding-3-small` - Balance of cost and performance
* `text-embedding-3-large` - Maximum accuracy
* `text-embedding-ada-002` - Legacy model

### Multilingual Models

Support for multiple languages:

* `BAAI/bge-m3` - Excellent multilingual support

### Language-Specific Models

Optimized for specific languages:

* English: `BAAI/bge-base-en-v1.5`, `BAAI/bge-large-en-v1.5`

### Specialized Models

Domain-specific embeddings:

* `Qwen/Qwen3-Embedding-0.6B` - Efficient with dimension reduction
* `Qwen/Qwen3-Embedding-4B` - Higher quality Qwen embeddings
* `Qwen/Qwen3-Embedding-8B` - Long-context Qwen embeddings
* `gemini-embedding-001` - Gemini embeddings

## Usage Examples

### Basic Request

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/embedding-models"
```

### With Authentication

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/embedding-models" \
  -H "Authorization: Bearer your_api_key_here"
```

### Python Example

```python theme={null}
import requests

# Discover available embedding models
response = requests.get("https://api.nano-gpt.com/api/v1/embedding-models")
models = response.json()

# Display models sorted by price
for model in sorted(models["data"], key=lambda x: x["pricing"]["per_million_tokens"]):
    print(f"{model['id']}: ${model['pricing']['per_million_tokens']}/1M tokens - {model['dimensions']} dims")
```

### JavaScript Example

```javascript theme={null}
// Discover available embedding models
const response = await fetch("https://api.nano-gpt.com/api/v1/embedding-models");
const models = await response.json();

// Find models that support dimension reduction
const flexibleModels = models.data.filter(m => m.supports_dimensions);
console.log("Models with dimension reduction:", flexibleModels.map(m => m.id));
```

## Model Selection Guide

| Use Case | Recommended Models | Rationale |
| - | - | - |
| General English text | `text-embedding-3-small` | Best price/performance ratio |
| Maximum accuracy | `text-embedding-3-large` | Highest quality embeddings |
| Multilingual content | `BAAI/bge-m3` | Excellent cross-language performance |
| Code embeddings | `qwen/qwen3-embedding-8b` | Strong code retrieval with a 32K-token context |
| Budget-conscious | `BAAI/bge-large-en-v1.5` | \$0.01/1M tokens |
| Chinese content | `BAAI/bge-m3` | Strong Chinese and multilingual retrieval |
| Fast similarity search | Models with `supports_dimensions: true` | Can reduce dimensions for speed |


## OpenAPI

````yaml GET /v1/embedding-models
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
  /v1/embedding-models:
    get:
      description: List all available embedding models with detailed information
      responses:
        '200':
          description: List of available embedding models
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EmbeddingModelsResponse'
        '400':
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
      security:
        - bearerAuth: []
        - apiKeyAuth: []
components:
  schemas:
    EmbeddingModelsResponse:
      type: object
      required:
        - object
        - data
      properties:
        object:
          type: string
          description: Always 'list'
          example: list
        data:
          type: array
          description: Array of embedding model objects
          items:
            type: object
            required:
              - id
              - object
              - created
              - owned_by
            properties:
              id:
                type: string
                description: Unique model identifier
                example: text-embedding-3-small
              object:
                type: string
                description: Always 'model'
                example: model
              created:
                type: integer
                description: Unix timestamp
                example: 1754480583
              owned_by:
                type: string
                description: Model provider
                example: openai
              name:
                type: string
                description: Human-readable model name
                example: Text Embedding 3 Small
              description:
                type: string
                description: Model description and use cases
                example: >-
                  Most cost-effective OpenAI embedding model with dimension
                  reduction support
              dimensions:
                type: integer
                description: Default embedding vector dimensions
                example: 1536
              supports_dimensions:
                type: boolean
                description: Whether model supports dimension reduction
                example: true
              max_tokens:
                type: integer
                description: Maximum input tokens supported
                example: 8191
              zero_data_retention:
                type: boolean
                description: >-
                  Whether the model accepts requests while ZDR-only routing is
                  on. Those requests use only providers that declare zero data
                  retention.
                example: false
              pricing:
                type: object
                required:
                  - per_million_tokens
                  - currency
                properties:
                  per_million_tokens:
                    type: number
                    description: Cost per million tokens
                    example: 0.02
                  currency:
                    type: string
                    description: Pricing currency
                    example: USD
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
    apiKeyAuth:
      type: apiKey
      in: header
      name: x-api-key

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.