> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Character Models

## Overview

`/api/v1/character-models` returns approved public characters that are enabled for API use in a model-list-compatible shape.

Use this endpoint when you want to sync available public characters into tools that already understand model list responses.

## Endpoint

```
GET https://api.nano-gpt.com/api/v1/character-models
```

Query parameters:

| Field | Type | Description |
| - | - | - |
| `detailed` | boolean | Include slug and extended character metadata |
| `cursor` | string | Pagination cursor |
| `limit` | number | Page size |

## Example

```bash theme={null}
curl "https://api.nano-gpt.com/api/v1/character-models?detailed=true"
```

Response:

```json theme={null}
{
  "object": "list",
  "data": [
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "object": "model",
      "created": 1760000000,
      "owned_by": "nanogpt",
      "character": {
        "character_id": "11111111-1111-1111-1111-111111111111",
        "slug": "helpful-guide",
        "base_model_id": "deepseek-ai/DeepSeek-V3-0324",
        "content_rating": "sfw",
        "tags": ["writing"],
        "rating_avg": 4.8,
        "rating_count": 12
      }
    }
  ],
  "next_cursor": null
}
```

Pass the returned `character.character_id` as `character_id` to the Responses API.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.