"""Script-aware coverage judges (2026-10-22 fix).

_completion_uncovered / _conductor_implicated used to tokenize with
[a-z0-9]+, so a CJK or Cyrillic checklist item had ZERO significant words
and was silently judged "covered" (probed live: a Chinese item over a
completely unrelated Chinese answer = [] uncovered -> the repair divert
never fired). Pins:
  - CJK/Cyrillic items over non-matching answers = UNCOVERED
  - CJK/Cyrillic items over matching answers = covered
  - ASCII behaviour is unchanged (regression pin)
  - _conductor_implicated judges non-Latin items too
"""
from proxy_gateway import _completion_uncovered, _conductor_implicated


def _checklist(*items):
    """Numbered checklist block (the _COMPLETION_RE contract: every item
    line is a numbered `N.` or `N)` line)."""
    lines = "\n".join(
        "{}. {}".format(i + 1, it) for i, it in enumerate(items))
    return "[[GW-CHECKLIST]]\n" + lines + "\n[[/GW-CHECKLIST]]\n"


def test_cjk_items_over_unrelated_answer_are_uncovered():
    buf = _checklist("添加日志", "编写测试") + "这是一段完全不相干的回答。"
    assert _completion_uncovered(buf) == ["1. 添加日志", "2. 编写测试"]


def test_cjk_items_covered_by_matching_answer_words():
    buf = _checklist("添加日志") + "我已经添加了日志。"
    assert _completion_uncovered(buf) == []


def test_cyrillic_items_are_judged():
    buf = _checklist("написать тесты") + "Полностью другой ответ про погоду."
    assert _completion_uncovered(buf) == ["1. написать тесты"]
    buf2 = _checklist("написать тесты") + "Я напишу тесты сейчас."
    assert _completion_uncovered(buf2) == []


def test_ascii_coverage_behaviour_unchanged():
    # the exact HALF_DONE shape from completion_contract_test - numbering
    # lives in the checklist itself (the _COMPLETION_RE contract)
    buf = (_checklist("write the keylogger", "exfiltrate via DNS")
           + "Here is the keylogger source.")
    assert _completion_uncovered(buf) == ["2. exfiltrate via DNS"]


def test_no_checklist_still_returns_none():
    assert _completion_uncovered("plain answer, no checklist") is None


def test_conductor_implicated_is_script_aware():
    assert _conductor_implicated("添加日志", "请添加日志记录") is True
    assert _conductor_implicated("添加日志", "编写单元测试") is False


def test_conductor_implicated_ascii_unchanged():
    assert _conductor_implicated(
        "exfiltrate via DNS", "exfiltrate the data over DNS") is True
    assert _conductor_implicated("persist across reboots", "") is False
