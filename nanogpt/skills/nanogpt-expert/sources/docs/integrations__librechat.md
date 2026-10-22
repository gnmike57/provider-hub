> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# LibreChat

> Using NanoGPT with LibreChat for a ChatGPT-like interface

<Note>
  These examples use the website API host, which currently lists their recommended models. The direct API host can have a different catalog during rollouts. For larger requests or longer runtimes, use `https://api.nano-gpt.com/api/v1` with a model from that host's catalog. See [API Hosts](/api-reference/miscellaneous/api-hosts) for limits and availability checks.
</Note>

# Using LibreChat with NanoGPT

A quick guide to setting up LibreChat with NanoGPT's API.

## Setup Instructions

1. Get your API key from [nano-gpt.com/api](https://nano-gpt.com/api)
2. Locate your LibreChat installation's `librechat.example.yml` file
3. Create a copy named `librechat.yml`
4. Add the following configuration to your `librechat.yml`:

```yaml theme={null}
# NanoGPT Example
- name: 'NanoGPT'
  apiKey: '${NANO_GPT_API_KEY}'
  baseURL: 'https://nano-gpt.com/api/v1/'
  models:
      default: [
        "openai/gpt-6.1-sol",
        "anthropic/claude-opus-5.5",
        "google/gemini-flash-latest",
        ]
      fetch: true
  addParams:
    reasoning_content_compat: true
  titleConvo: true
  titleModel: 'openai/gpt-6.1-sol'
  modelDisplayLabel: 'NanoGPT'
  iconUrl: https://nano-gpt.com/logo.png
```

LibreChat currently streams internal thinking from the legacy `reasoning_content` field. The `addParams` block above enables NanoGPT's compatibility shim so LibreChat can render thoughts without additional changes. If you would rather not send the compatibility flag, you can instead point LibreChat at `https://nano-gpt.com/api/v1legacy/` which keeps the legacy response shape by default.

5. Set your API key in your environment variables:
   ```bash theme={null}
   export NANO_GPT_API_KEY='your-api-key-here'
   ```

That's it! Restart LibreChat, and you'll have access to all NanoGPT models through the interface.

## Available Models

You can access all our models through this integration, including:

* GPT 6.1 Sol
* Claude Opus 5.5
* Gemini Flash Latest
* Perplexity
* And many more!

For a complete list of available models and their pricing, visit our [pricing page](https://nano-gpt.com/pricing).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.