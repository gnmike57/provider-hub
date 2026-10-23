"""Model Constellation Control Room - the creative switching layer (2026-10-19).

Creative model on top of the existing /v1/switch machinery: the gateway's
slots get constellation names, presets and a control room UI, so changing the
primary / specialist / secondary model is a point-and-click operation.

Slots (creative names, backward-compatible aliases in brackets):

    helm        the primary conversational model      [primary]
    specialist  the refusal / divert fallback model  [worker]
    scout       the cheap probe / pre-screen model   [secondary]

The scout slot is NEW: it is the model used for health probing (/healthz),
the background constellation probe and (optionally) cheap pre-screening. It
defaults to the helm binding, so a deployment that never touches it behaves
exactly as before.

Components in this module:

    Constellations   named 3-slot presets                 (constellations.json)
    ModelDNA         capability metadata per model         (heuristics + file)
    HealthTracker    rolling provider health scores      (model_health.jsonl)
    BindingHistory   time-travel slot binding history     (slot_bindings.json)

Persistence model: every runtime switch appends a full snapshot of all three
slots to BindingHistory. On boot the gateway restores the latest entry
(SLOT_PERSISTENCE=0 disables), so a model change survives restarts. Every
entry older than 7 days is pruned, so the file cannot grow unbounded.

Design rules (mirrors the proxy_gateway header):
    6. Guards run once, shared by the endpoints that call into here.
    7. Nothing in this module raises into the request path - history and
       health failures are swallowed or reported, never fatal to a switch.

Run: imported by proxy_gateway / model_switch (lazy, no circular import -
this module imports neither).
"""

import json
import os
import threading
import time
from typing import Dict, List, Optional

__all__ = [
    "SLOTS",
    "SLOT_DISPLAY",
    "SLOT_TARGET",
    "normalize_slot",
    "Constellations",
    "HealthTracker",
    "BindingHistory",
    "model_dna",
    "promotion_suggestions",
    "CONSTELLATIONS",
    "HEALTH",
    "BINDING_HISTORY",
]

ROOT = os.path.dirname(os.path.abspath(__file__))
CONSTELLATIONS_PATH = os.getenv("CONSTELLATIONS_FILE", os.path.join(ROOT, "constellations.json"))
HEALTH_PATH = os.getenv("MODEL_HEALTH_FILE", os.path.join(ROOT, "model_health.jsonl"))
HISTORY_PATH = os.getenv("SLOT_HISTORY_FILE", os.path.join(ROOT, "slot_bindings.json"))

# How long health events / binding history entries are kept.
RETENTION_S = 7 * 86400
MAX_HISTORY_ENTRIES = 500
# Health score below which a slot's model is considered degraded and a
# promotion suggestion is emitted (0-100, recency-weighted probe mean).
DEGRADED_THRESHOLD = 50.0

# --------------------------------------------------------------------------
# Slot vocabulary: display name <-> model_switch internal target.
# model_switch keeps its canonical targets (primary/worker/scout); the
# constellation layer speaks the creative names and translates.
# --------------------------------------------------------------------------
SLOTS = ("helm", "specialist", "scout")

# display name -> model_switch target
SLOT_TARGET = {
    "helm": "primary",
    "primary": "primary",
    "specialist": "worker",
    "worker": "worker",
    "scout": "scout",
    "secondary": "scout",
}

# model_switch target -> display name
SLOT_DISPLAY = {
    "primary": "helm",
    "worker": "specialist",
    "scout": "scout",
}


def normalize_slot(name: str) -> str:
    """'Helm' / 'primary' / 'SECONDARY' -> 'helm' / 'helm' / 'scout'.

    Raises ValueError on an unknown slot name (callers turn this into a 400).
    """
    key = str(name or "").strip().lower()
    if key not in SLOT_TARGET:
        raise ValueError(
            f"unknown slot {name!r}; expected one of "
            "helm/primary, specialist/worker, scout/secondary"
        )
    return SLOT_TARGET[key]


def _atomic_write_jsonl(path: str, rows: List[dict]) -> None:
    """Write rows as JSONL: temp file + replace (Registry.save pattern)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _load_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    rows: List[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn line never takes the hub down
    return rows

# --------------------------------------------------------------------------
# Constellations: named 3-slot presets.
# --------------------------------------------------------------------------
class Constellations:
    """Thread-safe view over constellations.json.

    Preset shape (provider/model ids resolve through the provider registry
    at APPLY time, so a preset never hardcodes URLs or keys):

        {
          "constellations": {
            "deep-space": {
              "description": "...",
              "slots": {"helm": {"provider": "hive", "model": "deepfrost-max-think"},
                        "specialist": {...}, "scout": {...}}
            }
          }
        }

    A missing file is not an error: list() is simply empty until one is
    written (the UI shows an empty gallery with a hint).
    """

    def __init__(self, path: str = ""):
        self.path = path or CONSTELLATIONS_PATH
        self._lock = threading.Lock()
        self._cache: Dict[str, dict] = {}
        self._mtime = 0.0
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = 0.0
        with self._lock:
            if not force and mtime and mtime == self._mtime:
                return
            self._cache = {}
            self._mtime = 0.0
            if not mtime:
                return
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                presets = raw.get("constellations") or {}
                if isinstance(presets, dict):
                    self._cache = {
                        str(name): preset
                        for name, preset in presets.items()
                        if isinstance(preset, dict)
                    }
                    self._mtime = mtime
            except (OSError, json.JSONDecodeError):
                pass  # a broken file reads as "no presets", never raises

    def list(self) -> List[dict]:
        """Public read-back for GET /v1/constellations (no secrets inside)."""
        self.reload()
        with self._lock:
            out = []
            for name, preset in self._cache.items():
                slots = preset.get("slots") or {}
                out.append(
                    {
                        "name": name,
                        "description": str(preset.get("description") or ""),
                        "slots": {
                            slot: {
                                "provider": str((slots.get(slot) or {}).get("provider") or ""),
                                "model": str((slots.get(slot) or {}).get("model") or ""),
                            }
                            for slot in SLOTS
                            if slots.get(slot)
                        },
                    }
                )
            return out

    def get(self, name: str) -> Optional[dict]:
        self.reload()
        with self._lock:
            preset = self._cache.get(str(name or "").strip().lower())
            return dict(preset) if preset else None

    def save(self, data: dict) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"constellations": data}, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        self.reload(force=True)

# --------------------------------------------------------------------------
# HealthTracker: rolling, recency-weighted provider health.
# --------------------------------------------------------------------------
class HealthTracker:
    """Appends provider probe results to model_health.jsonl and scores them.

    A model inherits its PROVIDER's health (probes hit {base}/models, which
    is provider-wide) - probing per model would need a completion call per
    model, which is not cheap. Score = recency-weighted mean of ok over the
    retained window, 0 (all recent probes failing) .. 100 (all passing).

    record() NEVER raises (design rule 7): a disk-full or locked file must
    not take down the probe loop or a switch.
    """

    def __init__(self, path: str = ""):
        self.path = path or HEALTH_PATH
        self._lock = threading.Lock()
        self._events: List[dict] = []
        self._load()

    def _load(self) -> None:
        cutoff = time.time() - RETENTION_S
        try:
            rows = _load_jsonl(self.path)
        except OSError:
            rows = []
        with self._lock:
            self._events = [
                r for r in rows
                if isinstance(r, dict) and isinstance(r.get("ts"), (int, float))
                and r.get("ts") >= cutoff
            ]

    def record(self, provider_id: str, ok: bool, latency_ms: float = 0.0,
               detail: str = "") -> None:
        event = {
            "ts": time.time(),
            "provider": str(provider_id),
            "ok": bool(ok),
            "latency_ms": round(float(latency_ms or 0.0), 1),
            "detail": str(detail or "")[:200],
        }
        try:
            with self._lock:
                self._events.append(event)
                cutoff = time.time() - RETENTION_S
                self._events = [e for e in self._events if e.get("ts", 0) >= cutoff]
                _atomic_write_jsonl(self.path, self._events)
        except OSError:
            pass  # history is advisory; the probe result is still in memory

    def provider_scores(self) -> Dict[str, dict]:
        """{provider_id: {score, probes, last_probe, last_ok, avg_latency_ms}}.

        Recency weighting: each event counts as ok * 0.75 ** age_hours, so
        an outage an hour ago matters more than one yesterday, and recovery
        pulls the score back up faster than a plain mean would.
        """
        now = time.time()
        by_provider: Dict[str, List[dict]] = {}
        with self._lock:
            for e in self._events:
                by_provider.setdefault(e.get("provider", "?"), []).append(dict(e))
        scores: Dict[str, dict] = {}
        for pid, events in by_provider.items():
            weighted_ok = 0.0
            weight = 0.0
            latencies = []
            last_ok = None
            for e in events:
                age_h = max(0.0, (now - e.get("ts", now)) / 3600.0)
                w = 0.75 ** age_h
                weight += w
                if e.get("ok"):
                    weighted_ok += w
                    last_ok = e.get("ts") if last_ok is None else max(last_ok, e.get("ts"))
                latencies.append(float(e.get("latency_ms") or 0.0))
            scores[pid] = {
                "score": round(100.0 * weighted_ok / weight, 1) if weight else 0.0,
                "probes": len(events),
                "last_probe": events[-1].get("ts") if events else None,
                "last_ok": last_ok,
                "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            }
        return scores

    def snapshot(self) -> List[dict]:
        """Raw recent events (read-back for the Control Room timeline)."""
        with self._lock:
            return [dict(e) for e in self._events[-40:]]

# --------------------------------------------------------------------------
# BindingHistory: time-travel rollback for slot bindings.
# --------------------------------------------------------------------------
class BindingHistory:
    """Every runtime switch appends a full 3-slot snapshot here.

    slot_bindings.json (JSONL) holds keys in plaintext exactly like
    gateway_registry.json does (review items 1-4 are still open by choice);
    the API layer masks them on every read-back (key_present booleans).

    entry_at(ts) finds the latest entry at or before ts - the "time travel"
    behind POST /v1/switch {"rollback_to": "..."}.
    """

    def __init__(self, path: str = ""):
        self.path = path or HISTORY_PATH
        self._lock = threading.Lock()
        self._entries: List[dict] = []
        self._load()

    def _load(self) -> None:
        cutoff = time.time() - RETENTION_S
        try:
            rows = _load_jsonl(self.path)
        except OSError:
            rows = []
        with self._lock:
            self._entries = [
                r for r in rows
                if isinstance(r, dict) and isinstance(r.get("ts"), (int, float))
                and r.get("ts") >= cutoff
            ][-MAX_HISTORY_ENTRIES:]

    def record(self, slots: Dict[str, dict], request_id: str = "",
               principal: str = "", action: str = "switch") -> None:
        """Append a snapshot; never raises (design rule 7).

        slots: {"helm": {"url","key","model","provider_id"}, ...} - full
        truth for all three slots at once, so one entry restores everything.
        """
        entry = {
            "ts": time.time(),
            "request_id": str(request_id or ""),
            "principal": str(principal or ""),
            "action": str(action or "switch"),
            "slots": {
                slot: {
                    "url": str(b.get("url") or ""),
                    "key": str(b.get("key") or ""),
                    "model": str(b.get("model") or ""),
                    "provider_id": str(b.get("provider_id") or ""),
                }
                for slot, b in (slots or {}).items()
                if isinstance(b, dict)
            },
        }
        try:
            with self._lock:
                self._entries.append(entry)
                cutoff = time.time() - RETENTION_S
                self._entries = [e for e in self._entries if e.get("ts", 0) >= cutoff]
                del self._entries[:-MAX_HISTORY_ENTRIES]
                _atomic_write_jsonl(self.path, self._entries)
        except OSError:
            pass

    def entries(self, limit: int = 50) -> List[dict]:
        """Masked read-back (keys -> key_present) for the Control Room."""
        with self._lock:
            out = []
            for e in self._entries[-int(limit):]:
                out.append({
                    "ts": e.get("ts"),
                    "request_id": e.get("request_id"),
                    "principal": e.get("principal"),
                    "action": e.get("action"),
                    "slots": {
                        slot: {
                            "url": b.get("url"),
                            "model": b.get("model"),
                            "provider_id": b.get("provider_id"),
                            "key_present": bool(b.get("key")),
                        }
                        for slot, b in (e.get("slots") or {}).items()
                    },
                })
            return list(reversed(out))  # newest first for the timeline UI

    def entry_at(self, ts: float) -> Optional[dict]:
        """Latest entry with ts <= the given timestamp (None when none fit)."""
        best = None
        with self._lock:
            for e in self._entries:
                if e.get("ts", 0) <= ts and (best is None or e.get("ts", 0) >= best.get("ts", 0)):
                    best = e
        return best

    def latest(self) -> Optional[dict]:
        with self._lock:
            return dict(self._entries[-1]) if self._entries else None

# --------------------------------------------------------------------------
# Model DNA: capability metadata, derived from names + provider knowledge.
# --------------------------------------------------------------------------
def model_dna(exposed_name: str, provider_id: str, upstream_id: str = "") -> dict:
    """Heuristic capability profile for one model.

    Tags drive the Control Room UI chips and the preset compatibility hint.
    This is derived (not hand-maintained) so a model added to the registry
    tomorrow gets a DNA card for free. Name patterns are intentionally
    coarse - DNA is a hint, never a routing decision.
    """
    name = f"{exposed_name} {upstream_id}".lower()
    tags: List[str] = []
    handles = "general"
    if "max-think" in name.replace(" ", "-") or "max think" in name:
        tags.append("max-reasoning")
        handles = "max-reasoning"
    elif any(k in name for k in ("deepseek", "glm", "reason", "think")):
        tags.append("reasoning")
        handles = "reasoning"
    if any(k in name for k in ("coder", "code", "qwen")):
        tags.append("coding")
    if any(k in name for k in ("abliterated", "uncensored", "cyber")):
        tags.append("uncensored")
    if "frost" in name:
        tags.append("legacy-frost")  # CyberFrost deleted 2026-10-23 (was "speculative")
    latency_tier = "mid"
    if any(k in name for k in ("flash", "mini", "small", "8b")):
        latency_tier = "fast"
        tags.append("fast")
    elif any(k in name for k in ("480b", "large", "max")):
        latency_tier = "slow"
    # Local providers (the gx10 hub) are effectively free to run.
    cost_tier = "free" if provider_id in ("cyberhub", "env-worker") else (
        "low" if "flash" in name else "mid"
    )
    if not tags:
        tags.append("general")
    return {
        "tags": tags,
        "handles": handles,
        "cost_tier": cost_tier,
        "latency_tier": latency_tier,
        "context_k": 128,
    }


def promotion_suggestions(models: List[dict], slot_models: Dict[str, str],
                          provider_scores: Dict[str, dict],
                          threshold: float = DEGRADED_THRESHOLD) -> List[dict]:
    """Suggest (never force) a healthier slot model when its provider degrades.

    models: Registry.catalog()-shaped entries (id, owned_by, tier, handles).
    slot_models: {"helm": model_id, ...} - the CURRENT binding per slot.
    provider_scores: HealthTracker.provider_scores() output.

    Returns [{"slot", "current", "suggested", "reason"}] - empty when every
    slot's provider is healthy or unknown (no probes yet = no opinion).
    """
    out = []
    for slot in ("helm", "specialist", "scout"):
        current = slot_models.get(slot) or ""
        if not current:
            continue
        current_provider = next(
            (m.get("owned_by") for m in models if m.get("id") == current),
            None,
        )
        health = provider_scores.get(current_provider or "", {})
        score = health.get("score")
        if score is None or score >= threshold:
            continue
        candidates = [
            m for m in models
            if m.get("owned_by") != current_provider
            and (provider_scores.get(m.get("owned_by"), {}).get("score") or 0) >= threshold
        ]
        if not candidates:
            out.append({
                "slot": slot,
                "current": current,
                "suggested": None,
                "reason": (
                    f"{current_provider or 'current provider'} degraded "
                    f"(health {score}); no healthy alternative provider found"
                ),
            })
            continue
        best = max(
            candidates,
            key=lambda m: (
                provider_scores.get(m.get("owned_by"), {}).get("score") or 0,
                m.get("dna", {}).get("latency_tier") == "fast",
            ),
        )
        out.append({
            "slot": slot,
            "current": current,
            "suggested": best.get("id"),
            "reason": (
                f"{current_provider or 'current provider'} degraded "
                f"(health {score}); {best.get('owned_by')} is healthier "
                f"({provider_scores.get(best.get('owned_by'), {}).get('score')})"
            ),
        })
    return out


# --------------------------------------------------------------------------
# Module-level singletons (one per process; tests build their own).
# --------------------------------------------------------------------------
CONSTELLATIONS = Constellations()
HEALTH = HealthTracker()
BINDING_HISTORY = BindingHistory()
