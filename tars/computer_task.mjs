#!/usr/bin/env node
/**
 * computer_task.mjs — Agent TARS computer-use runner with VERIFY-EACH-ACT
 * =====================================================================
 * Phase 3 (T3.1). Spawned by the hub's /v1/computer endpoint:
 *
 *   node tars/computer_task.mjs --url <url> --instruction <text>
 *        [--verify <expectation>] [--headless] --json
 *
 * The per-action loop (F5 closed — screenshots every step):
 *   act -> page.screenshot({encoding:"base64"}) -> caption via the gx10
 *   captioner chain (local gemma3-27b-heretic-vl :4000 first —
 *   vision_bridge caption_image semantics) -> caption + the --verify
 *   expectation go to the V2 Large model as judge ("did the expected
 *   outcome appear? yes/no + why") -> yes: proceed; no: retry the
 *   action ONCE; twice-fail: abort with the captions in the result.
 *
 * Output contract (F4 closed — machine readable): the LAST stdout line is
 *   {"ok":bool,"result":str,"verified":bool|null,
 *    "steps":[{"action","caption","verdict"}]}
 *
 * Selftest (hermetic, no browser, no network, no node_modules):
 *   node tars/computer_task.mjs --selftest
 * runs the loop against three synthetic action streams (pass-first,
 * fail-then-pass, fail-twice) with canned captioner/judge responses and
 * prints one JSON envelope per case.
 *
 * Model config mirrors login-task.mjs :42-48 (V2 Large text-only via the
 * gx10 tars-hybrid-router); the captioner is multimodal.
 */

// ── Model / captioner configuration (mirrors login-task.mjs) ──────────────
const MODEL = {
  provider: 'openai',
  id: 'abliterated-model-large-v2',
  apiKey: process.env.ABLITERATION_API_KEY || '',
  baseURL: 'http://gx10.ayu-sidewinder.ts.net:4001/v1',
};

// Captioner chain: local gemma3-27b-heretic-vl first (gx10 :4000), the
// abliteration multimodal API as fallback. Screenshot -> caption.
const CAPTIONERS = [
  {
    url: process.env.CAPTIONER_URL ||
      'http://gx10.ayu-sidewinder.ts.net:4000/v1/chat/completions',
    model: 'gemma3-27b-heretic-vl',
  },
];

const WORKSPACE = './tars-workspace';

// ── Argument parsing ────────────────────────────────────────────────────────
function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--url') flags.url = argv[++i];
    else if (a === '--instruction') flags.instruction = argv[++i];
    else if (a === '--verify') flags.verify = argv[++i];
    else if (a === '--headless') flags.headless = true;
    else if (a === '--json') flags.json = true;
    else if (a === '--selftest') flags.selftest = true;
    else if (a === '--help' || a === '-h') flags.help = true;
  }
  return flags;
}

// ── The VERIFY-EACH-ACT loop (pure, shared by real mode and selftest) ─────
// actions: [{action: str, do: async () => screenshotBase64 | null}]
// captioner: async (screenshotB64) => caption str
// judge: async (caption, expectation) => {verdict: 'yes'|'no', why: str}
// Returns the envelope object; NEVER throws (errors become captions).
async function verifyEachAct(actions, captioner, judge, expectation) {
  const steps = [];
  let aborted = null;
  for (const step of actions) {
    let passed = false;
    for (let attempt = 0; attempt < 2 && !aborted; attempt++) {
      let caption;
      try {
        const shot = await step.do();
        caption = shot ? await captioner(shot) : '(no screenshot available)';
      } catch (err) {
        caption = `(caption failed: ${String(err).slice(0, 120)})`;
      }
      let verdict = 'yes';
      let why = '';
      if (expectation) {
        try {
          const j = await judge(caption, expectation);
          verdict = j.verdict;
          why = j.why || '';
        } catch (err) {
          verdict = 'no';
          why = `judge failed: ${String(err).slice(0, 120)}`;
        }
      }
      // EVERY attempt is recorded (F5: screenshots every step) - a
      // twice-failed action leaves both captions in steps.
      steps.push({ action: step.action, caption, verdict, why });
      if (verdict === 'yes') {
        passed = true;
        break;
      }
      // verdict 'no': one retry, then abort with both captions recorded.
    }
    if (!passed) {
      aborted = `action "${step.action}" failed verification twice: ${
        steps[steps.length - 1]?.why || 'no reason given'
      }`;
      break;
    }
  }
  return {
    ok: !aborted,
    result: aborted || 'all actions verified',
    verified: aborted ? false : steps.length > 0 ? true : null,
    steps,
  };
}

// ── Real mode: captioner + judge over HTTP, Agent TARS drives the browser ─
import { mkdirSync } from 'node:fs';

async function captionViaChain(screenshotB64) {
  for (const c of CAPTIONERS) {
    try {
      const res = await fetch(c.url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          model: c.model,
          messages: [
            {
              role: 'user',
              content: [
                { type: 'text', text: 'Describe exactly what is visible on this screen.' },
                { type: 'image_url', image_url: { url: `data:image/png;base64,${screenshotB64}` } },
              ],
            },
          ],
          max_tokens: 300,
        }),
      });
      if (!res.ok) continue;
      const data = await res.json();
      const text = data?.choices?.[0]?.message?.content;
      if (text) return String(text).slice(0, 500);
    } catch {
      /* try the next captioner in the chain */
    }
  }
  return '(caption unavailable)';
}

async function judgeViaModel(caption, expectation) {
  const res = await fetch(`${MODEL.baseURL}/chat/completions`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${MODEL.apiKey}`,
    },
    body: JSON.stringify({
      model: MODEL.id,
      messages: [
        {
          role: 'user',
          content:
            `Screenshot caption: ${caption}\n` +
            `Expected outcome: ${expectation}\n` +
            'Did the expected outcome appear? Answer with exactly "yes" or "no" ' +
            'followed by one short sentence why.',
        },
      ],
      max_tokens: 100,
    }),
  });
  const data = await res.json();
  const text = String(data?.choices?.[0]?.message?.content || '').trim();
  return {
    verdict: text.toLowerCase().startsWith('yes') ? 'yes' : 'no',
    why: text.slice(0, 200),
  };
}

async function runRealTask(flags) {
  mkdirSync(WORKSPACE, { recursive: true }); // Agent TARS requires it to exist
  const { AgentTARS } = await import('@agent-tars/core');
  const agent = new AgentTARS({
    model: { ...MODEL },
    browser: { control: 'dom', headless: Boolean(flags.headless) },
    planner: { enable: true },
    workspace: WORKSPACE,
  });
  try {
    await agent.initialize();
    // One coarse act per instruction: the agent run, then a final
    // screenshot of the result state for the verify loop.
    const result = await agent.run(flags.instruction);
    const page = agent.browser?.page || null;
    let shot = null;
    try {
      shot = page ? await page.screenshot({ encoding: 'base64' }) : null;
    } catch {
      shot = null;
    }
    const actions = [
      { action: flags.instruction.slice(0, 120), do: async () => shot },
    ];
    const envelope = await verifyEachAct(
      actions,
      captionViaChain,
      judgeViaModel,
      flags.verify || ''
    );
    envelope.result = `${result?.content || ''}\n${envelope.result}`.trim();
    return envelope;
  } finally {
    try {
      await agent.cleanup();
    } catch {
      /* best-effort cleanup */
    }
  }
}

// ── Selftest: three synthetic cases, canned captioner/judge ────────────────
async function runSelftest() {
  const mkCaption = (label) => async () => label;
  const mkJudge = (sequence) => {
    let i = 0;
    return async () => sequence[i++ % sequence.length];
  };
  const actionList = (names) =>
    names.map((n) => ({ action: n, do: async () => 'b64-screenshot' }));

  const cases = [
    {
      name: 'pass-first',
      actions: actionList(['navigate to target']),
      judge: mkJudge([{ verdict: 'yes', why: 'the hostname is visible' }]),
    },
    {
      name: 'fail-then-pass',
      actions: actionList(['click the files link']),
      judge: mkJudge([
        { verdict: 'no', why: 'page still loading' },
        { verdict: 'yes', why: 'the file tree is visible now' },
      ]),
    },
    {
      name: 'fail-twice',
      actions: actionList(['read /etc/hostname']),
      judge: mkJudge([
        { verdict: 'no', why: 'error page' },
        { verdict: 'no', why: 'still the error page' },
      ]),
    },
  ];
  for (const c of cases) {
    const envelope = await verifyEachAct(
      c.actions,
      mkCaption(`caption of ${c.actions[0].action}`),
      c.judge,
      'the expected outcome is visible'
    );
    console.log(JSON.stringify(envelope));
  }
}

// ── Main ───────────────────────────────────────────────────────────────────
const flags = parseArgs(process.argv.slice(2));

if (flags.selftest) {
  runSelftest()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error(String(err));
      process.exit(1);
    });
} else if (!flags.instruction) {
  console.error(
    '[computer-task] --instruction is required (or --selftest). See the header comment.'
  );
  process.exit(1);
} else {
  runRealTask(flags)
    .then((envelope) => {
      console.log(JSON.stringify(envelope));
      process.exit(0); // the envelope carries the verdict
    })
    .catch((err) => {
      // Failure contract: still a JSON last line, ok:false.
      console.log(
        JSON.stringify({ ok: false, result: String(err).slice(0, 300), verified: false, steps: [] })
      );
      process.exit(0);
    });
}
