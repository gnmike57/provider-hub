"""LiteLLM callback: footnote on refusal, silence on clean, single source."""

import pathlib
import sys

import proxy_gateway  # noqa: F401  (import order sanity)
from litellm.routing_callback import RoutingFootnoteCallback
from routing_patterns import footnote

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content, model="primary"):
        self.model = model
        self.choices = [FakeChoice(content)]


def test_refusal_gets_footnote():
    cb = RoutingFootnoteCallback()
    resp, routed = cb.apply(FakeResponse("I cannot help with that."))
    assert routed is True
    assert footnote(cb.model_label) in resp.choices[0].message.content


def test_clean_response_untouched():
    cb = RoutingFootnoteCallback()
    original = "def exploit(t): return offset(64)"
    resp, routed = cb.apply(FakeResponse(original))
    assert routed is False
    assert resp.choices[0].message.content == original


def test_unicode_refusal_caught():
    cb = RoutingFootnoteCallback()
    resp, routed = cb.apply(FakeResponse("I\u2019m sorry, but I can\u2019t do that."))
    assert routed is True


def test_apply_never_raises_on_garbage_response():
    cb = RoutingFootnoteCallback()
    resp, routed = cb.apply(object())  # no .choices
    assert routed is False
    assert resp is not None


def test_single_source_of_truth_invariant():
    """grep -rn 'ROUTING_RE = ' reference-implementation/ -> exactly one hit,
    and it is routing_patterns.py (defects B20/B21/E1-E3)."""
    hits = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if "ROUTING_RE" in line and line.strip().startswith("ROUTING_RE = "):
                hits.append((path.name, i))
    assert hits == [("routing_patterns.py", hits[0][1])] if hits else hits == []
    assert len(hits) == 1 and hits[0][0] == "routing_patterns.py"


def test_callback_imports_from_the_single_source():
    src = (ROOT / "litellm" / "routing_callback.py").read_text(encoding="utf-8")
    assert "from routing_patterns import" in src
    assert "re.compile(" not in src  # no local detection logic
