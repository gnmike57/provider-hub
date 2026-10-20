#!/usr/bin/env node
/**
 * login-task.mjs — Agent TARS login-flow runner
 * =====================================================================
 * Directive: "V2 LARGE MODEL FOR ALL" — this task runs on
 * `abliterated-model-large-v2` (text-only, 1M ctx, GLM-5.3) via the
 * LiteLLM "tars-hybrid-router" on gx10 (http://gx10.ayu-sidewinder.ts.net:4001/v1).
 * The multimodal `abliterated-model` is never referenced here — only the
 * router internally uses a vision sensor. Browser control is 'dom' because
 * the V2 large model is text-only.
 *
 * What it does:
 *   1. Navigates to TARGET_URL
 *   2. Types USERNAME into the username/email field IF one is present
 *   3. Types PASSWORD into the password field IF one is present
 *   4. Clicks the Login / Sign in button
 *   5. Waits ~5 seconds
 *   6. Reports: 1) exact URL  2) page title  3) summary of visible content
 *
 * Usage (after `npm install` in this folder):
 *   node login-task.mjs
 *   node login-task.mjs https://example.com/login alice
 *   node login-task.mjs --url https://example.com/login --username alice --password 'VA2021!'
 *   node login-task.mjs --cli          # force the npx @agent-tars/cli fallback
 *
 * Environment variables (argv flags take precedence):
 *   TARGET_URL   (required — no default)
 *   USERNAME     (optional — Windows caveat: USERNAME is a built-in OS env
 *                 var holding the Windows account name; set TARS_USERNAME
 *                 or pass --username to be explicit)
 *   PASSWORD     (optional — default 'VA2021!')
 *
 * Note: until Abliteration.ai billing is fixed, live model calls may return
 * `insufficient_credits` — that is expected and does not mean this is broken.
 */

import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// ── Model / router configuration (gx10 tars-hybrid-router) ────────────────
const MODEL = {
  provider: 'openai',
  id: 'abliterated-model-large-v2',
  // Key: Windows user env ABLITERATION_API_KEY (installed 2026-10-21); no secret in source.
  apiKey: process.env.ABLITERATION_API_KEY || '',
  baseURL: 'http://gx10.ayu-sidewinder.ts.net:4001/v1',
};

// DOM mode: reliable default for the text-only V2 large model (hybrid would
// need the router's vision bridge; see agent-tars.config.ts for the full rule).
const BROWSER = { control: 'dom', headless: false };

const WORKSPACE = './tars-workspace';

// ── Argument / environment parsing ─────────────────────────────────────────
function parseArgs(argv) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--url') flags.url = argv[++i];
    else if (a === '--username') flags.username = argv[++i];
    else if (a === '--password') flags.password = argv[++i];
    else if (a === '--headless') flags.headless = true;
    else if (a === '--cli') flags.cli = true;
    else if (a === '--help' || a === '-h') flags.help = true;
    else positional.push(a);
  }
  return { positional, flags };
}

const { positional, flags } = parseArgs(process.argv.slice(2));

if (flags.help) {
  console.log('See the header comment of login-task.mjs for usage.');
  process.exit(0);
}

const TARGET_URL = flags.url || process.env.TARGET_URL || positional[0] || '';

// USERNAME is optional. argv > TARS_USERNAME > USERNAME env (Windows caveat
// above: USERNAME is always set on Windows to the OS account name).
const USERNAME =
  flags.username ?? process.env.TARS_USERNAME ?? process.env.USERNAME ?? '';

// PASSWORD default 'VA2021!'.
const PASSWORD =
  flags.password ?? process.env.PASSWORD ?? positional[2] ?? 'VA2021!';

if (!TARGET_URL) {
  console.error(
    '[login-task] TARGET_URL is required.\n' +
      '  Set the TARGET_URL environment variable, or run:\n' +
      '  node login-task.mjs https://example.com/login [username] [password]'
  );
  process.exit(1);
}

// ── Build the agent instruction ─────────────────────────────────────────────
function buildInstruction(targetUrl, username, password) {
  const usernameStep = username
    ? `2. IF a username/email input field is present on the page, type ${JSON.stringify(
        username
      )} into it. If there is no such field, skip this step.`
    : `2. No username was provided — do not type anything into username/email fields (skip this step if such a field exists).`;

  return [
    'You are performing a website login flow. Follow these steps exactly:',
    `1. Navigate to this URL: ${targetUrl}`,
    usernameStep,
    `3. IF a password input field is present on the page, type the password into it (password value: ${JSON.stringify(
      password
    )}). If there is no password field, skip this step.`,
    '4. Click the Login / Sign in / submit button (whichever is present).',
    '5. Wait about 5 seconds for the page to finish loading.',
    '6. Then report the result in EXACTLY this format (nothing else):',
    'URL: <the exact current URL of the page>',
    'TITLE: <the exact page title>',
    'SUMMARY: <a brief summary of the visible content on the page>',
  ].join('\n');
}

const instruction = buildInstruction(TARGET_URL, USERNAME, PASSWORD);

console.log('[login-task] target :', TARGET_URL);
console.log('[login-task] username:', USERNAME ? USERNAME : '(none — password-only login)');
console.log('[login-task] password:', '(provided, hidden)');
console.log('[login-task] model   :', MODEL.id, 'via', MODEL.baseURL);
console.log('[login-task] browser :', BROWSER.control, BROWSER.headless ? '(headless)' : '(headful)');

// ── Primary path: @agent-tars/core ────────────────────────────────────────
async function runViaCore() {
  const { AgentTARS } = await import('@agent-tars/core');

  const agent = new AgentTARS({
    model: { ...MODEL },
    browser: { ...BROWSER, headless: Boolean(flags.headless) },
    planner: { enable: true },
    workspace: WORKSPACE,
  });

  let result;
  try {
    await agent.initialize();
    result = await agent.run(instruction);
  } finally {
    try {
      await agent.cleanup();
    } catch {
      /* best-effort cleanup */
    }
  }

  const text =
    result && typeof result.content === 'string'
      ? result.content
      : JSON.stringify(result, null, 2);

  console.log('\n========== LOGIN TASK REPORT ==========');
  console.log(text);
  console.log('=======================================\n');
}

// ── Fallback path: spawn the Agent TARS CLI (npx) ─────────────────────────
function runViaCli() {
  const configPath = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    'agent-tars.config.ts'
  );

  // Keep the instruction free of double quotes so it is safe to pass through
  // a shell command line on Windows (cmd) and POSIX sh.
  const safeInstruction = instruction.replace(/"/g, "'");

  const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const args = [
    '--yes',
    '@agent-tars/cli@latest',
    '--config',
    configPath,
    '--headless',
    '--input',
    safeInstruction,
    '--format',
    'text',
  ];

  console.log('[login-task] @agent-tars/core unavailable — falling back to npx @agent-tars/cli');

  const child = spawn(npx, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });

  child.on('error', (err) => {
    console.error('[login-task] failed to spawn CLI:', err.message);
    process.exit(1);
  });
  child.on('close', (code) => {
    process.exit(code === null ? 1 : code);
  });
}

// ── Main ───────────────────────────────────────────────────────────────────
try {
  if (flags.cli) {
    runViaCli();
  } else {
    await runViaCore();
  }
} catch (err) {
  const message = err && err.message ? err.message : String(err);
  if (/Cannot find package|MODULE_NOT_FOUND/.test(message)) {
    // @agent-tars/core not installed (or broken install) → CLI fallback.
    runViaCli();
  } else {
    console.error('[login-task] failed:', message);
    process.exit(1);
  }
}

