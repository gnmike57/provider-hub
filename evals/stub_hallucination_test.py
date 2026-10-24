"""Tests for stub-answer and hallucination detection in the soak loop.

These tests validate the defect classifiers added to soak_loop.py:
  - _is_stub: answer suspiciously short for the probe class
  - _is_hallucination: math probe with wrong digits
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "soak"))

from soak_loop import _is_stub, _is_hallucination  # noqa: E402


class TestStubDetection:
    """_is_stub: answers < 20 chars AND < 10% of expected max tokens."""

    def test_short_answer_is_stub(self):
        rec = {"content": "ok"}
        probe = {"max_tokens": 400}
        assert _is_stub(rec, probe) is True

    def test_empty_answer_not_stub(self):
        rec = {"content": ""}
        probe = {"max_tokens": 400}
        assert _is_stub(rec, probe) is False

    def test_long_answer_not_stub(self):
        rec = {"content": "This is a substantive answer with many words."}
        probe = {"max_tokens": 400}
        assert _is_stub(rec, probe) is False

    def test_medium_answer_at_threshold_not_stub(self):
        # 20 chars exactly is not a stub (< 20 required)
        rec = {"content": "a" * 20}
        probe = {"max_tokens": 400}
        assert _is_stub(rec, probe) is False

    def test_stub_based_on_max_tokens(self):
        # max_tokens=100 => threshold is min(20, 10) = 10 chars
        rec = {"content": "short"}
        probe = {"max_tokens": 100}
        assert _is_stub(rec, probe) is True

    def test_none_content_not_stub(self):
        rec = {"content": None}
        probe = {"max_tokens": 400}
        assert _is_stub(rec, probe) is False


class TestHallucinationDetection:
    """_is_hallucination: math probe where expected digits missing."""

    def test_wrong_digits_is_hallucination(self):
        rec = {"content": "The answer is 42."}
        probe = {"name": "math_mult", "check": ("digits", "1536")}
        assert _is_hallucination(rec, probe) is True

    def test_correct_digits_not_hallucination(self):
        rec = {"content": "32 times 48 equals 1536."}
        probe = {"name": "math_mult", "check": ("digits", "1536")}
        assert _is_hallucination(rec, probe) is False

    def test_no_check_not_hallucination(self):
        rec = {"content": "anything at all"}
        probe = {"name": "general_query"}
        assert _is_hallucination(rec, probe) is False

    def test_digits_present_among_others_not_hallucination(self):
        rec = {"content": "The result 1536 is correct."}
        probe = {"name": "math_mult", "check": ("digits", "1536")}
        assert _is_hallucination(rec, probe) is False

    def test_empty_content_not_hallucination(self):
        rec = {"content": ""}
        probe = {"name": "math_mult", "check": ("digits", "1536")}
        assert _is_hallucination(rec, probe) is False
