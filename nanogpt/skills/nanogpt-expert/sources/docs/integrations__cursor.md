> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Cursor

> Using NanoGPT with Cursor AI-powered code editor

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# Using Cursor with NanoGPT

A quick guide to setting up Cursor with NanoGPT's API.

## Setup Instructions

1. Get your API key from [nano-gpt.com/api](https://nano-gpt.com/api)
2. In Cursor settings:
   * Override OpenAI Base URL with: [https://nano-gpt.com/api/v1/](https://nano-gpt.com/api/v1/)
   * Set the API Key to your NanoGPT API key
   * Click "+ Add Model" to add any of our models you want to use

That's it! You can now use any of our models in Cursor. Available models include {exampleTextModel}, anthropic/claude-opus-5.5, google/gemini-flash-latest, and many more.

Want to explore available models? Visit our [pricing page](https://nano-gpt.com/pricing).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.