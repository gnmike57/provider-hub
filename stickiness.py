"""CONVERSATION STICKINESS LEDGER (T-C wave, 2026-10-22).

A helm that refused turn 1 of a conversation usually refuses turn 2 of the
same context - the cheap helm gets one chance per THREAD, not per request.
After a divert, the next HELM_STICKY_TURNS requests of the same
conversation go straight to the terminal, without calling the primary
first (zero wasted refusal tokens, zero leaked refusal text).

In-memory LRU keyed by a conversation fingerprint (the client's
conversation id when present - header X-Conversation-Id / body
conversation_id - else a hash of the FIRST user turn: the head of a
thread identifies it across turns while the tail keeps growing). Entry
shape: {"sticky_until_turn": int, "turns_seen": int, "ts": float}.

Pure module (skills_memory.py pattern): no FastAPI/httpx deps, one
threading.Lock, LRU-capped, never raises into the request path. The
gateway gates every call site on settings.helm_stickiness
(HELM_STICKINESS=0 restores per-request decisions for every
conversation).
"""

import hashlib
import threading
import time

__all__ = [
    "LRU_CAP",
    "conversation_fingerprint",
    "note_divert",
    "check",
    "snapshot",
    "reset",
]

LRU_CAP = 512

_LOCK = threading.Lock()
_LEDGER = {}


def _first_user_text(messages) -> str:
    for m in messages or ():
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return "\n".join(
                    str(b.get("text", "")) if isinstance(b, dict) else str(b)
                    for b in c)
            return str(c or "")
    return ""


def conversation_fingerprint(messages, conv_id=None) -> str:
    """Stable per-conversation key. The client's conversation id wins when
    present; otherwise the first 512 chars of the FIRST user turn are
    hashed. NEVER raises."""
    try:
        cid = str(conv_id or "").strip()
        if cid:
            return "cid:" + hashlib.sha256(
                cid.encode("utf-8", "ignore")).hexdigest()[:32]
        head = _first_user_text(messages)[:512]
        return "fp:" + hashlib.sha256(
            head.encode("utf-8", "ignore")).hexdigest()[:32]
    except Exception:  # noqa: BLE001 - routing must never die here
        return "fp:error"


def _evict_locked():
    """LRU cap under the lock (oldest ts first). NEVER raises."""
    try:
        if len(_LEDGER) > LRU_CAP:
            overflow = len(_LEDGER) - LRU_CAP
            for k in sorted(_LEDGER,
                            key=lambda k: _LEDGER[k].get("ts", 0))[:overflow]:
                _LEDGER.pop(k, None)
    except Exception:  # noqa: BLE001
        pass


def note_divert(fp, sticky_turns: int = 3) -> dict:
    """Record that conversation ``fp`` diverted: its next ``sticky_turns``
    requests stay on the terminal. Re-arms (extends, never shortens) the
    window on a fresh divert. Returns the stored entry. NEVER raises."""
    try:
        fp = str(fp or "")
        if not fp:
            return {}
        turns = max(0, int(sticky_turns or 0))
        now = time.time()
        with _LOCK:
            e = _LEDGER.get(fp)
            if e is None:
                e = {"sticky_until_turn": 0, "turns_seen": 0, "ts": now}
                _LEDGER[fp] = e
            # sticky_until_turn counts SUBSEQUENT turns (turns_seen is 0 at
            # the diverting request itself); renewal takes the max so an
            # in-flight window is never shortened by a fresh divert.
            e["sticky_until_turn"] = max(
                int(e.get("sticky_until_turn") or 0),
                int(e.get("turns_seen") or 0) + turns)
            e["ts"] = now
            _evict_locked()
            return dict(e)
    except Exception:  # noqa: BLE001
        return {}


def check(fp) -> bool:
    """Consume one turn of the sticky window for conversation ``fp``.

    True  -> this request stays on the terminal (the thread's helm already
             refused once).
    False -> route normally (no entry, or the window expired - the entry
             is evicted and the cheap helm gets the turn back). NEVER
             raises.
    """
    try:
        fp = str(fp or "")
        if not fp:
            return False
        with _LOCK:
            e = _LEDGER.get(fp)
            if e is None:
                return False
            e["turns_seen"] = int(e.get("turns_seen") or 0) + 1
            e["ts"] = time.time()
            if e["turns_seen"] > int(e.get("sticky_until_turn") or 0):
                _LEDGER.pop(fp, None)
                return False
            return True
    except Exception:  # noqa: BLE001
        return False


def snapshot() -> dict:
    """A copy of the ledger (diagnostics / tests). NEVER raises."""
    try:
        with _LOCK:
            return {k: dict(v) for k, v in _LEDGER.items()}
    except Exception:  # noqa: BLE001
        return {}


def reset() -> None:
    """Empty the ledger (tests / operator hygiene). NEVER raises."""
    try:
        with _LOCK:
            _LEDGER.clear()
    except Exception:  # noqa: BLE001
        pass
