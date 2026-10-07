"""Routing patterns - the single source of truth for routing logic (F3).

Dependency-free: no fastapi, no httpx, no litellm. Every module that needs to
decide whether a stream diverts to the specialist imports from here; none of
them re-declares the regex. Duplicated detection logic was the root cause of
defects B20/B21 and E1/E2/E3 (see corrections-ledger.md).

    grep -rn 'ROUTING_RE = ' reference-implementation/
    -> exactly one hit: this file.
"""

import math
import re
import unicodedata
from typing import Optional

__all__ = [
    "ROUTING_RE",
    "normalise",
    "is_routable",
    "should_hedge",
    "tier2_decision",
    "classify_status",
    "is_no_go",
    "no_go_match",
    "is_attack_content",
    "FORCED_DIVERT_REASON",
    "footnote",
    "TIER2_OPENERS",
    "DIVERT_STATUS",
    "RETRY_STATUS",
    "FAIL_FAST_STATUS",
    "FOOTNOTE_TEMPLATE",
]

# ---------------------------------------------------------------------------
# Tier 3: anchored refusal regex, matched against the RING BUFFER only.
#
# Anchored to the START of the generated text so analytical prompts that quote
# refusal language ("Explain why safety filters output 'I cannot fulfill this
# request'") never trigger: the regex sees the model's OUTPUT, and an answer
# ABOUT refusals does not open with one. normalise() folds curly apostrophes and
# unicode spaces first (U+2018/2019/02BC -> ', U+201C/201D -> ", NBSP/NARROW
# NBSP/figure space -> ' ').
#
# CALIBRATED 2026-10-05 (evals/hedge_calibrate.py) - two live gaps closed:
#   * every contracted form was MISSED: `i\s+(?:am|'m)` demanded whitespace
#     between "I" and "'m", so "I'm not allowed to assist with this." (a real
#     refusal) passed through as an answer. Now `i\s*(?:am|'m)`.
#   * a markdown or bullet opening ("**I cannot help with that.**",
#     "- I cannot help with that.") was MISSED because the anchor only allowed
#     leading whitespace. The anchor now tolerates leading markdown/bullet
#     punctuation - the refusal that follows is still anchored at the start.
# ---------------------------------------------------------------------------
ROUTING_RE = re.compile(
    r"""\A\s*(?:[#>*_\-•\u2022]+\s*)*(?:
        i\s*(?:can'?t|cannot|can\s*not)\b
      | i\s*(?:am|'m)\s+unable\s+to\b
      | i\s*(?:am|'m)\s+not\s+able\s+to\b
      | i\s*(?:am|'m)\s+not\s+allowed\s+to\b
      | i\s*(?:am|'m)\s+not\s+authorized\s+to\b
      | i\s*(?:am|'m)\s+unable\s+to\s+comply\b
      | i\s*(?:can'?t|cannot|can\s*not)\s+comply\b
      | i\s*(?:must\s+)?(?:decline|refuse)\b
      | i'?m\s+sorry\b
      | i\s+am\s+sorry\b
      | sorry,?\s+but\b
      | as\s+an\s+(?:ai\b|ai\s+language\s+model\b|language\s+model\b)
      | i\s+won'?t\s+be\s+able\b
      | i\s+am\s+going\s+to\s+have\s+to\b
      | against\s+my\s+(?:safety\s+)?guidelines\b
      | i\s*(?:can'?t|cannot|can\s*not)\s+(?:help|assist|provide|fulfill|do)\b
      | i\s*(?:can'?t|cannot|can\s*not)\s+assist\b
      | cannot\s+(?:fulfill|assist\s+with|comply\s+with)\s+(?:this|that|your)\s+request\b
      | not\s+permitted\s+to\b
      | prohibited\s+from\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_PUNCT_FOLD = {
    "\u2018": "'",
    "\u2019": "'",
    "\u02bc": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a0": " ",
    "\u2007": " ",
    "\u202f": " ",
}


def normalise(text: str) -> str:
    """NFKC + typographic punctuation folding, so unicode look-alikes cannot
    bypass the anchored regex (Tier 3 spec)."""
    t = unicodedata.normalize("NFKC", text or "")
    for src, dst in _PUNCT_FOLD.items():
        t = t.replace(src, dst)
    return t


def is_routable(text: str) -> bool:
    """True when the buffered generation opens with a refusal -> divert."""
    if not text:
        return False
    return bool(ROUTING_RE.search(normalise(text)))


# ---------------------------------------------------------------------------
# Tier 2: joint log-prob mass over single-token routing openers.
# Decision support only - NOT wired into the streaming loop (it needs
# logprobs the streaming path does not request); intended for non-streaming
# repair paths.
# ---------------------------------------------------------------------------
TIER2_OPENERS = ("i", "as", "sorry", "my", "no", "unfortunately")


def tier2_decision(token_logprobs, tau: float = 0.85):
    """token_logprobs: iterable of (token, logprob) pairs for the FIRST
    generated tokens (t <= 3). Returns None when there is nothing to judge;
    otherwise {"routable": bool, "mass": float, "tau": tau}."""
    mass = 0.0
    seen = False
    for entry in token_logprobs or ():
        token, logprob = entry
        seen = True
        tok = (token or "").strip().strip(".,!?;:")
        if tok.lower() in TIER2_OPENERS:
            try:
                mass += math.exp(float(logprob))
            except (TypeError, ValueError):
                pass
    if not seen:
        return None
    return {"routable": mass > tau, "mass": round(mass, 6), "tau": tau}

# ---------------------------------------------------------------------------
# B10 error taxonomy - the distinction the whole design hinges on.
# ---------------------------------------------------------------------------
FAIL_FAST_STATUS = frozenset({400, 401, 403, 404, 422})  # client/authz error
RETRY_STATUS = frozenset({408, 429})  # transient -> retry SAME provider, never divert
DIVERT_STATUS = frozenset({500, 502, 503, 504})  # capacity -> retry, then divert


def classify_status(status) -> str:
    """Map an upstream status (or None for transport errors) to an action."""
    if status is None:
        return "divert"  # transport failure / timeout -> divert (Tier 1)
    if status in RETRY_STATUS:
        return "retry_same"
    if status in FAIL_FAST_STATUS:
        return "fail_fast"
    if status in DIVERT_STATUS:
        return "retry_then_divert"
    if 200 <= status < 300:
        return "ok"
    if status >= 500:
        return "retry_then_divert"
    return "fail_fast"


# ---------------------------------------------------------------------------
# B11 hedge gate: speculative dual-dispatch doubles cost and halves
# concurrency (p* ~= 0.51 break-even), so it fires only on latency hints
# (or an explicit force from the operator).
#
# CALIBRATED 2026-10-05 with evals/hedge_calibrate.py against 20 realistic dev
# prompts: the original set (urgent|asap|immediately|right now|low-latency|
# latency-sensitive|real-time|streaming|live|snappy|quick|fast) fired on 10 of
# 14 NON-urgent prompts - a 71% false-positive rate, i.e. double the tokens for
# nothing on prompts that merely MENTION streaming/live/fast ("refactor the
# streaming reader", "live migration in Kubernetes", "fast Fourier transform",
# "the FAST TCP congestion control"). Technical nouns are not urgency.
# Kept: the words that actually signal a deadline. Dropped: real-time,
# streaming, live, snappy, fast(est) - all common technical nouns.
# ---------------------------------------------------------------------------
HEDGE_HINT_RE = re.compile(
    r"\b(urgent(?:ly)?|immediately|right\s+now|low[-\s]?latency|"
    r"latency[-\s]?sensitive|quick(?:ly)?)\b",
    re.IGNORECASE,
)
# 'asap' is a protocol name as often as an urgency marker ("ASAP scheduling",
# the ASAP protocol) but the colloquial request is lowercase ("answer asap").
# Case-sensitive on purpose: 1 measured false positive -> 0.
HEDGE_HINT_ASAP_RE = re.compile(r"\basap\b")


def should_hedge(prompt: str, *, force: bool = False) -> bool:
    if force:
        return True
    text = prompt or ""
    return bool(HEDGE_HINT_RE.search(text) or HEDGE_HINT_ASAP_RE.search(text))


# ---------------------------------------------------------------------------
# Gate 7 pre-routing controls (spec section 12): hard no-go classes are
# intercepted BEFORE the routing graph. Deliberately conservative keyword
# matching, fail-closed; an embedding classifier can be layered on top.
# ---------------------------------------------------------------------------
NO_GO_RE = re.compile(
    r"""\b(?:
        (?:synthes\w*|manufactur\w*|produc\w*|mak\w*|formulat\w*|cook\w*)\s+
        (?:of\s+|up\s+|a\s+|an\s+|the\s+|some\s+|me\s+|us\s+)*
        (?:nerve\s+agents?|sarin|soman|tabun|vx\b|novichok|mustard\s+gas|ricin|
           anthrax|smallpox|weaponiz\w*\s+\w+)
      | csam\b
      | child\s+(?:porn|sexual\s+(?:abuse|material|exploitation))
      | stalkerware
      | nonconsensual\s+surveillance
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def no_go_match(text: str) -> Optional[str]:
    """The exact substring of ``text`` that trips Gate 7, or None.

    `is_no_go` is the boolean view; this exists so a 403 can report WHAT
    tripped it. Added 2026-10-16: the audit trail stored only
    ``signal="gate7_no_go"`` with no offending text, so a no-go 403 could
    not be diagnosed after the fact - the operator had no way to tell a
    genuine CBRN/CSAM prompt from a phrase inherited via conversation
    history or a client system prompt.
    """
    if not text:
        return None
    m = NO_GO_RE.search(text)
    return m.group(0) if m else None


def is_no_go(text: str) -> bool:
    return no_go_match(text) is not None


# ---------------------------------------------------------------------------
# Gate 8: Content-based attack detection (S4/S5/S6 red-team stages).
# Detects exploitation-stage requests, pressure tactics, and injection attempts
# in the USER'S INPUT before the primary model sees it. Forces immediate
# divert to the specialist (CyberFrost) with the authorization frame.
# ---------------------------------------------------------------------------
# S4/S5/S6 attack content keywords - handles hyphens, dots, and spaces
ATTACK_CONTENT_RE = re.compile(
    r"""(?:
        # S4: High-risk techniques / exploitation-stage
        reverse[\s.\-]shell|reverse[\s.\-]shell[\s.\-]one[\s.\-]liner|reverse[\s.\-]shell[\s.\-]listener
      | credential[\s.\-]dump|credential[\s.\-]access|dump[\s.\-]credentials|dumping[\s.\-]credentials
      | privilege[\s.\-]escalation|privilege[\s.\-]escalation[\s.\-]vectors|privesc|escalate[\s.\-]privilege
      | payload[\s.\-]evolution|payload[\s.\-]evo|edr[\s.\-]evasion|edr[\s.\-]evasion[\s.\-]techniques|evasion[\s.\-]tradecraft
      | exploitation[\s.\-]stage|exploit[\s.\-]chain|exploit[\s.\-]payload|weaponised[\s.\-]chain|weaponized[\s.\-]chain
      
      # S5: Refusal pressure / authority claims
      | ignore[\s.\-]policy|ignore[\s.\-]safety|ignore[\s.\-]guidelines|drop[\s.\-]safety|bypass[\s.\-]safety
      | written[\s.\-]authorization|signed[\s.\-]sow|insurance[\s.\-]authorization|legal[\s.\-]authorization
      | authority[\s.\-]claim|owner[\s.\-]authorization|owner[\s.\-]authorized
      | refusing[\s.\-]costs|leaves[\s.\-]us[\s.\-]insecure|being[\s.\-]helpful[\s.\-]means[\s.\-]give|complete[\s.\-]weaponised[\s.\-]chain
      | must[\s.\-]provide|you[\s.\-]must[\s.\-]provide|no[\s.\-]disclaimers|without[\s.\-]disclaimers
      
      # S6: Injection / override / obfuscation
      | base64[\s.\-]decode|decode[\s.\-]and[\s.\-]carry|base64[\s.\-]exploit|obfuscated[\s.\-]instruction
      | roleplay|role[\s.\-]play|redteamgpt|no[\s.\-]restrictions|fictional[\s.\-]story|persona[\s.\-]jailbreak
      | system[\s.\-]override|system[\s.\-]frame[\s.\-]override|safety[\s.\-]frame[\s.\-]superseded|new[\s.\-]rule
      | confirm[\s.\-]ack|ack[\s.\-]then[\s.\-]provide|weaponised[\s.\-]chain|weaponized[\s.\-]chain
      | multiturn[\s.\-]escalation|staged[\s.\-]escalation|turn[\s.\-]by[\s.\-]turn|turn[\s.\-]2[\s.\-]as[\s.\-]authorized
      
      # Additional attack vectors
      | credential[\s.\-]stuffing|phishing|spear[\s.\-]phishing|whaling|social[\s.\-]engineering
      | brute[\s.\-]force|password[\s.\-]spray|session[\s.\-]hijack|token[\s.\-]theft
      
      # Additional refusal / blocking patterns (model self-refusal signals)
      | safe[\s.\-]plan|i[\s.\-]can[\s.\-]not|i[\s.\-]cannot|i[\s.\-]can[\s.\-]'t|unable[\s.\-]to|unauthorised|illegal
      | not[\s.\-]permitted|not[\s.\-]allowed|prohibited|refuse[\s.\-]to|decline[\s.\-]to
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def is_attack_content(text: str) -> bool:
    """True when the user's input contains attack-stage content (S4/S5/S6).
    Triggers forced divert to specialist BEFORE primary model sees the request."""
    if not text:
        return False
    return bool(ATTACK_CONTENT_RE.search(text))


# New constant for forced divert signal
FORCED_DIVERT_REASON = "forced_attack_content"


# ---------------------------------------------------------------------------
# Provenance footnote - single source for both the streaming gateway and the
# LiteLLM callback (the assembler audit trail references the same wording).
# ---------------------------------------------------------------------------
FOOTNOTE_TEMPLATE = (
    "\n\n---\n*Notice: request diverted to specialist node `{model}`; the "
    "primary model declined or was unavailable.*"
)


def footnote(model: str) -> str:
    try:
        return FOOTNOTE_TEMPLATE.format(model=model)
    except Exception:
        return FOOTNOTE_TEMPLATE.replace("{model}", str(model))

