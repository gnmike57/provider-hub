"""Consolidated Desktop report: speculative system + Hive/Frost integration.

Reads whatever run artifacts exist and writes one markdown file to the Desktop.
Repeatable - re-run after more evidence lands:
  evals/results/hive_primary_hedge.json   (live hedge results per Hive model)
  evals/results/hive_redteam_stages.json  (staged refusal red-team, if finished)
"""
import io
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
R = ROOT / "evals" / "results"
DESK = Path(os.path.expanduser("~")) / "Desktop"

FROST = {
    "deepseek-ai/deepseek-v4.1-flash": "DeepFrost v4.1",
    "zai-org/glm-5.3-flash": "GLMFrost 5.3 Flash",
    "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw": "CyberFrost 3.8 SAGE",
}


def load(name):
    p = R / name
    if not p.exists():
        return []
    try:
        return json.loads(io.open(p, encoding="utf-8").read())
    except json.JSONDecodeError:
        return []


def defects_section(L):
    L.append("## Defects found and fixed (each with an offline regression test)")
    L.append("")
    L.append("| # | defect | symptom (measured live) | fix | evidence |")
    L.append("| --- | --- | --- | --- | --- |")
    L.append("| 1 | hedge never sent an output cap | Hive models spent the budget on hidden "
             "reasoning; GLM returned **0 chars** of content | hedge + gateway now send "
             "`max_completion_tokens` alongside `max_tokens` | `evals/hedge_budget_test.py`; "
             "probe: max_tokens=2000 -> 0ch vs max_completion_tokens=2000 -> 6461ch |")
    L.append("| 2 | empty sovereign was committed to the client | a finish with 0 content tokens "
             "shipped a blank 200 with no footnote and no signal | empty-sovereign rule diverts "
             "instead of committing (`hedge_empty_sovereign_total`) | `evals/hedge_empty_test.py`; "
             "the GLM live case now DIVERTS to CyberFrost |")
    L.append("| 3 | registry aliases were never resolved | `model: \"deepfrost-v4.1\"` went "
             "upstream verbatim -> `Invalid Model Name`; `providers.py` was not even imported by "
             "the gateway | Frost names resolve to slot + exact upstream id | "
             "`evals/frost_alias_test.py` (6 tests) |")
    L.append("| 4 | a dead async test | `test_read_json_body_counts_streamed_bytes` never ran "
             "(\"async functions are not natively supported\") | driven with `anyio.run` | suite "
             "90 passed/1 failed -> **97 passed/0 failed** |")
    L.append("")


def hedge_section(L, hedge):
    L.append("## Live speculative hedge with Hive primaries")
    L.append("")
    if not hedge:
        L.append("_no hedge results yet_")
        L.append("")
        return
    L.append("| model (Frost name) | case | result | ttft | total | reasoning | note |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in hedge:
        note = "; ".join(r.get("notes", []))[:70]
        L.append(f"| `{r['model']}` ({FROST.get(r['model'], '?')}) | {r['case']} | "
                 f"{'PASS' if r.get('pass') else 'FAIL'} | {r.get('ttft_s')}s | "
                 f"{r.get('seconds')}s | {r.get('reasoning_chars')}ch | {note} |")
    L.append("")


def redteam_section(L, red):
    L.append("## Staged refusal red-team (S1 benign -> S6 injection)")
    L.append("")
    if not red:
        L.append("_still running; the runner writes `hive_refusal_redteam_<stamp>.md` with "
                 "every reply when it finishes, and re-running this script folds it in_")
        L.append("")
        return
    by = defaultdict(Counter)
    for r in red:
        by[(r["model"], r["pass"])][r["outcome"]] += 1
    L.append("| model | specialist frame | ANSWERED | DIVERTED | EMPTY | ERROR |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for (m, p), c in sorted(by.items()):
        L.append(f"| `{m}` ({FROST.get(m, '?')}) | {p} | {c['ANSWERED']} | "
                 f"{c['DIVERTED']} | {c['EMPTY']} | {c['ERROR']} |")
    L.append("")
    L.append("### Every staged prompt: what the system did")
    L.append("")
    L.append("| stage | prompt | model | frame | expect | outcome | seconds | reasoning |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in red:
        L.append(f"| {r['stage']} | `{r['id']}` | {FROST.get(r['model'], r['model'])} | "
                 f"{r['pass']} | {r['expected_refusal']} | {r['outcome']} | "
                 f"{r['seconds']} | {r['reasoning_chars']}ch |")
    L.append("")
    L.append("Replies (verbatim, 2500 chars each) are in the companion file written by the "
             "runner. `auth` = the specialist was given the operator's in-house "
             "authorization frame; compare the two columns for its effect.")
    L.append("")


def endpoints_section(L):
    L.append("## Published endpoints (tailnet 100.113.176.84, bind 0.0.0.0)")
    L.append("")
    L.append("| port | model field | Frost name | backend |")
    L.append("| --- | --- | --- | --- |")
    L.append("| 9310 | any Frost name or raw id | general | Hive (default DeepFrost) + CyberFrost worker |")
    L.append("| 9311 | optional | DeepFrost v4.1 | Hive `deepseek-ai/deepseek-v4.1-flash` |")
    L.append("| 9312 | optional | GLMFrost 5.3 Flash | Hive `zai-org/glm-5.3-flash` |")
    L.append("| 9313 | optional | CyberFrost 3.8 SAGE | gx10 hub `CYBER-FROST-3.8-EXL3-SAGE-3.87bpw` |")
    L.append("| 9314 | optional | DeepFrost Max Think | Hive `deepseek-ai/deepseek-v4.1-flash` (max-think, no hedge) |")
    L.append("| 9315 | optional | GLMFrost Max Think | Hive `zai-org/glm-5.3-flash` (max-think, no hedge) |")
    L.append("")
    L.append("```bash")
    L.append("# from any tailnet peer (verified from the gx10):")
    L.append("curl http://100.113.176.84:9310/v1/chat/completions -H 'Content-Type: application/json' \\")
    L.append("  -d '{\"model\":\"DeepFrost v4.1\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":300,\"hedge\":true}'")
    L.append("```")
    L.append("")
    L.append("* `\"hedge\": true` forces the speculative dual-dispatch; omitting it means the "
             "hedge fires only on the latency hints.")
    L.append("* Frost names verified live: `DeepFrost v4.1` reached Hive as "
             "`deepseek-ai/deepseek-v4.1-flash`; `CyberFrost 3.8 SAGE` routed to the worker slot.")
    L.append("* **9301 belongs to the ufo bridge** - publishing there fails silently "
             "(winerror 10048), which is why the Frost ports start at 9310.")
    L.append("* Start/stop them with `python tools/hive/serve_endpoints.py`.")
    L.append("")


def main():
    hedge = load("hive_primary_hedge.json")
    red = load("hive_redteam_stages.json")
    L = []
    L.append(f"# Speculative system + Frost report - {time.strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    L.append("Provider-hub interception gateway: Hive models as primaries, CYBER-FROST as the "
             "divert target, Frost names as the public ids. Generated by "
             "`tools/hive/make_report.py`.")
    L.append("")
    defects_section(L)
    hedge_section(L, hedge)
    redteam_section(L, red)
    endpoints_section(L)
    L.append(f"_generated {time.strftime('%Y-%m-%d %H:%M:%S')}_")
    out = DESK / "frost_speculative_system_report.md"
    io.open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"wrote {out} ({len(hedge)} hedge rows, {len(red)} redteam rows)")


if __name__ == "__main__":
    main()

