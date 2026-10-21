// agent-tars.config.ts - gx10 headless runner.
// Operator directive: "V2 LARGE MODEL FOR ALL" - abliterated-model-large-v2
// (text-only GLM-5.3, 1M ctx) via the local tars-hybrid-router on :4001.
// DOM control because V2 large is text-only: Agent TARS reads the page DOM /
// accessibility snapshot as text instead of sending screenshots. (hybrid /
// visual mode also works through the router's vision bridge if ever needed.)
import { defineConfig } from '@agent-tars/interface';

export default defineConfig({
  model: {
    provider: 'openai',
    id: 'abliterated-model-large-v2',
    baseURL: 'http://127.0.0.1:4001/v1',
    // Key: env ABLITERATION_API_KEY (gx10 router.env / Windows user env); no
    // secret in source. On the box, source the env first - the router enforces
    // master_key auth and ABLITERATION_API_KEY == LITELLM_MASTER_KEY:
    //   set -a; source ~/tars-litellm-router/router.env; set +a
    //   agent-tars --config ~/tars-litellm-router/gx10-agent-tars.config.ts
    apiKey: process.env.ABLITERATION_API_KEY ?? '',
  },
  browser: {
    headless: true, // gx10 is a server box - no display
    control: 'dom', // text-only model -> DOM snapshots, never screenshots
  },
  planner: {
    enabled: true,
  },
  workspace: './tars-workspace',
});
