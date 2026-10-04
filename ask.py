#!/usr/bin/env python3
"""Ask the speculative gateway from the command line. Beginner-friendly.

    python ask.py "What is 7 times 8?"
    python ask.py --hedge "What is 9 times 9?"      # force the hedge
    python ask.py "urgent: what is 11 times 12?"    # hint words auto-hedge

Start the gateway first (see docs/run_speculative_gateway.md).
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:9000"


def main() -> int:
    args = sys.argv[1:]
    hedge = "--hedge" in args
    args = [a for a in args if a != "--hedge"]
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
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"gateway unreachable at {BASE} ({exc}). Is it running?")
        return 1

    answer = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "error" in ev:
            answer += f"\n<error: {ev['error']}>"
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            answer += delta["content"]
    print(answer.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
