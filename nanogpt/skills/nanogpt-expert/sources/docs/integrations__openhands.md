> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenHands

> Using NanoGPT with OpenHands autonomous agent

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# Using OpenHands with NanoGPT

A quick guide to setting up OpenHands with NanoGPT's API.

## Setup Instructions

1. Get your API key from [nano-gpt.com/api](https://nano-gpt.com/api)
2. In OpenHands, add a new LLM Endpoint and toggle "Advanced".
3. Configure the fields as follows:
   * Custom Model: `openai/<MODEL_NAME_FROM_NANOGPT>`
     * Example: <code>openai/{exampleTextModel}</code> (OpenHands' first `openai/` selects its OpenAI-compatible adapter; the rest is the NanoGPT model ID.)
     * If a model name contains a slash, include it: e.g. `openai/anthropic/claude-opus-5.5` or `openai/google/gemini-flash-latest`
   * Base URL: `https://nano-gpt.com/api/v1` (no trailing slash)
   * API Key: Your key from step 1
   * Search API Key (Tavily): Optional
   * Agent: `CodeActAgent` (recommended)

## Important Notes

* The Base URL must NOT end with a `/`. Use `https://nano-gpt.com/api/v1` exactly.
* Prefix the model with `openai/` and use the exact model name as shown by the NanoGPT API or on our pricing page.

You can now use OpenHands with any NanoGPT model. Popular choices include <code>{exampleTextModel}</code>, `anthropic/claude-opus-5.5`, and `google/gemini-flash-latest`. For a full list, check our [pricing page](https://nano-gpt.com/pricing).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.