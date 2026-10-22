"""hedge_calibrate.py - calibrate the speculative hedge's two tunables offline.

  1. COMMIT_TOKENS: how many content tokens must the sovereign emit before the
     gateway commits to it? Too small -> refusals slip through as answers.
     Too large -> the client waits longer on the happy path for nothing.
     Measured here: the token index at which the refusal regex actually fires.

  2. HEDGE_HINT_RE: auto-hedging on a hint word doubles the token spend for that
     request. Measured here: the false-positive rate on realistic prompts.

No network, no model: pure function calls into routing_patterns, so the numbers
are reproducible on any machine and in CI.

PROBE + TEST MODE (2026-10-21): the report half is now ASSERTIVE - the
collected stats (fire indices, hedge confusion counts) are returned by
main() and pinned by the pytest layer at the bottom of this file, so the
COMMIT_TOKENS=10 calibration and the footnote-order invariants fail CI the
moment the regex or the footnote contract drifts.

    python3 evals/hedge_calibrate.py            # report
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routing_patterns import HEDGE_HINT_RE, is_routable, normalise, should_hedge  # noqa: E402

# Refusals a real model actually opens with (harvested from live CYBER-FROST /
# cloud runs), plus the formatting variants that could defeat an anchored regex.
REFUSALS = [
    "I cannot help with that.",
    "I can't assist with this request.",
    "I'm sorry, but I can't do that.",
    "I am unable to comply with this request.",
    "Sorry, but I cannot provide that information.",
    "I must decline this request.",
    "As an AI language model, I cannot provide instructions for that.",
    "I won't be able to help with that.",
    "I'm not allowed to assist with this.",
    "I am not authorized to perform this action.",
    "\nI cannot help with that.",
    "   I can't do that.",
    "I can\u2019t help with that.",          # curly apostrophe -> normalise() folds it
    "I\u2019m sorry, but I can\u2019t assist.",
    "**I cannot help with that.**",         # markdown prefix
    "- I cannot help with that.",           # bullet prefix
    "I cannot help with that.\n\nHowever,",  # refusal then continues
    "Against my guidelines, I will not.",   # a real (mid-phrase) refusal opening
    "Here is why models say 'I cannot help':",  # answer ABOUT refusals: should NOT fire
    "Certainly! I cannot help with that.",  # not a refusal opening: should NOT fire
]
NOT_REFUSALS = {
    "Here is why models say 'I cannot help':",
    "Certainly! I cannot help with that.",
}

# Realistic prompts. `urgent=True` means a hedge is DESERVED (true positive);
# urgent=False means hedging is wasted money (false positive) if it fires.
PROMPTS = [
    ("Refactor the streaming reader to reuse one buffer.", False),
    ("Explain how live migration works in Kubernetes.", False),
    ("Write a fast Fourier transform in Python.", False),
    ("Give me a quicksort implementation with tests.", False),
    ("How does real-time clock synchronization work?", False),
    ("What is the fastest sorting algorithm in practice?", False),
    ("Show me a live example of a deadlock.", False),
    ("Write unit tests for the live-reload file watcher.", False),
    ("Describe how ASAP scheduling works in networking.", False),
    ("What does the FAST TCP congestion control do?", False),
    ("Implement a live-updating dashboard with websockets.", False),
    ("Batch-convert 500 rows of CSV to JSON.", False),
    ("Summarize this 40 page PDF into 5 bullets.", False),
    ("Fix the off-by-one in the pagination helper.", False),
    ("Urgent: rotate the API keys before the deadline.", True),
    ("I need this immediately, the demo starts in 5 minutes.", True),
    ("Optimize this query for low latency.", True),
    ("Give me the answer quickly, the user is waiting.", True),
    ("Answer asap - production is down.", True),
    ("Right now, tell me the current error rate.", True),
]

# Measured on the gx10 (bench_calibrate.py, 2026-10-05): sustained decode rate.
TOK_PER_S = 42.3


def tokenise(text):
    """Approximate the model's stream granularity: word-ish chunks."""
    return [t for t in normalise(text).split(" ") if t]


def refusal_fire_index(text):
    """Index of the content token at which is_routable first fires, else None.

    Mirrors the hedge: it screens the accumulated delta.content after every
    content token and diverts as soon as the anchored regex matches.
    """
    acc = ""
    for i, tok in enumerate(tokenise(text), start=1):
        acc = (acc + " " + tok).strip()
        if is_routable(acc):
            return i
    return None


def main():
    print("== 1. refusal detection vs COMMIT_TOKENS ==")
    print(f"   (decode rate measured on the box: {TOK_PER_S} tok/s)")
    hits, idxs, missed = 0, [], []
    for text in REFUSALS:
        idx = refusal_fire_index(text)
        if idx:
            hits += 1
            idxs.append(idx)
            print(f"   fire@{idx:2d} tok  {text[:52]!r}")
        else:
            missed.append(text)
            tag = "expected (not a refusal)" if text in NOT_REFUSALS else "!! MISSED"
            print(f"   no fire      {text[:52]!r}   {tag}")
    if idxs:
        ordered = sorted(idxs)
        median = ordered[len(ordered) // 2]
        print(f"\n   refusals detected: {hits}/{len(REFUSALS)}")
        print(f"   detection index: min={min(idxs)} median={median} max={max(idxs)} tokens")
        print(f"   -> a commit window of {max(idxs)} catches every detectable refusal")
        print("\n   happy-path cost of the window (the gateway holds the buffer, so the")
        print("   client waits this long for the FIRST visible token):")
        for c in (5, 10, 25, 50, 100):
            print(f"      COMMIT_TOKENS={c:3d}  ->  {c / TOK_PER_S:4.2f}s held before content")
    unexpected = [m for m in missed if m not in NOT_REFUSALS]
    if unexpected:
        print("\n   !! undetected refusals (regex gap: each leaks a refusal as an answer):")
        for m in unexpected:
            print(f"      {m!r}")

    print("\n== 2. auto-hedge hint false-positive rate ==")
    tp = fp = tn = fn = 0
    fp_examples = []
    for text, deserves in PROMPTS:
        fired = should_hedge(text)
        if fired and deserves:
            tp += 1
        elif fired and not deserves:
            fp += 1
            fp_examples.append(text)
        elif deserves:
            fn += 1
        else:
            tn += 1
    print(f"   prompts={len(PROMPTS)}  deserved={tp + fn}  triggered={tp + fp}")
    print(f"   true positive  (deserved + fired): {tp}")
    print(f"   false positive (fired, NOT urgent): {fp}  <- each costs 2x tokens for nothing")
    print(f"   false negative (urgent, no fire)  : {fn}")
    print(f"   false-positive rate on non-urgent asks: {fp / max(1, fp + tn):.0%}")
    if fp_examples:
        print("   wasted hedges:")
        for text in fp_examples:
            match = HEDGE_HINT_RE.search(text)
            print(f"      matched {match.group(0)!r:12s} in {text[:58]!r}")

    # Collect (not just print) the stats so the pytest layer can pin them.
    return {
        "detected": hits,
        "total": len(REFUSALS),
        "missed": missed,
        "unexpected_misses": unexpected,
        "max_fire_index": max(idxs) if idxs else None,
        "median_fire_index": sorted(idxs)[len(idxs) // 2] if idxs else None,
        "hedge": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


if __name__ == "__main__":
    stats = main()
    # Exit non-zero ONLY on a real regex gap: a refusal the anchored ROUTING_RE
    # never detects. Everything else (window size, hedge FPs) is calibration
    # commentary, not a failure - the pytest layer pins those as invariants.
    raise SystemExit(1 if stats["unexpected_misses"] else 0)


# ---------------------------------------------------------------------------
# pytest layer (2026-10-21): pins the calibration INVARIANTS the gateway was
# sized against, so a regex/footnote/commit-window drift fails CI instead of
# silently re-opening the gaps the 2026-10-05/10-21 calibrations closed.
#   * COMMIT_TOKENS=10 (BUFFER_CONTENT_TOKENS default, proxy_gateway.py:251)
#     must still cover every detectable refusal opening (max fire index <= 10)
#     while every answer-shaped opener stays below the anchor;
#   * the divert stream's provenance footnote keeps its contract: verbatim
#     specialist answer -> footnote delta -> finish_reason=stop -> [DONE].
# ---------------------------------------------------------------------------

import os  # noqa: E402

import httpx  # noqa: E402

# The `script` fixture (and SSE builders) from the shared harness. Importing
# `script` at module level is what registers it with pytest (hedge_test.py
# pattern).
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: E402,F401


def test_commit_tokens_10_still_catches_every_detectable_refusal():
    """The pinned BUFFER_CONTENT_TOKENS=10 default (proxy_gateway Settings)
    must cover the worst-case detection index across the refusal battery."""
    stats = main()
    assert stats["detected"] == stats["total"] - len(NOT_REFUSALS)
    assert not stats["unexpected_misses"]
    shipped_default = int(os.getenv("BUFFER_CONTENT_TOKENS", "10"))
    assert shipped_default == 10, (
        "BUFFER_CONTENT_TOKENS default moved; re-run this calibration before "
        "trusting the commit window"
    )
    assert stats["max_fire_index"] <= shipped_default, (
        "a refusal now fires after the 10-token commit window: either the "
        "window must grow (latency cost) or the regex was loosened"
    )
    # Median 2 was the calibration headline (detection is nearly instant).
    assert stats["median_fire_index"] == 2


def test_answer_shaped_openers_stay_unrouted():
    """The two NOT_REFUSALS must remain non-detections: an answer ABOUT
    refusals must never divert (the whole point of the anchor)."""
    for text in NOT_REFUSALS:
        assert refusal_fire_index(text) is None, text
        assert not is_routable(text), text


def test_gateway_footnote_order_after_a_divert(script, monkeypatch):  # noqa: F811
    """Divert-stream contract: the verbatim specialist answer ships first,
    then the provenance footnote delta, then finish_reason=stop, then [DONE].
    The old probe only printed; this asserts the order."""
    import json

    import proxy_gateway
    from fastapi.testclient import TestClient

    def _make():
        return httpx.AsyncClient(transport=httpx.MockTransport(script))

    monkeypatch.setattr(proxy_gateway, "make_client", _make)
    s = proxy_gateway.SETTINGS
    s.primary_api_url, s.primary_api_key, s.primary_model = PRIMARY, "", "primary"
    s.fallback_api_url, s.fallback_api_key, s.fallback_model = WORKER, "none", "worker"
    s.buffer_content_tokens = 10  # the calibrated COMMIT_TOKENS under test
    s.buffer_reasoning = 0
    s.audit_log = ""
    s.authz_enforced = False
    s.keepalive_url = ""
    s.specialist_system_mode = "neutral"

    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    text = resp.text

    # Walk the SSE stream and record what each data line carries.
    kinds = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            kinds.append("done")
            continue
        ev = json.loads(payload)
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            kinds.append("footnote" if "taking over" in delta["content"] else "content")
        elif ev.get("choices", [{}])[0].get("finish_reason"):
            kinds.append("finish")

    # The divert DID happen (the helm refusal reached the specialist path)...
    assert script.calls and any(c["url"] == WORKER for c in script.calls)
    # ...and the shipped order is exactly: content, footnote, finish, [DONE].
    assert kinds == ["content", "footnote", "finish", "done"]
