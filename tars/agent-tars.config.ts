/**
 * Agent TARS CLI configuration — "V2 LARGE MODEL FOR ALL"
 *
 * Every TARS surface on this machine talks to the abliterated-model-large-v2
 * (text-only, 1M context, GLM-5.3) served through the LiteLLM
 * "tars-hybrid-router" on the gx10 (tailnet: gx10.ayu-sidewinder.ts.net,
 * port 4001 — port 4000 is the existing local hub, 4001 is the new router).
 *
 * The multimodal `abliterated-model` NEVER appears here: only the router
 * internally uses a vision sensor to caption screenshots into structured text.
 *
 * Usage with the CLI:
 *   npx @agent-tars/cli@latest --config ./agent-tars.config.ts
 * (also loadable by login-task.mjs / any @agent-tars/core program)
 *
 * NOTE on live calls: until Abliteration.ai billing is fixed, requests may
 * return `insufficient_credits` — this config is correct regardless.
 */

// defineConfig gives full TypeScript type-checking for the config file
// (AgentTARSAppConfig). Verified on @agent-tars/interface@0.3.1: the
// package root does NOT runtime-export defineConfig, and the documented
// '@agent-tars/cli/config' subpath does not exist in the published CLI.
// The working, tested import (ESM + CJS/jiti, which is how the CLI loads
// this file) is the './define-config' subpath of @tarko/interface — the
// upstream of the @agent-tars/interface config family, hoisted into
// node_modules by @agent-tars/interface itself.
import { defineConfig } from '@tarko/interface/define-config';
import type { AgentTARSAppConfig } from '@agent-tars/interface';

export default defineConfig({
  // ── Model ────────────────────────────────────────────────────────────────
  // OpenAI-compatible provider pointed at the gx10 tars-hybrid-router.
  // The router translates every request to the text-only V2 large model.
  model: {
    provider: 'openai',
    id: 'abliterated-model-large-v2',
    // Key: Windows user env ABLITERATION_API_KEY (installed 2026-10-21); no secret in source.
    apiKey: process.env.ABLITERATION_API_KEY ?? '',
    baseURL: 'http://gx10.ayu-sidewinder.ts.net:4001/v1',
    // V2 large has a 1M-token context; Agent TARS defaults maxTokens to 8192.
    // maxTokens: 32768, // ← uncomment if you want a larger generation window.
  },

  // ── Browser ───────────────────────────────────────────────────────────────
  // DOM-VS-HYBRID RULE:
  //   'dom'      — pure DOM analysis/interaction (fastest, most reliable).
  //                Works with TEXT-ONLY models because the accessibility
  //                tree/DOM snapshot is already textual.
  //   'hybrid'   — mixes DOM + visual grounding (screenshots). Needs a VISION
  //                bridge: the model must be able to read images. The gx10
  //                router makes this possible (it captions screenshots to
  //                structured text before forwarding to the V2 large model),
  //                but 'dom' remains the RELIABLE DEFAULT for the V2 large
  //                model — no caption round-trip, no grounding ambiguity.
  //   'visual-grounding' — pure screenshot control; same vision-bridge
  //                dependency as hybrid.
  // We use 'dom' because abliterated-model-large-v2 is text-only.
  browser: {
    control: 'dom',
    // Headful on Windows so the operator can watch/troubleshoot the flow.
    headless: false,
  },

  // ── Planner ───────────────────────────────────────────────────────────────
  // Structured planning for multi-step tasks (login flows, research, etc.).
  // (The runtime option is `enable` — `AgentTARSPlannerOptions.enable`.)
  planner: {
    enable: true,
  },

  // ── Workspace ─────────────────────────────────────────────────────────────
  // All filesystem operations are scoped to this directory.
  workspace: './tars-workspace',

  // ── Optional ──────────────────────────────────────────────────────────────
  // Uncomment to run the Web UI server headlessly instead of the CLI UI:
  // server: {
  //   port: 8888,
  //   storage: { type: 'sqlite' },
  // },
});
