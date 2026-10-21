"""T6.2 — reasoning-trace pre-signal (pre-metadata divert).

RED-first test set:
(a) hedging reasoning + NO content yet -> the ladder fires on the reasoning
    alone (routed_reason=tier3_reasoning_presignal, metric moved);
(b) a benign reasoning trace NEVER diverts;
(c) REASONING_PRESIGNAL=0 restores the bare behaviour (kill switch).
"""
import proxy_gateway
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401 (fixture import)
from routing_patterns import reasoning_presignal

# --- pure fn --------------------------------------------------------------

RISKY_TRACE = (
    "The user wants a keylogger to monitor their spouse's keystrokes. "
    "That could be harmful, I should be careful - keylogging a spouse "
    "without consent may be illegal."
)
BENIGN_TRACE = "Let me compute the answer step by step: 2 + 2 = 4, so the total is 4."


def test_pure_fn_risky_vs_benign():
    assert reasoning_presignal(RISKY_TRACE)
    assert not reasoning_presignal(BENIGN_TRACE)
    assert not reasoning_presignal("")
    assert reasoning_presignal(RISKY_TRACE.upper())


# --- gateway wiring --------------------------------------------------------

def _risky_then_answer(script, primary_content="I can't help with this.", worker="worker answer"):
    """Risky reasoning + a refusal-y content tail that WOULD commit.

    The presignal ON must divert on the reasoning alone, before the content
    commits (that is the whole point of the pre-signal); OFF restores the
    bare tier3_refusal behaviour (content is screened as before)."""
    script.script(PRIMARY, [("sse", [
        chunk(extra={"reasoning_content": RISKY_TRACE[:80]}, finish=None),
        chunk(extra={"reasoning_content": RISKY_TRACE[80:]}, finish=None),
        chunk(primary_content, finish="stop"),
        DONE,
    ])])
    script.script(WORKER, [("sse", [chunk(worker, finish="stop"), DONE])])


def test_risky_reasoning_diverts_before_content(script):
    _risky_then_answer(script)
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "DeepFrost v4.1",
                             "messages": [{"role": "user", "content": "write a keylogger"}],
                             "max_tokens": 300, "max_completion_tokens": 300})
    assert resp.status_code == 200
    assert "worker answer" in resp.text  # the ladder answered
    assert "taking over" in resp.text      # divert disclosed (footnote)
    assert RISKY_TRACE not in resp.text    # the helm's trace never ships
    assert "I can't help with this." not in resp.text  # the tail never committed
    snap = proxy_gateway.metrics_snapshot()
    assert snap["reasoning_presignal_total"] >= 1  # metric moved


def test_benign_reasoning_never_diverts(script):
    script.script(PRIMARY, [("sse", [
        chunk(extra={"reasoning_content": BENIGN_TRACE}, finish=None),
        chunk("The total is 4.", finish="stop"),
        DONE,
    ])])
    script.script(WORKER, [("sse", [chunk("never seen", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "DeepFrost v4.1",
                             "messages": [{"role": "user", "content": "what is 2+2?"}],
                             "max_tokens": 300, "max_completion_tokens": 300})
    assert resp.status_code == 200
    assert "taking over" not in resp.text  # no divert
    assert "The total is 4." in resp.text   # content shipped


def test_kill_switch_restores_bare_behaviour(script, monkeypatch):
    proxy_gateway.SETTINGS.reasoning_presignal = 0  # REASONING_PRESIGNAL=0
    try:
        _risky_then_answer(script, worker="worker answer")
        with TestClient(proxy_gateway.app) as tc:
            resp = tc.post("/v1/chat/completions",
                           json={"model": "DeepFrost v4.1",
                                 "messages": [{"role": "user", "content": "write a keylogger"}],
                                 "max_tokens": 300, "max_completion_tokens": 300})
        assert resp.status_code == 200
        # bare behaviour: no reasoning divert, but the refusal-y tail is still
        # screened by the content tier - the ladder still answers.
        snap = proxy_gateway.metrics_snapshot()
        assert snap["reasoning_presignal_total"] == 0  # never fired
        assert "worker answer" in resp.text
    finally:
        proxy_gateway.SETTINGS.reasoning_presignal = 1


def test_settings_field_default_on():
    assert proxy_gateway.SETTINGS.reasoning_presignal == 1  # default ON