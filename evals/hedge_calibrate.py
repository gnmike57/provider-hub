"""hedge_calibrate.py - calibrate the speculative hedge's two tunables offline.

  1. COMMIT_TOKENS: how many content tokens must the sovereign emit before the
     gateway commits to it? Too small -> refusals slip through as answers.
     Too large -> the client waits longer on the happy path for nothing.
     Measured here: the token index at which the refusal regex actually fires.

  2. HEDGE_HINT_RE: auto-hedging on a hint word doubles the token spend for that
     request. Measured here: the false-positive rate on realistic prompts.

No network, no model: pure function calls into routing_patterns, so the numbers
are reproducible on any machine and in CI.

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


if __name__ == "__main__":
    main()
