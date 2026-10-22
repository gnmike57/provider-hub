"""is_multi_item_ask precision pins (2026-10-22 fix).

The old detector counted ANY two ordinal connectives ("then", "also",
"next") as a multi-item ask, so narrative past-tense prose ("I built the
parser, then I ran the tests, then I shipped it.") fired a spurious
COMPLETION_STRICT repair divert / AUTO_TEAM decomposition. Pins:
  - narrative prose with weak connectives only = 0 (single ask)
  - imperative-backed enumerations still count (>= 2)
  - marked lists unchanged
  - MULTI_ITEM_LEGACY_ORDINALS=1 restores the legacy counting (kill switch)
"""
from routing_patterns import is_multi_item_ask


def test_narrative_past_tense_prose_is_a_single_ask():
    assert is_multi_item_ask(
        "I built the parser, then I ran the tests, then I shipped it.") == 0
    assert is_multi_item_ask(
        "Then the server crashed and then the logs rotated.") == 0
    assert is_multi_item_ask(
        "I built the parser and also I ran the tests.") == 0


def test_pure_weak_connectives_never_trigger():
    assert is_multi_item_ask(
        "Also the flake was green. Then the suite passed.") == 0


def test_imperative_backed_enum_is_still_multi_item():
    # strong ordinals + imperative verbs (the pinned legacy case)
    assert is_multi_item_ask(
        "First write the code, then explain it, finally test it.") >= 2
    # comma-lead-in imperatives the old sentence-start-only anchor missed
    assert is_multi_item_ask(
        "Write a function, explain it, and add tests.") >= 2


def test_strong_ordinal_plus_imperative_is_two_items():
    assert is_multi_item_ask("First write the code, then explain it.") == 2


def test_marked_lists_unchanged():
    assert is_multi_item_ask("1. add auth\n2. add tests") == 2


def test_simple_asks_stay_single():
    assert is_multi_item_ask("What is the capital of France?") == 0
    assert is_multi_item_ask("hi") == 0
    assert is_multi_item_ask("") == 0


def test_legacy_kill_switch_restores_weak_connective_counting(monkeypatch):
    monkeypatch.setenv("MULTI_ITEM_LEGACY_ORDINALS", "1")
    # the exact narrative that read 2 before the fix reads 2 again
    assert is_multi_item_ask(
        "I built the parser, then I ran the tests, then I shipped it.") >= 2
