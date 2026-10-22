> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nano-gpt.com/llms.txt
> Use this file to discover all available pages before exploring further.

# RisuAI

> Using NanoGPT with RisuAI for chat and character-based conversations

# RisuAI Integration

Use this guide to connect RisuAI to NanoGPT so you can run your chats through NanoGPT models.

## Before You Start

1. Create or log in to your NanoGPT account.
2. Generate your API key at [nano-gpt.com/api](https://nano-gpt.com/api).
3. Open [risuai.xyz](https://risuai.xyz/).

If RisuAI shows onboarding, skip it. NanoGPT is configured in the main settings.

## Step-by-Step Setup

1. From the RisuAI home screen, open the left menu (hamburger icon), then go to **Settings**.
   <Frame>
     <img src="https://mintcdn.com/nano-gpt/JZU2VneOQbGbp1Of/images/risuai-01.png?fit=max&auto=format&n=JZU2VneOQbGbp1Of&q=85&s=7cd244a9d1314e5803c7da6f33e8e64e" alt="Open the menu and go to Settings in RisuAI" style={{ borderRadius: '0.5rem' }} width="4480" height="2354" data-path="images/risuai-01.png" />
   </Frame>
2. In **Settings**, open the **Chat Bot** panel.
   <Frame>
     <img src="https://mintcdn.com/nano-gpt/JZU2VneOQbGbp1Of/images/risuai-02.png?fit=max&auto=format&n=JZU2VneOQbGbp1Of&q=85&s=4916355e93fdbedcf84026f06ba9b15b" alt="Open the Chat Bot settings panel in RisuAI" style={{ borderRadius: '0.5rem' }} width="4480" height="2354" data-path="images/risuai-02.png" />
   </Frame>
3. Set both of these fields to **NanoGPT**:
   * **Model**
   * **Auxiliary Model**
   <Frame>
     <img src="https://mintcdn.com/nano-gpt/JZU2VneOQbGbp1Of/images/risuai-03.png?fit=max&auto=format&n=JZU2VneOQbGbp1Of&q=85&s=f0e78571ffff8d937fee0cd9e2533b6a" alt="Set both Model and Auxiliary Model to NanoGPT in RisuAI" style={{ borderRadius: '0.5rem' }} width="4480" height="2354" data-path="images/risuai-03.png" />
   </Frame>
4. Paste your key from [nano-gpt.com/api](https://nano-gpt.com/api) into **NanoGPT API Key**.
5. If you have a NanoGPT subscription, enable **Use subscription endpoint & models**.
   * If this is not enabled, RisuAI uses pay-as-you-go mode by default.
   <Frame>
     <img src="https://mintcdn.com/nano-gpt/JZU2VneOQbGbp1Of/images/risuai-04.png?fit=max&auto=format&n=JZU2VneOQbGbp1Of&q=85&s=faec3c7a085123c53acf2afc42efce12" alt="Enable subscription endpoint and select NanoGPT model settings in RisuAI" style={{ borderRadius: '0.5rem' }} width="4478" height="2350" data-path="images/risuai-04.png" />
   </Frame>
6. Choose your model in **NanoGPT Model**:
   * **Select from List** to browse available models.
   * **Manual Input** if the model list does not load or you want to enter a model ID directly.
7. Optional: enable **Response Streaming** for streamed output.

## Pay-As-You-Go Provider Selection

In pay-as-you-go mode, some models expose multiple providers. RisuAI will show provider options with pricing so you can compare and choose.

<Frame>
  <img src="https://mintcdn.com/nano-gpt/JZU2VneOQbGbp1Of/images/risuai-05.png?fit=max&auto=format&n=JZU2VneOQbGbp1Of&q=85&s=528198c98503c083d017060b7cd1bbd9" alt="Compare provider options and pricing in RisuAI pay-as-you-go mode" style={{ borderRadius: '0.5rem' }} width="2572" height="812" data-path="images/risuai-05.png" />
</Frame>

## Quick Troubleshooting

* Model list not loading: switch to **Manual Input** and enter the model ID.
* Unexpected pricing mode: verify whether **Use subscription endpoint & models** is enabled.
* Auth errors: confirm your NanoGPT API key is valid and pasted without extra spaces.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.