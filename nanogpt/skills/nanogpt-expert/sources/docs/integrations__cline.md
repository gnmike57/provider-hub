> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Cline

> Using NanoGPT with Cline CLI interface

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# Using Cline with NanoGPT

A quick guide to setting up Cline with NanoGPT's API.

## Setup Instructions

1. Get your API key from [nano-gpt.com/api](https://nano-gpt.com/api)
2. In Cline settings, add a new Custom Model with these details:
   * API Provider: OpenAI Compatible
   * Base URL: [https://nano-gpt.com/api/v1/](https://nano-gpt.com/api/v1/)
   * API Key: Your key from step 1
   * Model ID: {exampleTextModel}

> **Tip:** If Cline is not showing a model's `thinking` output, switch the Base URL to `https://nano-gpt.com/api/v1legacy/`. Cline still expects the legacy streaming shape for parallel thinking/output channels, and this endpoint keeps that compatibility without affecting model availability.

That's it! You can now use Cline with every model you can think of. Model names are on our [pricing page](https://nano-gpt.com/pricing) - important ones are {exampleTextModel}, anthropic/claude-opus-5.5, google/gemini-flash-latest, or just any other model you fancy.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.