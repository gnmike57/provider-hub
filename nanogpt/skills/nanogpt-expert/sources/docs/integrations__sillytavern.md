> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# SillyTavern

> Using NanoGPT with SillyTavern for character-based chat

export const exampleTextModelName = "GPT 6.1 Sol";

export const exampleTextModel = "openai/gpt-6.1-sol";

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# SillyTavern Integration

Configure NanoGPT:

* Select "OpenAI" as the API type (NanoGPT uses an OpenAI-compatible API)
* Enter your NanoGPT API key
* Set the API URL to: `https://nano-gpt.com/api/v1` (SillyTavern understands the modern `delta.reasoning` stream)
* Set the Model to: <code>{exampleTextModel}</code> (or `anthropic/claude-opus-5.5`, `google/gemini-flash-latest`)

**Important Note**: If you choose the Chat Completions endpoint in SillyTavern, you will see NanoGPT automatically appear as an option.

## Image Generation

SillyTavern has a built-in NanoGPT image source, so you do not need to enter an image API URL.

1. Save your NanoGPT API key under **API Connections** (Chat Completion → NanoGPT). The image source reuses that key.
2. Open **Extensions → Image Generation** and set **Source** to **NanoGPT**.
3. Pick a model from the **Model** list. SillyTavern loads it from NanoGPT's image catalog.
4. Choose a **Resolution** the model supports. SillyTavern defaults to 512x512, which some models reject. GPT Image 2.5, for example, needs at least 1024x1024 (or another supported size such as 1536x1024).

<Note>
  SillyTavern's **OpenAI** image source always calls OpenAI directly and cannot be pointed at NanoGPT. Use the **NanoGPT** source instead.
</Note>

<Note>
  SillyTavern reads images from the inline `b64_json` field. Very large outputs (roughly over 3.5 MB, for example 4K PNGs) are returned as a download `url` instead, which SillyTavern cannot display. Use a smaller resolution if generation fails for large sizes.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.