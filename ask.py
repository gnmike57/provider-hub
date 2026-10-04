#!/usr/bin/env python3
"""Ask the speculative gateway from the command line. Beginner-friendly.

    python ask.py "What is 7 times 8?"
    python ask.py --hedge "What is 9 times 9?"      # force the hedge
    python ask.py "urgent: what is 11 times 12?"    # hint words auto-hedge
    python ask.py --no-thinking "..."               # hide the model's reasoning
    python ask.py --plain "..."                     # no ANSI colour
    python ask.py --principal red-1 "..."           # principal for an authz gateway

The model's THINKING is streamed live as it is produced (dimmed), then the
answer. That is the default on both paths: the ring-buffer path forwards
reasoning immediately, and the hedge forwards it live too (HEDGE_LIVE_REASONING=1
on the gateway). Start the gateway first (see docs/run_speculative_gateway.md).

If the gateway runs with AUTHZ_ENFORCED=1, your principal must be in
AUTHORISED_PRINCIPALS - otherwise the gateway correctly answers 403 before any
model is called (this CLI sends X-Principal: ask-cli by default).
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("GATEWAY_URL", "http://127.0.0.1:9000")
DIM, RESET = "\033[2m", "\033[0m"


def main() -> int:
    args = sys.argv[1:]
    hedge = "--hedge" in args
    show_thinking = "--no-thinking" not in args
    use_colour = "--plain" not in args
    principal = "ask-cli"
    if "--principal" in args:
        i = args.index("--principal")
        principal = args[i + 1] if i + 1 < len(args) else principal
        del args[i:i + 2]
    args = [a for a in args if a not in ("--hedge", "--no-thinking", "--plain")]
    if not args:
        print(__doc__)
        return 2
    question = " ".join(args)

    body = {"messages": [{"role": "user", "content": question}], "max_tokens": 400}
    if hedge:
        body["hedge"] = True

    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        json.dumps(body).encode(),
        {"Content-Type": "application/json", "X-Principal": principal},
    )
    dim = (lambda t: f"{DIM}{t}{RESET}") if use_colour else (lambda t: t)
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            thinking_started = answer_started = False
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if "error" in ev:
                    print(f"\n<error: {ev['error']}>")
                    continue
                delta = (ev.get("choices") or [{}])[0].get("delta") or {}
                reasoning = (
                    delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or delta.get("thinking")
                )
                if reasoning and show_thinking:
                    if not thinking_started:
                        print(dim("--- thinking ---"))
                        thinking_started = True
                    print(dim(reasoning), end="", flush=True)
                content = delta.get("content")
                if content:
                    if not answer_started:
                        print(("\n" if thinking_started else "") + dim("--- answer ---")
                              if thinking_started else "")
                        answer_started = True
                    print(content, end="", flush=True)
            print()
    except Exception as exc:
        print(f"gateway unreachable at {BASE} ({exc}). Is it running?")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

