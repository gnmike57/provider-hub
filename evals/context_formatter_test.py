"""context_formatter pins (2026-10-23).

LIVE DEFECT: a TARS tool turn carried a lone reasoning closer tag that
survived prune_artifacts (its regexes only remove PAIRED blocks) and then
raised inside assert_clean() - called from fallback_stream, INSIDE the live
streaming generator, after the response headers were on the wire. uvicorn
aborted the body: the client saw a 200 that just died (no finish marker, no
[DONE]), the access log showed a clean 200 OK, and the watchdog kept
reporting the hub healthy. Pins:
  - prune_artifacts removes EVERY _LEAK_MARKERS entry, paired or orphaned
  - the full leak-marker sweep cannot raise on any marker in any turn
  - the orphan reasoning closer - the exact live killer - is swept
"""
import context_formatter
from context_formatter import _LEAK_MARKERS, assert_clean, prune_artifacts


def test_prune_removes_every_leak_marker_even_orphaned():
    # the invariant is bidirectional: nothing assert_clean forbids may
    # survive stage 3, whether the marker arrives paired, orphaned, or
    # twice
    for marker in _LEAK_MARKERS:
        assert marker not in prune_artifacts(f"ok {marker} tail"), marker
        assert marker not in prune_artifacts(f"ok {marker}{marker} tail"), marker


def test_orphan_reasoning_closer_is_swept():
    # the EXACT live killer: a reasoning closer with no opener in the same
    # turn (TARS tool results carry the tail of a cut reasoning block)
    # the closer tag is 8 codepoints (0x3c 0x2f t-h-i-n-k 0x3e) - the live
    # killer from the TARS tool turn. Built via chr() because the literal
    # renders mangled in some tool output.
    orphan = ("explanation text" + chr(60) + chr(47) + "think" + chr(62)
              + " more text")
    pruned = prune_artifacts(orphan)
    assert pruned == "explanation text more text"
    assert "more text" in pruned and "explanation text" in pruned
    # and the formatter invariant holds afterwards (it used to raise)
    assert assert_clean([{"role": "tool", "content": pruned}]) is True


def test_unclosed_opening_tag_is_swept():
    # the code-review P1-6 sibling: an unclosed opener used to survive too
    unclosed = "answer" + chr(60) + "think" + chr(62) + "leaked deliberation"
    pruned = prune_artifacts(unclosed)
    assert "leaked deliberation" in pruned  # the opener is swept, prose kept
    assert assert_clean([{"role": "tool", "content": pruned}]) is True


def test_paired_blocks_still_prune_wholesale():
    # regression guard: the original paired removals keep working
    assert prune_artifacts("a<thinking>hidden</thinking>b") == "ab"
    assert prune_artifacts("a<|im_start|>b") == "ab"
    assert prune_artifacts("a<system-reminder:x\n\nb") == "a<b"
    # (0.3, 2026-10-23) TAG-form reminders: the paired block is removed
    # wholesale; orphaned openers/closers fall to the marker sweep (the L3
    # bidirectional invariant).
    tag = chr(60) + "system-reminder" + chr(62)
    closer = chr(60) + "/system-reminder" + chr(62)
    assert prune_artifacts("a" + tag + "injected" + closer + "b") == "ab"
    assert prune_artifacts("x" + tag + "orphan opener") == "x>orphan opener"
    assert prune_artifacts("orphan closer" + closer + "y") == "orphan closer>y"
    assert assert_clean([{"role": "user", "content":
                          prune_artifacts("x" + tag + "leak" + closer)}]) is True


def test_specialist_messages_never_leak_markers_into_assert_clean():
    # end to end through the entry point fallback_stream actually uses
    msgs = context_formatter.specialist_messages([
        {"role": "user", "content": "run the tool"},
        {"role": "tool", "tool_call_id": "t1",
         "content": "result" + chr(60) + chr(47) + "think" + chr(62)},
    ])
    assert assert_clean(msgs) is True
