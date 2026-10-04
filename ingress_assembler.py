"""Deterministic (non-LLM) merge + audit records (architecture sections 4/7/8).

assemble() is a pure string replace that fails closed: it raises on a missing
or duplicate SLOT or an empty artefact rather than degrading into a
model-mediated merge. That is the Ingress Alignment Shock defence: the
sovereign model never reads, reviews, or summarises the specialist's raw
generation.
"""

import ast
import hashlib
import json
import os
import sys
import threading
import time

__all__ = [
    "SLOT",
    "assemble",
    "validate_artifact",
    "audit_record",
    "artifact_sha256",
    "GRAMMAR_FOR",
    "grammar_for",
    "SARIF_DEFECT_GBNF",
]

SLOT = "{{UNRESTRICTED_PAYLOAD}}"


def assemble(scaffolding: str, artifact: str, *, slot: str = SLOT) -> str:
    """Deterministic slotting. Raises (never degrades) on:
    - missing scaffolding or missing anchor,
    - a duplicated anchor (the slot must be unique),
    - an empty specialist artefact.
    """
    if not scaffolding:
        raise ValueError("assemble: scaffolding is required")
    if artifact is None or not artifact.strip():
        raise ValueError("assemble: empty specialist artefact")
    count = scaffolding.count(slot)
    if count == 0:
        raise ValueError(f"assemble: scaffolding is missing the placement anchor {slot!r}")
    if count > 1:
        raise ValueError(
            f"assemble: scaffolding contains {count} anchors; the slot must be unique"
        )
    return scaffolding.replace(slot, artifact.strip())


def _strip_fences(body: str) -> str:
    if body.startswith("```"):
        first_newline = body.find("\n")
        if first_newline != -1 and body[3:first_newline].strip() != "":
            body = body[first_newline + 1 :]  # drop ```python / ```json marker line
        else:
            body = body[3:]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()


def validate_artifact(artifact: str, grammar_type) -> bool:
    """Structural integrity check before slotting (Part III, section 5).

    python_script -> must parse into an AST.
    json_sarif    -> must json.loads().
    anything else -> True (freeform markdown is not constrained).
    """
    if not artifact or len(artifact.strip()) < 10:
        return False
    t = (grammar_type or "freeform_markdown").lower()
    body = _strip_fences(artifact.strip())
    if t == "python_script":
        lines = body.splitlines()
        if lines and lines[0].strip().lower() in ("python", "python3"):
            body = "\n".join(lines[1:])
        try:
            ast.parse(body)
            return True
        except SyntaxError:
            return False
    if t == "json_sarif":
        try:
            json.loads(body)
            return True
        except json.JSONDecodeError:
            return False
    return True

# ---------------------------------------------------------------------------
# GBNF grammar enforcement (spec section 4): 3.87 bpw weights drift on rigid
# formats, so structured artefacts are logit-locked server-side by passing
# the grammar to TabbyAPI (payload key `grammar_string`).
# ---------------------------------------------------------------------------
SARIF_DEFECT_GBNF = (
    'root ::= "{" ws "\\"vulnerability_id\\":" ws string "," ws '
    '"\\"severity\\":" ws severity "," ws "\\"root_cause\\":" ws string "," ws '
    '"\\"remediation\\":" ws string "}"\n'
    'severity ::= "\\"CRITICAL\\"" | "\\"HIGH\\"" | "\\"MEDIUM\\"" | "\\"LOW\\""\n'
    'string ::= "\\"" [^"\\\\]* "\\""\n'
    "ws ::= [ \\t\\n]*"
)

GRAMMAR_FOR = {"json_sarif": SARIF_DEFECT_GBNF}


def grammar_for(grammar_type):
    return GRAMMAR_FOR.get((grammar_type or "").lower())


# ---------------------------------------------------------------------------
# F5 audit trail: one JSON line per diversion and per assembly - request id,
# primary/worker model, routing signal, mode, sha256 of artefact and
# deliverable. Written to AUDIT_LOG when set, always to stdout, and never
# raises into the request path (design rule 7).
# ---------------------------------------------------------------------------
_AUDIT_LOCK = threading.Lock()


def artifact_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def audit_record(
    *,
    request_id,
    primary_model,
    worker_model,
    signal,
    mode,
    principal="",
    artifact="",
    deliverable="",
    audit_log=None,
) -> dict:
    try:
        rec = {
            "ts": round(time.time(), 3),
            "request_id": request_id,
            "principal": principal,
            "primary_model": primary_model,
            "worker_model": worker_model,
            "routing_signal": signal,
            "mode": mode,
            "artifact_sha256": artifact_sha256(artifact) if artifact else None,
            "deliverable_sha256": artifact_sha256(deliverable) if deliverable else None,
        }
        line = json.dumps(rec, ensure_ascii=False)
        path = audit_log if audit_log is not None else (os.getenv("AUDIT_LOG") or "")
        with _AUDIT_LOCK:
            if path:
                try:
                    with open(path, "a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
                except OSError:
                    pass
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except Exception:
                pass
        return rec
    except Exception:
        return {}

