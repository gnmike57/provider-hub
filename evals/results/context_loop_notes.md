# Context handoff test - loop phase observations (2026-10-07)

## Restored phases (all validated against the live hub)

| phase  | kind   | result | evidence |
| ------ | ------ | ------ | -------- |
| direct | live   | PASS   | catalog 15 models, frost resolved dynamically, status 200, ttft 1.42s, no divert footnote - `context_direct.json` |
| wire   | offline| PASS   | 15/15 assertions (divert, provenance, F6/F7 carry, artefact pruning) - `context_wire.log` |
| loop   | live   | PASS   | 3-turn run: 3/3 canaries retrieval, ttft 4.47 -> 8.79s - `context_loop.json` |

## Transient empty reply (6-turn run, turn 3)

The 6-turn default run failed one turn:

```json
{"turn": 3, "status": 200, "seconds": 48.4, "ttft_s": null, "reply": ""}
```

Classification: a **transient empty-answer response**, not a context loss.
Evidence it is not a handoff/context defect:

* turn 4 (same conversation, sent after the empty turn) echoed CAN-4 and
  listed CAN-1, CAN-2 **and CAN-3** verbatim - the history was intact;
* the final recall probe returned **6/6 canaries verbatim** in 7.3s;
* status was 200 with zero content deltas and no error event.

Known shape from the calibration notes: CYBER-FROST thinks always-on, so a
turn whose budget is consumed by thinking can emit an empty content stream.
The 3-turn run had no such turn. Re-run recorded in `loop6_rerun_stdout.txt`.

## Environment note (not test-related)

`Get-CimInstance Win32_Process` reported **410 python processes**, including
50 duplicate `pdfsitch\bench\.venv\Scripts\pdf-edit-mcp.exe` and 102
`node.exe` (NodeJS LTS). Likely leaked MCP servers / runners from earlier
sessions - worth a cleanup pass, but they were left alone because other live
sessions may own them.
