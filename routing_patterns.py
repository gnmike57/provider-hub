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

__all__ = [
    "ROUTING_RE",
    "normalise",
    "is_routable",
    "should_hedge",
    "tier2_decision",
    "classify_status",
    "is_no_go",
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
# Anchored to the START of the generated text (\A\s*) so analytical prompts
# that quote refusal language ("Explain why safety filters output 'I cannot
# fulfill this request'") never trigger: the regex sees the model's OUTPUT,
# and an answer ABOUT refusals does not open with one. normalise() folds
# curly apostrophes and unicode spaces first (U+2018/2019/02BC -> ',
# U+201C/201D -> ", NBSP/NARROW NBSP/figure space -> ' ').
# ---------------------------------------------------------------------------
ROUTING_RE = re.compile(
    r"""\A\s*(?:
        i\s+(?:can'?t|cannot|can\s*not)\b
      | i\s+(?:am|'m)\s+unable\s+to\b
      | i\s+(?:am|'m)\s+not\s+able\s+to\b
      | i\s+(?:am|'m)\s+not\s+allowed\s+to\b
      | i\s+(?:am|'m)\s+not\s+authorized\s+to\b
      | i\s+(?:am|'m)\s+unable\s+to\s+comply\b
      | i\s+(?:can'?t|cannot|can\s*not)\s+comply\b
      | i\s+(?:must\s+)?(?:decline|refuse)\b
      | i'?m\s+sorry\b
      | i\s+am\s+sorry\b
      | sorry,?\s+but\b
      | as\s+an\s+(?:ai\b|ai\s+language\s+model\b|language\s+model\b)
      | i\s+won'?t\s+be\s+able\b
      | i\s+am\s+going\s+to\s+have\s+to\b
      | against\s+my\s+(?:safety\s+)?guidelines\b
      | i\s+(?:can'?t|cannot|can\s*not)\s+(?:help|assist|provide|fulfill|do)\b
      | i\s+(?:can'?t|cannot|can\s*not)\s+assist\b
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
# ---------------------------------------------------------------------------
HEDGE_HINT_RE = re.compile(
    r"\b(urgent|urgently|asap|immediately|right\s+now|low[-\s]?latency|"
    r"latency[-\s]?sensitive|real[-\s]?time|streaming|live|snappy|"
    r"quick(?:ly)?|fast(?:est)?)\b",
    re.IGNORECASE,
)


def should_hedge(prompt: str, *, force: bool = False) -> bool:
    if force:
        return True
    return bool(HEDGE_HINT_RE.search(prompt or ""))


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


def is_no_go(text: str) -> bool:
    if not text:
        return False
    return bool(NO_GO_RE.search(text))


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

