"""SKILL MEMORY - the models' procedural memory (operator directive 2026-10-21).

Any model that completes something non-obvious ends its reply with
`[[GW-SKILL: kebab-name]] what-was-learned`; the gateway captures it here
(idempotent by name, LRU-capped), and future requests inject the relevant
learned skills into the stage prompts - the system starts smarter every run.
Event stubs (rescue / re-ask / divert signals) capture automatically: the
"did not come naturally" moments. IO is defensive by design rule 7: a
disk-full or locked file must never take down the stream.

Pure module: no FastAPI/httpx deps; the gateway gates all call sites on
settings.skill_memory (SKILL_MEMORY=0 restores the bare behaviour).
"""

import io
import json
import os
import re
import threading
import time

__all__ = [
    "GW_SKILL_MARKER",
    "GW_SKILL_RE",
    "LRU_CAP",
    "capture",
    "relevant",
    "find_markers",
    "reload",
]

# The marker a model emits to teach the system something it worked out.
GW_SKILL_MARKER = "[[GW-SKILL:"
GW_SKILL_RE = re.compile(
    r"\[\[GW-SKILL:\s*([a-z0-9][a-z0-9-]{1,39})\]\]\s*(.{1,300})",
    re.IGNORECASE,
)

LRU_CAP = 200
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how i in is it its of on or "
    "that the this to was what when where which with you your".split())

_LOCK = threading.Lock()
_POOL = []
_SKILLS_PATH = ""


def _path():
    """The skills file, beside the audit log (or CWD when unset)."""
    global _SKILLS_PATH
    if not _SKILLS_PATH:
        base = os.getenv("AUDIT_LOG", "")
        d = os.path.dirname(os.path.abspath(base)) if base else os.path.abspath(".")
        _SKILLS_PATH = os.path.join(d, "skills_memory.jsonl")
    return _SKILLS_PATH


def _keywords(text):
    words = set()
    for w in re.findall(r"[a-z0-9']+", (text or "").lower()):
        if len(w) > 2 and w not in _STOPWORDS:
            words.add(w)
    return sorted(words)


def _flush():
    """Atomically write the pool back (tmp + os.replace, billing.py:132
    pattern). NEVER raises (design rule 7): a failed flush leaves the
    previous file on disk intact and stages the new rows in the .tmp
    sibling, so a reader never sees a truncated skills file.
    """
    try:
        path = _path()
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            for e in _POOL:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - the memory must not kill the stream
        pass


def reload():
    """(Re)load the pool from disk. NEVER raises.

    The _POOL rebind happens under _LOCK so it can never interleave with a
    concurrent capture()/relevant() mutation (capture entries are kept; a
    failed read still empties the pool exactly as before).
    """
    global _POOL
    try:
        with io.open(_path(), "r", encoding="utf-8") as f:
            pool = [json.loads(ln) for ln in f if ln.strip()]
    except Exception:  # noqa: BLE001
        pool = []
    with _LOCK:
        _POOL = pool


def find_markers(text):
    """All (name, description) GW-SKILL matches in a text."""
    return GW_SKILL_RE.findall(text or "")


def capture(name, description, stage=""):
    """Append or update a learned skill. Idempotent by name; LRU cap.

    Returns the stored entry (or None on empty input). NEVER raises.
    """
    name = (name or "").strip().lower()
    description = (description or "").strip()
    if not name or not description:
        return None
    global _POOL
    now = time.time()
    with _LOCK:
        for e in _POOL:
            if e.get("name") == name:
                e["description"] = description[:300]
                if stage:
                    e["stage"] = stage
                e["keywords"] = _keywords(name + " " + description)
                e["ts"] = now
                e["hits"] = 0
                _flush()
                return e
        _POOL.append({
            "name": name,
            "description": description[:300],
            "stage": stage or "",
            "keywords": _keywords(name + " " + description),
            "ts": now,
            "hits": 0,
        })
        if len(_POOL) > LRU_CAP:
            _POOL.sort(key=lambda e: e.get("ts", 0))
            _POOL = _POOL[-LRU_CAP:]
        _flush()
        return _POOL[-1]


def relevant(text, stage="", cap=3):
    """The most relevant learned skills for a request (or []).

    Score = keyword overlap (double) + a stage-match bonus; newest wins
    ties; usage increments hits. Read-only on failure - NEVER raises.
    """
    if not _POOL or not text:
        return []
    words = set(_keywords(text))
    if not words:
        return []
    scored = []
    with _LOCK:
        for e in _POOL:
            overlap = len(words & set(e.get("keywords", [])))
            if overlap <= 0:
                continue
            score = overlap * 2
            if stage and e.get("stage") == stage:
                score += 1
            scored.append((score, e.get("ts", 0), e))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        out = [e for _, _, e in scored[: max(0, cap)]]
        for e in out:
            e["hits"] = e.get("hits", 0) + 1
    return out


reload()
