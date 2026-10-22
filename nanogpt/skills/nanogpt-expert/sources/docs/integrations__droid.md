> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Droid

> Use NanoGPT with the Droid CLI agent

## Quick start

1. Install the Droid CLI: `curl -fsSL https://app.factory.ai/cli | sh`
2. Grab your NanoGPT API key from [nano-gpt.com/api](https://nano-gpt.com/api).

## Configure NanoGPT as a custom model

Add (or merge) the following block into `~/.factory/config.json`:

```json theme={null}
{
  "custom_models": [
    {
      "model_display_name": "GLM Latest",
      "model": "z-ai/glm-latest",
      "base_url": "https://api.nano-gpt.com/api/v1/",
      "api_key": "xxx",
      "provider": "generic-chat-completion-api"
    }
  ]
}
```

* Replace `api_key` with your NanoGPT key and keep it secret.
* If you already have other `custom_models`, just append this object instead of removing the existing ones.
* Keep the trailing slash on `base_url`—Droid expects it when talking to OpenAI-compatible APIs.

## Use it

Start a new terminal and run `droid` to load the config. When prompted for a model, pick **GLM Latest** (or whatever name you set in `model_display_name`) to use NanoGPT through Droid.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.