# Context handoff test - loop phase observations (2026-10-07)

## Restored phases (all validated against the live hub)

| phase  | kind   | result | evidence |
| ------ | ------ | ------ | -------- |
| direct | live   | PASS   | catalog 15 models, frost resolved dynamically, status 200, ttft 1.42s, no divert footnote - `context_direct.json` |
| wire   | offline| PASS   | 15/15 assertions (divert, provenance, F6/F7 carry, artefact pruning) - `context_wire.log` |
| loop   | live   | PASS   | 3-turn run: 3/3 canaries retrieval, ttft 4.47 -> 8.79s - `context_loop.json` |

## Empty reply on compound turns - root-caused and fixed

Both 6-turn runs failed early turns with `status 200, ttft null, reply ""`
(48.4s, then 33.8s + 44.1s on the re-run). Evidence it was **budget
exhaustion, not context loss or a handoff defect**:

* turn 3 is the first turn whose prompt is compound (acknowledge the canary
  AND list every prior term); it failed in both runs;
* elapsed 34-48s at ~45 tok/s is ~1500-2100 generated tokens - more than the
  old 1200 budget, and thinking is always-on on CYBER-FROST (the hub ignores
  `enable_thinking:false`), so the budget was consumed before any content;
* the NEXT turn rebuilt every missing canary verbatim, and the final probe
  returned **6/6 canaries** - the conversation was never truncated.

Fix: per-turn `max_tokens` 1200 -> 2400 in `part_loop` (both the turn loop and
the final recall probe). Verified: full 6-turn run now passes every turn with
echo=OK and recall_prior=OK, final probe 6/6, ttft 3.59 -> 5.85s
(`loop7_stdout.txt`).

## Environment note (not test-related)

`Get-CimInstance Win32_Process` reported **410 python processes**, including
50 duplicate `pdfsitch\bench\.venv\Scripts\pdf-edit-mcp.exe` and 102
`node.exe` (NodeJS LTS). Likely leaked MCP servers / runners from earlier
sessions - worth a cleanup pass, but they were left alone because other live
sessions may own them.
