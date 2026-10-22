"""GX10 OFFLOAD - the hub's instinct to hand work to the free local box.

Operator directive (2026-10-23): "ingrain as a function of ANY of the
models in the hub to always seek to offload work or tasks to gx10 anywhere
anytime it's beneficial." The gx10 (DGX Spark) local hub on :4000 serves
FREE local models (qwen3-coder-480b, kimi-k3, glm-5.3-flash,
deepseek-v4-pro, gemma3-27b-heretic-vl, ...) - no Hive spend, no
Abliteration spend, LAN latency.

LAWS (pinned by evals/gx10_offload_test.py):
  * BENEFICIAL ONLY: no tools (tool plumbing stays on the paid path), a
    SIMPLE ask (routing_patterns.is_multi_item_ask < 2 - decomposition would
    help a complex one), not a REDHANDS/sustained chain (their own
    machinery decides), and the knob on (GX10_OFFLOAD, default 1).
  * HEALTH-GATED + COOLDOWN: a cached /v1/models probe (max one per
    GX10_HEALTH_CACHE_S, default 30s); a failure cools the offload off for
    GX10_OFFLOAD_COOLDOWN_S (default 30s) so a dead box is never hammered.
  * BOUNDED: ONE non-streaming call, GX10_OFFLOAD_MAX_TOKENS
    (default 1024), short connect timeout.
  * CLEAN + SUBSTANTIVE: the answer passes the is_routable refusal screen
    and the min-substantive-chars bar; anything less falls through.
  * FAIL-OPEN, NEVER RAISES: try_offload returns the (text, model) or
    None - the normal path answers instead. The offload can only SAVE
    money, never hurt a request.

Env knobs: GX10_OFFLOAD (1), GX10_URL, GX10_MODELS_URL,
GX10_OFFLOAD_MODEL (glm-5.3-flash), GX10_OFFLOAD_MAX_TOKENS (1024),
GX10_HEALTH_CACHE_S (30), GX10_OFFLOAD_COOLDOWN_S (30).
"""
import os
import time

import httpx

from routing_patterns import is_multi_item_ask, is_routable

__all__ = ["eligible", "try_offload", "healthy", "reset", "url",
           "models_url", "model"]

DEFAULT_URL = "http://100.67.13.78:4000/v1/chat/completions"
DEFAULT_MODELS_URL = "http://100.67.13.78:4000/v1/models"

# process-wide health cache: {"ok": bool, "checked": ts, "fail_until": ts}
_health = {"ok": False, "checked": 0.0, "fail_until": 0.0}


def reset():
    """Test hermeticity: clear the health cache + cooldown."""
    _health.update({"ok": False, "checked": 0.0, "fail_until": 0.0})


def _env(name, default):
    return (os.getenv(name, "") or default).strip()


def url():
    return _env("GX10_URL", DEFAULT_URL)


def models_url():
    return _env("GX10_MODELS_URL", DEFAULT_MODELS_URL)


def model():
    return _env("GX10_OFFLOAD_MODEL", "glm-5.3-flash")


def enabled():
    try:
        return int(os.getenv("GX10_OFFLOAD", "1") or 1) != 0
    except (TypeError, ValueError):
        return True


def max_tokens():
    try:
        return max(64, int(os.getenv("GX10_OFFLOAD_MAX_TOKENS", "1024") or 1024))
    except (TypeError, ValueError):
        return 1024


def _cache_s():
    try:
        return max(1.0, float(os.getenv("GX10_HEALTH_CACHE_S", "30") or 30))
    except (TypeError, ValueError):
        return 30.0


def _cooldown_s():
    try:
        return max(0.0, float(os.getenv("GX10_OFFLOAD_COOLDOWN_S", "30") or 30))
    except (TypeError, ValueError):
        return 30.0


def eligible(body, chain, user_query):
    """Beneficial-only gate (the caller supplies the last user text)."""
    if not enabled():
        return False
    if body.get("tools"):
        return False
    if chain and (chain.get("sustained") or chain.get("redhands")):
        return False  # their own pre-probe/brain decides
    try:
        return is_multi_item_ask(user_query or "") < 2
    except Exception:  # noqa: BLE001 - never block the request path
        return False


async def healthy(client) -> bool:
    """Cached box health; cooldown after a failure (never hammer a dead box)."""
    now = time.time()
    if now < _health["fail_until"]:
        return False
    if _health["ok"] and (now - _health["checked"]) < _cache_s():
        return True
    try:
        resp = await client.get(models_url(), timeout=httpx.Timeout(3.0, read=5.0))
        ok = resp.status_code < 500
    except Exception:  # noqa: BLE001
        ok = False
    _health["ok"] = ok
    _health["checked"] = now
    if not ok:
        _health["fail_until"] = now + _cooldown_s()
    return ok


async def try_offload(messages, *, settings=None, client=None):
    """ONE bounded attempt at the free box. Returns (text, model) or None.
    NEVER raises; every doubt falls through to the normal path."""
    if client is None or not messages:
        return None
    if not await healthy(client):
        return None
    payload = {
        "model": model(),
        "messages": list(messages),
        "stream": False,
        "max_tokens": max_tokens(),
    }
    try:
        resp = await client.post(
            url(), json=payload,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(5.0, read=90.0))
    except Exception:  # noqa: BLE001 - fail open
        _health["fail_until"] = time.time() + _cooldown_s()
        return None
    if resp.status_code >= 400:
        return None  # answer shape wrong for the box; not a health signal
    try:
        text = str((((resp.json().get("choices") or [{}])[0]
                     .get("message") or {}).get("content")) or "").strip()
    except Exception:  # noqa: BLE001
        return None
    min_subst = max(1, int(getattr(settings, "min_substantive_chars", 20) or 20))
    if not text or is_routable(text) or len(text) < min_subst:
        return None
    # protocol markers NEVER ship to the client (live 2026-10-23 finding:
    # the box's glm followed the injected [[GW-CHECKLIST]] contract and echoed
    # the marker back; the paid paths strip these - the offload must too).
    import re as _re
    text = _re.sub(r"\[\[GW-[A-Z-]+\]\]", "", text).strip()
    if not text or len(text) < min_subst:
        return None
    return text, model()
