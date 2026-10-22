> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# TypingMind

> Using NanoGPT with TypingMind for an enhanced ChatGPT experience

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

## Quick Start Guide

1. Get your API key from your [API page](https://nano-gpt.com/api)
2. In [TypingMind](https://www.typingmind.com/), go to add custom model
3. Select "Create Manually"
4. Enter the following details:
   * Name: NanoGPT
   * API Type: OpenAI Compatible API
   * Icon URL (Optional): [https://nano-gpt.com/logo.png](https://nano-gpt.com/logo.png)
   * Endpoint: `https://nano-gpt.com/api/v1/chat/completions`
   * Model ID: {exampleTextModel} (or anthropic/claude-opus-5.5, google/gemini-flash-latest)
   * Authorization: Bearer YOUR\_API\_KEY
5. Click "Test" to verify the connection, then "Add Model"

## All the models

We have a v1 models route that now supports detailed model information including pricing when you use `?detailed=true`. You can also find an easy overview of all models on our [pricing page](https://nano-gpt.com/pricing).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.