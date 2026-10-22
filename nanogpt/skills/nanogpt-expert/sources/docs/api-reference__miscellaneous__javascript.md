> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# JavaScript Library

> Node.js library for interacting with NanoGPT API

# NanoGPTJS

[NanoGPTJS](https://github.com/kilkelly/nanogptjs) is a Node.js library designed to interact with NanoGPT's API. This library provides an easy way to integrate NanoGPT's capabilities into your JavaScript applications.

## Overview

The NanoGPT service enables pay-per-prompt interaction with chat and image generation models. You will need a prefilled NanoGPT wallet and API key to use this library effectively.

## Installation

You can install the library using npm:

```bash theme={null}
npm install nanogptjs
```

## Basic Usage

```javascript theme={null}
const NanoGPT = require('nanogptjs');

// Initialize with your API key
const nanogpt = new NanoGPT('your-api-key');

async function chatExample() {
  try {
    const response = await nanogpt.chat({
      model: 'openai/gpt-6.1-sol',
      messages: [
        { role: 'system', content: 'You are a helpful assistant.' },
        { role: 'user', content: 'What is the capital of France?' }
      ]
    });
    
    console.log(response);
  } catch (error) {
    console.error('Error:', error);
  }
}

chatExample();
```

## Features

* **Chat Completions**: Generate text responses using various AI models
* **Image Generation**: Create images from text prompts
* **Model Selection**: Choose from a wide range of available models
* **Balance Management**: Check your NanoGPT balance and manage transactions

## API Methods

### Chat

```javascript theme={null}
const response = await nanogpt.chat({
  model: 'openai/gpt-6.1-sol',
  messages: [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Hello, how are you?' }
  ],
  temperature: 0.7,
  max_tokens: 150
});
```

### Generate Image

```javascript theme={null}
const response = await nanogpt.generateImage({
  prompt: 'A beautiful sunset over the ocean',
  model: 'recraft-v3',
  width: 1024,
  height: 1024
});
```

### Check Balance

```javascript theme={null}
const balance = await nanogpt.checkBalance();
console.log('USD Balance:', balance.usd_balance);
console.log('Nano Balance:', balance.nano_balance);
```

## Error Handling

The library provides robust error handling to manage API response errors:

```javascript theme={null}
try {
  const response = await nanogpt.chat({
    model: 'openai/gpt-6.1-sol',
    messages: [
      { role: 'user', content: 'Hello!' }
    ]
  });
} catch (error) {
  console.error('Status:', error.status);
  console.error('Message:', error.message);
}
```

## Resources

* [GitHub Repository](https://github.com/kilkelly/nanogptjs)
* [NanoGPT API Documentation](https://docs.nano-gpt.com)
* [Get your API Key](https://nano-gpt.com/api)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.