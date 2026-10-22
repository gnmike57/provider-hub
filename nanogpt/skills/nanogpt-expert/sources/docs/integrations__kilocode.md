> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Kilo Code

> Using NanoGPT with Kilo Code interface

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# Using Kilo Code with NanoGPT

A quick guide to setting up Kilo Code with NanoGPT's API.

## Setup Instructions

1. Get your API key from [nano-gpt.com/api](https://nano-gpt.com/api)
2. In Kilo Code settings, add a new Custom Model with these details:
   * API Provider: OpenAI Compatible
   * Base URL: [https://nano-gpt.com/api/v1/](https://nano-gpt.com/api/v1/)
   * API Key: Your key from step 1
   * Model ID: {exampleTextModel}

That's it! You can now use Kilo Code with every model you can think of. Model names are on our [pricing page](https://nano-gpt.com/pricing) - important ones are {exampleTextModel}, anthropic/claude-opus-5.5, google/gemini-flash-latest, or just any other model you fancy.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.