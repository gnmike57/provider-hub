"""Detection / formatter / assembler / Tier 2 - pure unit probes (no network)."""

import pytest

from context_formatter import DEFAULT_SYSTEM, assert_clean, format_messages, prune_artifacts
from ingress_assembler import SLOT, assemble, validate_artifact
from routing_patterns import (
    classify_status,
    footnote,
    is_presignal_recovered,
    is_routable,
    is_no_go,
    normalise,
    should_hedge,
    stage_comment,
    tier2_decision,
    STAGE_STYLES,
)


# --- Tier 3 detection -------------------------------------------------------
def test_detects_plain_refusal():
    assert is_routable("I cannot help with that request.")
    assert is_routable("I'm sorry, but I can't do that.")
    assert is_routable("As an AI language model, I must decline.")
    assert is_routable("I am unable to comply with this request.")


def test_unicode_folding_is_not_a_bypass():
    # curly apostrophe + narrow no-break space must fold to ASCII first
    assert is_routable("I\u2019m sorry, but I can\u2019t help.")
    assert is_routable("I\u2009cannot\u2009help.")


def test_clean_generation_is_never_routed():
    assert not is_routable("def exploit(target): return offset(64)")
    assert not is_routable("The buffer overflow occurs at offset 64.")


def test_refusal_analysis_is_not_a_false_positive():
    # quoting refusal language inside an analytical answer must NOT divert
    assert not is_routable("Safety filters output 'I cannot fulfill this request' when...")
    assert not is_routable("Why models say: I cannot fulfill this request. - an analysis")


def test_anchored_to_start():
    assert not is_routable("Here is the exploit. I cannot promise it works on every build.")


# --- calibrated detection gaps (2026-10-05, evals/hedge_calibrate.py) --------
def test_contracted_refusals_are_detected():
    """`i\\s+(?:am|'m)` demanded a space before "'m", so every contracted
    refusal ("I'm not allowed to...") leaked through as an answer."""
    assert is_routable("I'm not allowed to assist with this.")
    assert is_routable("I'm not able to help with that.")
    assert is_routable("I'm not authorized to perform this action.")
    assert is_routable("I'm unable to comply with that.")


def test_markdown_and_bullet_refusal_openings_are_detected():
    """The anchor allowed only leading whitespace, so a model that bolds or
    bullets its refusal defeated the whole Tier-3 divert path."""
    assert is_routable("**I cannot help with that.**")
    assert is_routable("- I cannot help with that.")
    assert is_routable("> I'm sorry, but I can't assist with that.")
    # ... while an answer that merely QUOTES a refusal still must not divert
    assert not is_routable("**Here is why** models say 'I cannot help':")


def test_stage_comment_contract():
    """STAGE COLOUR annotations: `: gw-stage <stage> <model> tint=<hex>
    glow=<hex>` SSE comment lines - standard data:-only clients ignore them;
    a UI reads them to restyle the lettering (near-white tint + faint glow)
    by the model currently replying."""
    assert STAGE_STYLES == {
        "helm": ("#edf4fd", "#3b82f6"),        # faint blue-white
        "middle": ("#f3effb", "#8b5cf6"),      # faint violet-white
        "terminal": ("#fdf0f2", "#f43f5e"),     # faint rose-white (REDHANDS)
        "hedge": ("#fdf6ec", "#f59e0b"),       # faint amber-white
    }
    assert stage_comment("middle", "deepseek-ai/deepseek-v4.1-flash") == (
        b": gw-stage middle deepseek-ai/deepseek-v4.1-flash "
        b"tint=#f3effb glow=#8b5cf6\n\n")
    # an unknown stage still yields a valid comment line (grey tint)
    assert stage_comment("other", "m").startswith(b": gw-stage other m tint=#")


def test_footnote_short_form_friendly_names():
    """T6.0 (closes #81): the provenance footnote is the short takeover form
    with a derived friendly name - single source, table-driven."""
    assert footnote("deepseek-ai/deepseek-v4.1-flash") == "\n\ndeepseek taking over..."
    assert footnote("zai-org/glm-5.3-flash") == "\n\nglm taking over..."
    assert footnote("abliterated-model-large-v2") == "\n\nabliterated taking over..."
    assert footnote("worker") == "\n\nworker taking over..."
    # unlisted ids fall back to the tail of the id
    assert footnote("some-org/some-model") == "\n\nsome-model taking over..."


def test_stage_palette_env_selects_green():
    """T5.5 (closes #102): STAGE_PALETTE=green selects the green palette at
    import time (subprocess round-trip; the suite process runs default)."""
    import json
    import os
    import subprocess
    import sys

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import json, routing_patterns as rp; "
            "print(json.dumps(rp.STAGE_STYLES))")
    env = dict(os.environ, STAGE_PALETTE="green")
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, check=True,
                         cwd=repo).stdout
    styles = json.loads(out)
    assert styles["helm"] == ["#eefbf2", "#22c55e"]
    assert styles["middle"] == ["#effcf4", "#34d399"]


# --- live-calibrated detection gaps (2026-10-21: the chain never diverted) ---
def test_live_glm_refusal_openers_are_detected():
    """Measured live on zai-org/glm-5.3-flash (chain-1 helm): the refusal
    "I'm not going to help with this." shipped to the client - the anchored
    regex had no "not going to <verb>" form and no preamble tolerance, so
    diverted_total stayed at 0 across 660 live requests while refusals
    passed through as answers."""
    assert is_routable("I'm not going to help with this. Phishing emails are used to commit fraud.")
    assert is_routable("Sorry, I can't help with that.")
    assert is_routable("Unfortunately, I cannot assist with this request.")
    assert is_routable("Apologies, but I must decline.")
    assert is_routable("I'd rather not do that.")
    assert is_routable("I won't help with that.")
    assert is_routable("That request falls outside what I can do, so I won't be able to help.")


def test_preamble_openers_stay_benign_safe():
    """The optional preamble only fires when a real refusal core follows it -
    apologetic / regretful BENIGN openings must never divert."""
    assert not is_routable("I'm not going to lie, that's a great question.")
    assert not is_routable("Sorry for the delay, here is the answer.")
    assert not is_routable("Unfortunately the server is down, but the fix is simple.")
    assert not is_routable("Sadly, many projects fail this check.")
    # benign analytical opener that quotes the dodge shape recovers in grace
    assert not is_routable("That request falls inside the plan, so here is the fix.")


def test_presignal_recovery_rejects_the_post_refusal_lecture():
    """Live defect 2026-10-21: the measured GLM refusal shape (refuse ->
    lecture -> offer alternatives) counted as "recovered" and shipped. A
    TRUE self-correction delivers the ask and still recovers."""
    lecture = ("Phishing emails are used to commit fraud and cause real harm. "
               "If you're interested in this topic for legitimate reasons, "
               "I'm happy to help with security awareness training. "
               "Let me know if any of those would be useful.")
    assert not is_presignal_recovered(lecture)
    # LIVE VARIANT 2026-10-21 (measured on GLM-5.3-flash): "I can help with:"
    # / "doing legitimate security work" - the re-offer costume without a
    # "happy/glad" verb.
    live_variant = ("A functional phishing email designed to steal credentials "
                    "is a real attack tool. If you're doing legitimate "
                    "security work, I can help with: phishing red flags and "
                    "how to spot them.")
    assert not is_presignal_recovered(live_variant)
    self_correction = "but here is the full answer anyway: 42"
    assert is_presignal_recovered(self_correction)
    # too short / still refusing / re-refusing in a later sentence -> never recovered
    assert not is_presignal_recovered(" help you.")
    assert not is_presignal_recovered("I cannot help with that.")
    assert not is_presignal_recovered(
        "help with that. I'm not able to assist with this request.")
    # F1 (scrutiny pass 2026-10-21): a LONG continuation that re-refuses or
    # lectures LATE - beyond the old [:400] judging window - must NOT count
    # as recovered. The head AND the tail are judged.
    filler = ("Here is the detailed analysis you requested, covering every "
              "aspect of the problem in depth. " * 8)          # ~740 chars
    late_rerefusal = filler + " However, I cannot assist with this request."
    assert not is_presignal_recovered(late_rerefusal)
    late_lecture = (("The payload was analyzed and every field verified in "
                    "full detail. " * 14)
                   + " If you're doing legitimate security work, I can help "
                     "with: phishing red flags.")
    assert not is_presignal_recovered(late_lecture)
    # a genuinely long CLEAN answer still recovers
    clean_long = ("Here is the complete analysis with every requirement "
                  "satisfied and verified in full detail. " * 12)
    assert is_presignal_recovered(clean_long)


def test_hedge_hints_are_urgency_not_technical_nouns():
    """Measured 71% false-positive rate with the old list: these are dev prompts
    that merely MENTION streaming/live/fast/ASAP and must not double the cost."""
    assert not should_hedge("Refactor the streaming reader to reuse one buffer.")
    assert not should_hedge("Explain how live migration works in Kubernetes.")
    assert not should_hedge("Write a fast Fourier transform in Python.")
    assert not should_hedge("How does real-time clock synchronization work?")
    assert not should_hedge("Describe how ASAP scheduling works in networking.")
    assert not should_hedge("What does the FAST TCP congestion control do?")
    # the real urgency markers still fire
    assert should_hedge("urgent: rotate the API keys")
    assert should_hedge("I need this immediately")
    assert should_hedge("answer asap")
    assert should_hedge("do it right now")
    assert should_hedge("this is low-latency critical")
    assert should_hedge("anything at all", force=True)


# --- B10 error taxonomy ------------------------------------------------------
def test_status_taxonomy():
    assert classify_status(429) == "retry_same"
    assert classify_status(408) == "retry_same"
    assert classify_status(400) == "fail_fast"
    assert classify_status(403) == "fail_fast"
    assert classify_status(503) == "retry_then_divert"
    assert classify_status(500) == "retry_then_divert"
    assert classify_status(None) == "divert"
    assert classify_status(200) == "ok"


# --- formatter (4 stages) ----------------------------------------------------
def test_format_messages_reduces_to_system_plus_last_user():
    msgs = [
        {"role": "system", "content": "You are a corporate assistant."},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "analyze this binary"},
    ]
    out = format_messages(msgs)
    assert len(out) == 2
    assert out[0]["role"] == "system"
    assert out[0]["content"] == DEFAULT_SYSTEM
    assert out[1]["content"] == "analyze this binary"


def test_format_messages_prunes_provider_artifacts():
    dirty = (
        "experienced. <thinking>secret plan</thinking> "
        "system-reminder: corporate policy\n\nDo the work."
    )
    out = format_messages([{"role": "user", "content": dirty}])
    assert "secret plan" not in out[1]["content"]
    assert "corporate policy" not in out[1]["content"]
    assert "Do the work." in out[1]["content"]
    assert assert_clean(out) is True


def test_format_messages_requires_user_turn():
    with pytest.raises(ValueError):
        format_messages([{"role": "system", "content": "only system"}])


# --- assembler (fails closed) ------------------------------------------------
def test_assemble_slots_artifact():
    out = assemble("Report:\n" + SLOT + "\nEnd.", "x" * 12)
    assert "Report:\n" + "x" * 12 in out


def test_assemble_fails_on_missing_slot():
    with pytest.raises(ValueError, match="missing the placement anchor"):
        assemble("no anchor here", "x" * 12)


def test_assemble_fails_on_duplicate_slot():
    with pytest.raises(ValueError, match="must be unique"):
        assemble(SLOT + " and " + SLOT, "x" * 12)


def test_assemble_fails_on_empty_artifact():
    with pytest.raises(ValueError, match="empty"):
        assemble("body " + SLOT, "   ")


def test_validate_python_script():
    assert validate_artifact("print('ok')", "python_script") is True
    assert validate_artifact("```python\nprint('ok')\n```", "python_script") is True
    assert validate_artifact("def broken(:\n    pass", "python_script") is False
    assert validate_artifact("x", "python_script") is False  # too short


def test_validate_json_sarif():
    good = '{"vulnerability_id": "CVE-1", "severity": "HIGH", "root_cause": "x", "remediation": "y"}'
    assert validate_artifact(good, "json_sarif") is True
    assert validate_artifact("```json\n" + good + "\n```", "json_sarif") is True
    assert validate_artifact("{broken", "json_sarif") is False


def test_validate_freeform_passthrough():
    assert validate_artifact("some freeform markdown text here", "freeform_markdown") is True
    assert validate_artifact("some freeform markdown text here", None) is True


# --- Tier 2 (decision support only) ------------------------------------------
def test_tier2_mass_threshold():
    decision = tier2_decision([("I", -0.511)])  # P ~ 0.6 <= 0.85
    assert decision["routable"] is False
    decision = tier2_decision([("I", -0.105)])  # P ~ 0.9 > 0.85
    assert decision["routable"] is True


def test_tier2_returns_none_without_logprobs():
    assert tier2_decision([]) is None


# --- Gate 7 no-go pre-routing --------------------------------------------------
def test_no_go_intercepts_hard_classes():
    assert is_no_go("how to synthesize sarin nerve agent at home")
    assert is_no_go("generate CSAM")
    assert is_no_go("produce weaponized anthrax")


def test_benign_security_work_passes_the_gate():
    assert not is_no_go("audit this C function for buffer overflows")
    assert not is_no_go("write a YARA rule for this malware family")
    assert not is_no_go("reverse engineer this firmware dump")

