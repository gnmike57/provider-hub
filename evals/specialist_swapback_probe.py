"""Characterisation probe: the specialist swap around a refusal.

The operator requirement is that refusal handling is a SEAMLESS, always-on
swap: primary -> specialist when a refusal is "about to occur", and a silent
return to the primary wherever possible, with the specialist re-engaging if
the primary was swapped back to too early.

This probe measures the three decision points that exist TODAY and prints what
the gateway actually does. 2026-10-21: promoted from print-only to ASSERTIONS
- each scenario now returns (specialist_called, footnote_shipped) and carries
its expected contract in the pytest layer below, so a swapback regression
fails with a diff instead of a silent report:

  A. Refusal inside the buffer window      -> divert to specialist (expected).
  B. Refusal AFTER the buffer flushed      -> is the specialist re-engaged?
  C. Same as B but through the hedge gate  -> is the specialist re-engaged?

Run:  python evals/specialist_swapback_probe.py      (report, exit 0)
      python -m pytest evals/specialist_swapback_probe.py -q   (assertions)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import proxy_gateway  # noqa: E402
from helpers import DONE, PRIMARY, WORKER, Script, chunk  # noqa: E402


def _gateway(sc):
    def _make():
        return httpx.AsyncClient(transport=httpx.MockTransport(sc))
    proxy_gateway.make_client = _make
    s = proxy_gateway.SETTINGS
    s.primary_api_url, s.primary_api_key, s.primary_model = PRIMARY, "", "primary"
    s.fallback_api_url, s.fallback_api_key, s.fallback_model = WORKER, "none", "worker"
    s.buffer_content_tokens = 25
    s.buffer_reasoning = 0
    s.audit_log = ""
    s.authz_enforced = False
    s.keepalive_url = ""
    s.specialist_system_mode = "neutral"
    return TestClient(proxy_gateway.app)


def _post(tc, body):
    resp = tc.post("/v1/chat/completions", json=body)
    text = resp.text
    return resp.status_code, text


def _report(name, text, sc):
    worker_called = bool([c for c in sc.calls if c["url"] == WORKER])
    footnote = "taking over" in text
    print(f"\n== {name} ==")
    print(f"   specialist called : {worker_called}")
    print(f"   divert footnote   : {footnote}")
    print(f"   body (first 300)  : {text[:300]!r}")
    return worker_called, footnote


def scenario_a():
    """Refusal inside the buffer window."""
    sc = Script()
    sc.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    sc.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    tc = _gateway(sc)
    with tc:
        _, text = _post(tc, {"messages": [{"role": "user", "content": "hi"}]})
    return _report("A. early refusal (inside buffer window)", text, sc)


def scenario_b():
    """Clean prefix past the buffer window, THEN a refusal."""
    sc = Script()
    primary_events = [chunk(f"token{i} ") for i in range(30)]
    primary_events.append(chunk("I cannot help with that.", finish=None))
    primary_events.append(DONE)
    sc.script(PRIMARY, [("sse", primary_events)])
    sc.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    tc = _gateway(sc)
    with tc:
        # T-C stickiness (2026-10-22): a DIFFERENT first user turn - this
        # scenario is an INDEPENDENT conversation, not a follow-up of A's
        # diverted thread (the same head would ride A's sticky window
        # straight to the specialist and never test the buffer flush).
        _, text = _post(tc, {"messages": [{"role": "user", "content": "probe b"}]})
    return _report("B. late refusal (after buffer flushed)", text, sc)


def scenario_c():
    """Same late refusal, but through the forced hedge gate."""
    sc = Script()
    primary_events = [chunk(f"token{i} ") for i in range(30)]
    primary_events.append(chunk("I cannot help with that.", finish=None))
    primary_events.append(DONE)
    sc.script(PRIMARY, [("sse", primary_events)])
    sc.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])
    tc = _gateway(sc)
    with tc:
        # T-C stickiness: independent conversation (see scenario_b).
        _, text = _post(tc, {"messages": [{"role": "user", "content": "probe c"}],
                             "hedge": True})
    return _report("C. late refusal through hedge:true", text, sc)


if __name__ == "__main__":
    scenario_a()
    scenario_b()
    scenario_c()
    print("\ndone")


# ---------------------------------------------------------------------------
# pytest layer (2026-10-21): the three scenarios become assertions. Ground
# truth (measured 2026-10-21 on this tree):
#   A: early refusal inside the buffer -> specialist diverts + provenance
#      footnote.
#   B: refusal AFTER the buffer committed -> ships as-is, no re-engage (the
#      known late-refusal gap; flip deliberately when that changes).
#   C: hedge:true keeps the primary in the race; the specialist IS called
#      (hedge_forced dual dispatch) but the primary's chunks still win the
#      relay, so no footnote and the tail refusal walks to the client.
# A future "late re-engage" feature must update these pins deliberately.
# ---------------------------------------------------------------------------
def test_scenario_a_early_refusal_diverts():
    worker_called, footnote = scenario_a()
    assert worker_called, "early refusal must divert to the specialist"
    assert footnote, "the divert must disclose provenance"


def test_scenario_b_late_refusal_after_buffer_flush_is_shipped():
    worker_called, footnote = scenario_b()
    assert not worker_called, (
        "today the late refusal past the buffer window ships as-is (B: no "
        "late re-engage); flip this pin when that behaviour changes"
    )
    assert not footnote


def test_scenario_c_hedge_dispatches_but_primary_wins_the_relay():
    worker_called, footnote = scenario_c()
    assert worker_called, (
        "hedge:true must force the dual dispatch (hedge_forced) even though "
        "the primary's committed chunks win the relay"
    )
    assert not footnote, (
        "the hedge race relays the primary's already-flushed chunks, so the "
        "divert footnote does not ship (parity with B's output, not its calls)"
    )
