> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Brave

> Brave provider notes

# Brave

Brave is supported as a standard web search provider in NanoGPT.

For primary usage, use the main web search docs:

* [Chat Completion web search](/api-reference/endpoint/chat-completion)
* [Direct Web Search API (`POST /api/web`)](/api-reference/endpoint/web-search)
* [Web Search in Text Generation Guide](/api-reference/text-generation)

## Common usage

* `webSearch.provider: "brave"`
* Model suffixes: `:online/brave` and `:online/brave-deep`

## Notes

* Provider pricing is documented in the web search pricing tables.
* BYOK support is provider-dependent; see [BYOK](/api-reference/miscellaneous/byok).
* If Brave model IDs appear in `GET /api/v1/models`, you can use them like any other model ID.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.