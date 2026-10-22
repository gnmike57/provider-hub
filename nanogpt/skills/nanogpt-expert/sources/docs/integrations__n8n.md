> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# n8n

> Use n8n OpenAI nodes with NanoGPT to access 50+ models in your workflows

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

## Overview

n8n can use any OpenAI-compatible API. With NanoGPT, you get:

* One API key for 50+ models (GPT 6.1 Sol, Claude Opus 5.5, Gemini Flash Latest, and more)
* The ability to switch models without changing your workflow logic
* Unified billing across providers

## Prerequisites

* An n8n instance (desktop app, self-hosted, or n8n Cloud)
* A NanoGPT account and API key from [nano-gpt.com/api](https://nano-gpt.com/api)

## Step 1: Get your NanoGPT API key

1. Go to [nano-gpt.com/api](https://nano-gpt.com/api)
2. Click "Create New API Key"
3. Copy the key (format: `sk-nano-...`)
4. Store it securely, you will not be able to view it again

## Step 2: Create OpenAI credentials in n8n

1. Open your n8n instance
2. Go to **Credentials** in the left sidebar
3. Click **+ Add Credential**
4. Search for and select **OpenAI**
5. Fill in the fields:

| Field | Value |
| - | - |
| Credential Name | `NanoGPT` (or any name you prefer) |
| API Key | `sk-nano-YOUR-API-KEY` |
| Base URL | `https://nano-gpt.com/api/v1` |

6. Click **Save**

## Step 3: Use NanoGPT in a workflow

1. Go to **Workflows** and click **+ New Workflow**
2. Add an **OpenAI** node or **Chat OpenAI** node
3. In the node settings:
   * **Credential:** Select your NanoGPT credential
   * **Model:** Enter the model name exactly (examples below)
   * Configure your prompt or messages
4. Click **Execute Node** to test

## Available models

Use any model listed on the [NanoGPT pricing page](https://nano-gpt.com/pricing). Enter the model name exactly as shown.

| Model | Provider | Best for |
| - | - | - |
| <code>{exampleTextModel}</code> | OpenAI | Best overall |
| `anthropic/claude-opus-5.5` | Anthropic | Deep reasoning, writing |
| `anthropic/claude-sonnet-4.5` | Anthropic | Coding, analysis |
| `google/gemini-flash-latest` | Google | Fast, cost-effective |
| `google/gemini-pro-latest` | Google | Long context, reasoning |
| `z-ai/glm-latest` | Zhipu | Open model alternative |

## Example workflows

### Basic chat completion

```
[Manual Trigger] -> [OpenAI Chat] -> [Output]

OpenAI Chat node:
- Credential: NanoGPT
- Model: openai/gpt-6.1-sol
- Messages: User message from input
```

### Document summarization

```
[Webhook] -> [HTTP Request (fetch doc)] -> [OpenAI Chat] -> [Respond to Webhook]

OpenAI Chat node:
- Model: google/gemini-flash-latest
- System: Summarize the following document concisely
- User: {{ $json.documentContent }}
```

### Multi-model comparison

```
[Input] -> [OpenAI Chat (GPT-4o)] -\
                                  -> [Merge] -> [Compare Results]
[Input] -> [OpenAI Chat (Claude)] -/
```

## Troubleshooting

| Issue | Solution |
| - | - |
| `401 Unauthorized` | Verify the API key and that your account has credits |
| `Invalid API Key` | Ensure there are no extra spaces when copying the key |
| `Model not found` | Double-check the model name on the pricing page |
| `Connection timeout` | Confirm the Base URL is `https://nano-gpt.com/api/v1` |
| `Rate limited` | Add a delay between requests or upgrade your plan |

## Advanced: HTTP Request node

If you need full control over parameters, use the HTTP Request node:

1. Add **HTTP Request**
2. Set:
   * **Method:** `POST`
   * **URL:** `https://nano-gpt.com/api/v1/chat/completions`
   * **Authentication:** Header Auth
   * **Header Name:** `Authorization`
   * **Header Value:** `Bearer sk-nano-YOUR-API-KEY`
   * **Body Content Type:** JSON
   * **Body:**

```json theme={null}
{
  "model": "openai/gpt-6.1-sol",
  "messages": [
    { "role": "user", "content": "{{ $json.prompt }}" }
  ]
}
```

## Related links

* [Get API key](https://nano-gpt.com/api)
* [Model pricing](https://nano-gpt.com/pricing)
* [n8n documentation](https://docs.n8n.io/)
* [n8n OpenAI node docs](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.lmchatopenai/)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.