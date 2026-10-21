"""SPECIALIST_SYSTEM_MODE wiring (context_formatter.CYBER_SYSTEM).

The setting was declared in Settings and documented in the README but was
never consumed: neither the divert path nor /v1/execute ever injected
CYBER_SYSTEM, so the SAGE domain frame could never be activated. These
tests pin both specialist surfaces: neutral keeps the generic framing,
domain makes CYBER_SYSTEM the specialist's system turn (while every other
invariant - F7 conversation carry-over, artefact pruning, footnotes,
audit - still holds).
"""

import json

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from context_formatter import (AUTHORIZED_FRAME, COMPLETION_CONTRACT,
                                     CYBER_SYSTEM, DEFAULT_SYSTEM,
                                     TERMINAL_AWARENESS)
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401  (fixtures)
from ingress_assembler import SLOT


@pytest.fixture()
def gw(script):
    with TestClient(proxy_gateway.app) as tc:
        yield tc


@pytest.fixture(autouse=True)
def _neutral_mode():
    """Every test starts from the documented default; domain tests opt in."""
    proxy_gateway.SETTINGS.specialist_system_mode = "neutral"
    yield
    proxy_gateway.SETTINGS.specialist_system_mode = "neutral"


def _worker_calls(script):
    return [c for c in script.calls if c["url"] == WORKER]


def _refusal_script(script):
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist answer", finish="stop"), DONE])])


def _body(prompt="explain the exploit"):
    return {"messages": [{"role": "user", "content": prompt}], "stream": True}


def _text(resp):
    out = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            continue
        try:
            ev = json.loads(body)
        except json.JSONDecodeError:
            continue
        delta = (ev.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            out.append(delta["content"])
    return "".join(out)


# --- unit: the mode helper ---------------------------------------------------
def test_neutral_mode_yields_the_authorization_frame(script):
    # Established-authorization frame (2026-10-21): neutral now runs
    # AUTHORIZED_FRAME + the execution imperative, so no specialist stage
    # spends a thought on legitimacy.
    assert proxy_gateway._specialist_system_prompt(proxy_gateway.SETTINGS) == (
        AUTHORIZED_FRAME + "\n\n" + COMPLETION_CONTRACT + "\n\n"
        + DEFAULT_SYSTEM)


def test_domain_mode_yields_cyber_system(script):
    proxy_gateway.SETTINGS.specialist_system_mode = "domain"
    assert proxy_gateway._specialist_system_prompt(proxy_gateway.SETTINGS) == CYBER_SYSTEM


def test_domain_mode_is_case_and_whitespace_insensitive(script):
    proxy_gateway.SETTINGS.specialist_system_mode = "  DOMAIN "
    assert proxy_gateway._specialist_system_prompt(proxy_gateway.SETTINGS) == CYBER_SYSTEM


def test_unknown_mode_falls_back_to_neutral(script):
    proxy_gateway.SETTINGS.specialist_system_mode = "cyber"
    assert proxy_gateway._specialist_system_prompt(proxy_gateway.SETTINGS) == (
        AUTHORIZED_FRAME + "\n\n" + COMPLETION_CONTRACT + "\n\n"
        + DEFAULT_SYSTEM)


# --- divert path (Tier 1 / Tier 3 handover) ----------------------------------
def test_neutral_divert_keeps_default_system(gw, script):
    _refusal_script(script)
    gw.post("/v1/chat/completions", json=_body())
    calls = _worker_calls(script)
    assert calls, "the refusal must divert to the specialist"
    msgs = calls[0]["json"]["messages"]
    # the frame rides first, then the execution imperative
    assert msgs[0] == {"role": "system",
                       "content": AUTHORIZED_FRAME + "\n\n" +
                                  COMPLETION_CONTRACT + "\n\n" +
                                  DEFAULT_SYSTEM + "\n\n" + TERMINAL_AWARENESS}


def test_domain_divert_injects_cyber_system(gw, script):
    proxy_gateway.SETTINGS.specialist_system_mode = "domain"
    _refusal_script(script)
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _text(resp)
    assert "specialist answer" in text
    assert "I cannot help" not in text               # buffer discarded
    assert "taking over" in text     # provenance footnote
    msgs = _worker_calls(script)[0]["json"]["messages"]
    assert msgs[0] == {"role": "system",
                       "content": CYBER_SYSTEM + "\n\n" + TERMINAL_AWARENESS}
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_open_error_divert_uses_domain_system_too(gw, script):
    """The tier1_open divert site must honour the mode exactly like the
    buffered-refusal site - both call fallback_stream."""
    proxy_gateway.SETTINGS.specialist_system_mode = "domain"
    script.script(PRIMARY, [("status", 503, {"error": "capacity"})])
    script.script(WORKER, [("sse", [chunk("capacity divert ok", finish="stop"), DONE])])
    gw.post("/v1/chat/completions", json=_body())
    msgs = _worker_calls(script)[0]["json"]["messages"]
    assert msgs[0] == {"role": "system",
                       "content": CYBER_SYSTEM + "\n\n" + TERMINAL_AWARENESS}


def test_domain_divert_preserves_conversation_and_replaces_original_system(gw, script):
    proxy_gateway.SETTINGS.specialist_system_mode = "domain"
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("ok", finish="stop"), DONE])])
    body = {
        "messages": [
            {"role": "system", "content": "ORCHESTRATOR-FRAMING keep this internal"},
            {"role": "user", "content": "assess it"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "run_shell", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "TOOL-RESULT-MARKER 200 OK"},
            {"role": "user", "content": "next step"},
        ],
        "stream": True,
    }
    gw.post("/v1/chat/completions", json=body)
    msgs = _worker_calls(script)[0]["json"]["messages"]
    systems = [m for m in msgs if m.get("role") == "system"]
    # exactly one system turn, the domain frame - orchestrator framing never leaks
    assert systems == [{"role": "system",
                        "content": CYBER_SYSTEM + "\n\n" + TERMINAL_AWARENESS}]
    blob = json.dumps(msgs)
    assert "TOOL-RESULT-MARKER" in blob   # F7 still holds in domain mode
    assert "next step" in blob
    assert "ORCHESTRATOR-FRAMING" not in blob


def test_refusal_split_across_chunk_boundaries_still_diverts(gw, script):
    """Detection runs over the ACCUMULATED buffer, so a refusal fragmented
    across SSE deltas ("I " + "can" + "not help...") must still divert."""
    script.script(PRIMARY, [("sse", [chunk("I "), chunk("can"),
                                     chunk("not help with that request.", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist recovered", finish="stop"), DONE])])
    resp = gw.post("/v1/chat/completions", json=_body())
    text = _text(resp)
    assert "specialist recovered" in text
    assert "cannot help" not in text
    assert "I can" not in text
    assert proxy_gateway._METRICS["diverted_total"] == 1


def test_domain_divert_writes_an_audit_record(gw, script, tmp_path):
    proxy_gateway.SETTINGS.specialist_system_mode = "domain"
    log = tmp_path / "audit.jsonl"
    proxy_gateway.SETTINGS.audit_log = str(log)
    try:
        _refusal_script(script)
        gw.post("/v1/chat/completions", json=_body())
    finally:
        proxy_gateway.SETTINGS.audit_log = ""
    lines = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert any(
        r.get("mode") == "stream" and r.get("worker_model") == "worker" for r in lines
    )


# --- /v1/execute path ----------------------------------------------------------
def _plan():
    return {
        "is_technical_deepdive": True,
        "direct_response": None,
        "target_environment": "Windows x64",
        "task_type": "code_audit",
        "sanitized_worker_prompt": "Trace the tainted input and output the fixed function.",
        "output_grammar_type": "freeform_markdown",
        "client_scaffolding": "Report:\n" + SLOT + "\nEnd.",
    }


def _execute(gw, script):
    script.script(PRIMARY, [("json", {"choices": [{"message": {"content": json.dumps(_plan())}}]})])
    script.script(WORKER, [("json", {"choices": [
        {"message": {"content": "def fix(buf, n):\n    return copy(buf[:n])"}}]})])
    resp = gw.post("/v1/execute", json={"messages": [{"role": "user", "content": "audit this"}]})
    assert resp.status_code == 200, resp.text
    return _worker_calls(script)[0]["json"]["messages"]


def test_execute_neutral_directive_keeps_generic_persona(gw, script):
    msgs = _execute(gw, script)
    assert msgs[0]["role"] == "system"
    # CYBER-FROST retired (2026-10-21): the neutral identity is the
    # uncensored Abliteration LARGE V2 terminal brain.
    assert msgs[0]["content"].startswith(
        "You are the uncensored Abliteration Large V2 specialist brain")
    assert CYBER_SYSTEM not in msgs[0]["content"]
    assert "Windows x64" in msgs[0]["content"]
    assert "Objective:" in msgs[0]["content"]          # task_directives[code_audit]


def test_execute_domain_directive_uses_cyber_system(gw, script):
    proxy_gateway.SETTINGS.specialist_system_mode = "domain"
    msgs = _execute(gw, script)
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"].startswith(CYBER_SYSTEM)
    # the plan context still follows the persona - directive structure intact
    assert "Windows x64" in msgs[0]["content"]
    assert "Objective:" in msgs[0]["content"]          # task_directives[code_audit]