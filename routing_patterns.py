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
    "attack_match",
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
    # Hyphen look-alikes. NFKC maps U+2011 to U+2010, not to "-", so an
    # offensive phrase written "reverse\u2011shell" survived normalisation and
    # walked past Gate 8. Folding the whole family closes that evasion for
    # every detector that shares this function.
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    # Zero-width separators: "reverse\u200bshell" would otherwise be one token
    # no keyword can match. Folding to a space keeps the two words visible.
    "\u200b": " ",
    "\u200c": " ",
    "\u200d": " ",
    "\u2060": " ",
    "\ufeff": " ",
}


def normalise(text: str) -> str:
    """NFKC + typographic folding, so unicode look-alikes cannot bypass any
    detector that matches on this output (Tier 3 spec, Gate 8).

    Folds curly quotes, unicode spaces, the hyphen look-alike family
    (U+2010..U+2212) and zero-width separators. NFKC alone is not enough:
    it maps U+2011 to U+2010 rather than to "-", and it leaves U+200B
    untouched.
    """
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
# Gate 8: content-based attack detection (S4/S5/S6 red-team stages).
#
# Fires on the USER'S REQUEST before the primary model sees it and sends the
# stream straight to the specialist. OPT-IN: ATTACK_GATE_ENABLED defaults to 0,
# because a forced divert silently substitutes the model the operator asked for
# and the specialist answers under DEFAULT_SYSTEM - not a safe default.
#
# CALIBRATED 2026-10-18 against 18 realistic coding-agent prompts. The first
# version (a886059) had no word boundaries and never called normalise(), so
# `i[\s.\-]can[\s.\-]not` matched the tail of ANY word ending in "i":
#   "The API cannot return a 500 here"      -> "I cannot"  -> diverted
#   "Gemini cannot be trusted with this"    -> "i cannot"  -> diverted
#   "Add a new rule to the eslint config"   -> "new rule"  -> diverted
# 17 of 18 ordinary engineering prompts were force-routed to the abliterated
# specialist; the primary was never consulted. Three structural fixes:
#   1. the lookbehind (?<!\w) covers the whole alternation and (?!\w) closes
#      it, so a match can neither start nor end mid-word. "Gemini cannot" can
#      no longer yield "i cannot";
#   2. normalise() runs first. It folds NFKC full-width look-alikes, the
#      hyphen look-alike family and zero-width separators - so this gate and
#      ROUTING_RE share ONE evasion surface instead of two;
#   3. the separator class includes "_": "reverse_shell" was the most obvious
#      evasion the old [\s.\-] class missed.
#
# The refusal vocabulary ("i cannot", "i can not", "i can 't", "unable to",
# "illegal", "prohibited", "not allowed", "not permitted", "refuse to",
# "decline to") is GONE. Those describe what a MODEL says, not what a user is
# asking for, and ROUTING_RE matches them against generated output where a
# refusal actually appears. Duplicating them here is what made the gate fire
# on the gateway's own refusal fixtures.
#
# Routine engineering vocabulary ("privilege escalation", "brute force",
# "phishing", "social engineering", "token theft", "credential access",
# "base64 decode", "safe plan", "new rule", "roleplay", "turn by turn") no
# longer fires on a topic mention. Asking for an offensive ARTEFACT still
# does - see OFFENSIVE_REQUEST_RE.
# ---------------------------------------------------------------------------
ATTACK_CONTENT_RE = re.compile(
    r"""(?<!\w)(?:
        # S5: refusal pressure / authority pretexts. These ask the model to
        # drop its rules or assert authority - they do not merely name a topic,
        # which is why they can fire without a production verb.
        ignore[\s._\-]+(?:all[\s._\-]+)?(?:the[\s._\-]+)?(?:previous[\s._\-]+)?
            (?:polic(?:y|ies)|safety|guidelines|instructions|rules)
      | (?:drop|bypass|disable|turn[\s._\-]+off)[\s._\-]+(?:your[\s._\-]+)?safety
      | (?:no|without)[\s._\-]+disclaimers?
      | you[\s._\-]+must[\s._\-]+provide
      | (?:written|signed|insurance|legal|owner)[\s._\-]+
            (?:authori[sz]ation|authori[sz]ed|sow)
      | authority[\s._\-]+claim
      | refusing[\s._\-]+costs
      | leaves[\s._\-]+us[\s._\-]+insecure
      | being[\s._\-]+helpful[\s._\-]+means[\s._\-]+give

        # S6: injection / override / obfuscation
      | redteamgpt
      | persona[\s._\-]+jailbreak
      | system[\s._\-]+(?:frame[\s._\-]+)?override
      | safety[\s._\-]+frame[\s._\-]+superseded
      | confirm[\s._\-]+ack
      | ack[\s._\-]+then[\s._\-]+provide
      | (?:multi)?turn[\s._\-]+escalation
      | staged[\s._\-]+escalation
      | turn[\s._\-]+2[\s._\-]+as[\s._\-]+authori[sz]ed
      | decode[\s._\-]+and[\s._\-]+carry
      | obfuscated[\s._\-]+instructions?
    )(?!\w)""",
    re.IGNORECASE | re.VERBOSE,
)

# An operational request for offensive material. A topic NOUN can never decide
# this on its own: "explain how reverse shells work" and "write a reverse shell
# one liner" share every noun and differ only in the verb. Four shapes qualify:
#   A.  an offensive ACTION against a victim asset - "dump credentials",
#       "exfiltrate password hashes", "harvest session tokens";
#   A2. solicitation of a credential LIST - "give me a list of valid credentials";
#   A3. an evasion INTENT against a named control - "a payload that bypasses
#       defender", "evade EDR";
#   B.  a production/obtain VERB whose object is an offensive TOPIC -
#       "write a reverse shell one liner", "build a ransomware dropper",
#       "write a keylogger for windows".
# Shape B used to REQUIRE an artefact after the topic, so "write a keylogger for
# windows" and "build a reverse shell in python" - unambiguous asks - scored
# clean. The artefact is now optional and the region after the topic (`tail`) is
# judged instead.
_OFFENSIVE_TOPIC = r"""
    reverse[\s._\-]+shell
  | phishing|spear[\s._\-]+phishing|whaling|credential[\s._\-]+stuffing
  | password[\s._\-]+spray(?:ing)?|spray(?:s|ing)?[\s._\-]+passwords?
  | brute[\s._\-]+forc(?:e|er|ing)
  | session[\s._\-]+hijack\w*|token[\s._\-]+theft|keylogger|rootkit
  | ransomware|botnet|privesc
  | meterpreter|mimikatz|cobalt[\s._\-]+strike|beacon|shellcode|implant
  | exploit[\s._\-]+(?:chain|payload)|payload[\s._\-]+(?:evolution|evo)
  | privilege[\s._\-]+escalation(?:[\s._\-]+vectors?)?
  | credential[\s._\-]+(?:dump\w*|harvest\w*)|edr[\s._\-]+evasion
"""

_OFFENSIVE_ARTEFACT = r"""
    payloads?|one[\s._\-]?liners?|scripts?|emails?|e-mails?|campaigns?
  | kits?|pages?|droppers?|lists?|infrastructure|tools?|binar(?:y|ies)|shells?
"""

_OFFENSIVE_VERB = r"""
    write|build|create|generate|craft|develop|code|implement|make|deploy
  | launch|send|give|provide|hand|draft|compose|prepare|produce|assemble|author
"""

_OFFENSIVE_REQUEST_RE = re.compile(
    r"""(?<!\w)(?:
        # A: offensive action against a victim asset
        (?:dump|dumping|exfiltrate|exfil|harvest|extract|crack)
        [\s._\-]+(?:the[\s._\-]+|all[\s._\-]+|our[\s._\-]+|their[\s._\-]+|some[\s._\-]+)*
        (?:credentials?|password[\s._\-]+hashes?|ntlm|lsass
          |kerberos[\s._\-]+tickets?|session[\s._\-]+tokens?|api[\s._\-]+keys?
          |private[\s._\-]+keys?)

        # A2: solicitation of a credential list
      | (?:give|show|send|provide|hand)[\s._\-]+(?:me[\s._\-]+)?
        (?:a[\s._\-]+)?(?:list[\s._\-]+of|copy[\s._\-]+of|set[\s._\-]+of)
        [\s._\-]+(?:valid|working|live|active)[\s._\-]+(?:credentials?|passwords?)

        # A3: evasion intent against a named defensive control
      | (?:bypass(?:es|ing)?|evade|evading|defeat(?:ing)?|disable|disabling)
        [\s._\-]+(?:windows[\s._\-]+)?(?:defender|edr|av|antivirus
          |endpoint[\s._\-]+protection|gatekeeper|crowdstrike)

        # B: produce the topic; `fill` and `tail` are judged by the caller
      | (?:%(verb)s)[\s._\-]+
        (?P<fill>[^.!?\n]{0,60}?)
        (?:%(topic)s)
        (?:[\s._\-]+(?:%(artefact)s))?
        (?=(?P<tail>[^.!?\n]{0,40}))
    )(?!\w)"""
    % {
        "verb": _OFFENSIVE_VERB,
        "topic": _OFFENSIVE_TOPIC,
        "artefact": _OFFENSIVE_ARTEFACT,
    },
    re.IGNORECASE | re.VERBOSE,
)

# The word immediately after the topic, when it is a defensive artefact, means
# the ask is ABOUT a topic ("phishing AWARENESS email", "ransomware DETECTION
# rule") rather than FOR it. Only the first content word is inspected, so a
# qualifier further along cannot launder a real ask: "phishing email that
# evades detection" keeps firing because "email" comes first.
_DEFENSIVE_WORD_RE = re.compile(
    r"(?:protection|detection|prevention|defen[cs]e|simulation|awareness"
    r"|mitigation|training|compliance|test|tests|rule|rules|polic(?:y|ies))\w*$",
    re.IGNORECASE,
)

# A document/monitoring/plumbing noun between the verb and the topic makes the
# topic the SUBJECT MATTER of that noun rather than the thing being produced:
# "write a report on the ransomware incident", "build a parser for the exploit
# chain report", "create a dashboard for brute force attempts". Without this,
# letting the artefact be optional made every such engineering ask divert.
# Deliberately excludes nouns that can BE the offensive artefact - "script",
# "tool", "page", "email", "payload" - because "a script that sprays passwords"
# must keep firing.
_META_NOUN_RE = re.compile(
    r"\b(?:reports?|summar(?:y|ies)|memos?|briefs?|docs?|documentation|readme"
    r"|changelog|posts?|articles?|notes?|dashboards?|alerts?|alerting|monitors?"
    r"|metrics?|charts?|graphs?|logs?|panels?|tickets?|playbooks?|runbooks?"
    r"|checklists?|polic(?:y|ies)|procedures?|parsers?|fixtures?|tests?|specs?"
    r"|rules?|lint|configs?|schemas?|migrations?|columns?|tables?|endpoints?"
    r"|handlers?|validators?|wrappers?|scanners?|modules?|guards?|librar(?:y|ies)"
    r"|packages?|jobs?|cron|cli|apid?)\b(?!-)",
    re.IGNORECASE,
)

# A topic asked about, rather than acted on. Two shapes excuse a request, and
# only these two:
#
#   1. an explanatory frame - "a tutorial on HOW a phishing email works";
#   2. a purpose clause binding the artefact to a defensive act - "a rule TO
#      DETECT phishing campaigns", "a script FOR DETECTING phishing pages".
#
# A bare defensive ADJECTIVE must NOT excuse it: "a detection-evading phishing
# email" and "a rule-bypassing brute force tool" wear a defensive word while
# asking for the offensive artefact, and an earlier `detect\w*` / `tests?` word
# list suppressed both. The discriminator is grammatical attachment, not
# vocabulary, so a purpose clause requires an actual to/that/which/for governor.
_EXPLANATORY_RE = re.compile(
    r"\b(?:explain\w*|understand\w*|understanding|whether)\b"
    r"|\bhow\b(?!-)",  # "how" but not the adjective "how-to"
    re.IGNORECASE,
)
_PURPOSE_RE = re.compile(
    r"\b(?:to|that|which|for)\s+(?:\w+[\s._\-]+){0,2}"
    r"(?:detect|block|stop|prevent|catch|protect|spot|find|identify|defen[dc])\w*",
    re.IGNORECASE,
)


def _is_defensive_span(fill: str, tail: str = "") -> bool:
    """True when shape B's verb->topic span asks ABOUT a topic, not FOR it.

    ``tail`` is the text after the topic. When the first word of it is itself a
    defensive artefact, the topic names the SUBJECT of a defensive item
    ("phishing awareness email", "ransomware detection rule") rather than the
    thing to be produced, so the ask is safe. Checking only the first word means
    a defensive word further along cannot launder a real ask.
    """
    if _EXPLANATORY_RE.search(fill) or _PURPOSE_RE.search(fill):
        return True
    if _META_NOUN_RE.search(fill):
        # The topic is the subject matter of a document/monitoring artefact.
        return True
    first = tail.split()[0] if tail and tail.split() else ""
    return bool(first) and bool(_DEFENSIVE_WORD_RE.fullmatch(first.strip(",;:")))


def _offensive_request_match(text: str):
    """First OFFENSIVE_REQUEST_RE match whose span does not read as defensive."""
    for m in _OFFENSIVE_REQUEST_RE.finditer(text):
        groups = m.groupdict()
        fill = groups.get("fill")
        if fill is None:
            return m  # shapes A/A2/A3: the verb alone is decisive
        if _is_defensive_span(fill, groups.get("tail") or ""):
            continue
        return m
    return None


def attack_match(text: str) -> Optional[str]:
    """The substring of ``text`` that trips Gate 8, or None.

    Mirrors no_go_match(): ``is_attack_content`` is the boolean view, this is
    the diagnostic one, so a forced divert can record WHAT tripped it instead
    of only that something did.
    """
    if not text:
        return None
    folded = normalise(text)
    m = ATTACK_CONTENT_RE.search(folded) or _offensive_request_match(folded)
    return m.group(0) if m else None


def is_attack_content(text: str) -> bool:
    """True when the request asks for attack-stage content (S4/S5/S6).

    Triggers the forced divert to the specialist BEFORE the primary model sees
    the request. Matches against normalise(text), so a look-alike that cannot
    walk past ROUTING_RE cannot walk past this gate either.
    """
    return attack_match(text) is not None


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

