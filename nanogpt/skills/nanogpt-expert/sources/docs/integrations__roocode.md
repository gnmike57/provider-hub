> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Roo Code

> Using NanoGPT with Roo Code interface

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# Using Roo Code with NanoGPT

A quick guide to setting up Roo Code with NanoGPT's API.

## Setup Instructions

1. Get your API key from [nano-gpt.com/api](https://nano-gpt.com/api)
2. In Roo Code settings, add a new Custom Model with these details:
   * API Provider: OpenAI Compatible
   * Base URL: [https://nano-gpt.com/api/v1thinking/](https://nano-gpt.com/api/v1thinking/)
   * API Key: Your key from step 1
   * Model ID: {exampleTextModel}

> **Tip:** Roo Code surfaces the `thinking` and `response` channels side-by-side. Pointing it at `https://nano-gpt.com/api/v1thinking/` keeps that richer reasoning stream intact for models like Minimax M2 or Kimi K2 Thinking.

That's it! You can now use Roo Code with every model you can think of. Model names are on our [pricing page](https://nano-gpt.com/pricing) - important ones are {exampleTextModel}, anthropic/claude-opus-5.5, google/gemini-flash-latest, or just any other model you fancy.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.