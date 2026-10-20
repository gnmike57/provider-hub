"""
vision_bridge.py - the modality bridge of the tars-hybrid-router.

Operator directive: "V2 LARGE MODEL FOR ALL". abliterated-model-large-v2 is
text-only (rejects image content with HTTP 400 on api.abliteration.ai), but
UI-TARS Desktop and hybrid-mode Agent TARS send base64 screenshots on every
step. This LiteLLM proxy callback (async_pre_call_hook) rewrites image parts
into structured text captions BEFORE the request leaves the gx10, so the
text-only flagship can drive vision clients:

    screenshot -> [vision sensor captions it] -> structured text -> V2 large

The vision sensor is NOT the brain. Sensor chain (first success wins):
  1. local:  gemma3-27b-heretic-vl on the gx10 llm-hub (127.0.0.1:4000,
             no auth - keeps ALL Abliteration.ai spend on V2 large)
  2. remote: abliterated-model on api.abliteration.ai (same key; only used
             if the local sensor is down)

Registered from litellm_config.yaml (LiteLLM 1.106+ wants an instance):
    litellm_settings:
      callbacks:
        - vision_bridge.proxy_handler_instance
loaded because systemd sets PYTHONPATH=/home/nick/tars-litellm-router.

All knobs are environment variables (see router.env) - no code edits needed.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:  # pragma: no cover - litellm[proxy] always brings httpx
    httpx = None  # type: ignore


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "off", "no")


# --------------------------------------------------------------------------
# Configuration (env-driven; defaults match the gx10 deployment)
# --------------------------------------------------------------------------
BRIDGE_ENABLED = _flag("VISION_BRIDGE", "1")
# Models whose requests get bridged. Anything else (e.g. the multimodal
# abliterated-model passthrough) sees images raw.
BRIDGED_MODELS = {
    m.strip()
    for m in os.getenv(
        "BRIDGE_BRIDGED_MODELS", "abliterated-model-large-v2,tars-hybrid"
    ).split(",")
    if m.strip()
}
BRIDGE_ALL_MODELS = _flag("BRIDGE_ALL_MODELS", "0")

LOCAL_CAPTIONER_URL = os.getenv(
    "CAPTIONER_LOCAL_URL", "http://127.0.0.1:4000/v1/chat/completions"
)
LOCAL_CAPTIONER_MODEL = os.getenv("CAPTIONER_LOCAL_MODEL", "gemma3-27b-heretic-vl")
LOCAL_CAPTIONER_KEY = os.getenv("CAPTIONER_LOCAL_KEY", "")  # llm-hub: no auth

REMOTE_CAPTIONER_URL = os.getenv(
    "CAPTIONER_REMOTE_URL", "https://api.abliteration.ai/v1/chat/completions"
)
REMOTE_CAPTIONER_MODEL = os.getenv("CAPTIONER_REMOTE_MODEL", "abliterated-model")
REMOTE_CAPTIONER_KEY = os.getenv("ABLITERATION_API_KEY", "")

CAPTIONER_TIMEOUT = float(os.getenv("CAPTIONER_TIMEOUT", "120"))
CAPTIONER_MAX_TOKENS = int(os.getenv("CAPTIONER_MAX_TOKENS", "900"))
MAX_IMAGES_PER_REQUEST = int(os.getenv("BRIDGE_MAX_IMAGES", "24"))
LOG_BRIDGE = _flag("BRIDGE_LOG", "1")

# --------------------------------------------------------------------------
# Caption prompt: the sensor must be precise enough for a text-only
# controller to click. Normalized 0-1000 coordinates match UI-TARS Desktop.
# --------------------------------------------------------------------------
CAPTION_PROMPT = (
    "You are the vision sensor of a GUI automation agent. The controller that "
    "acts on your description is TEXT-ONLY, so be exact and structured.\n"
    "Describe the screenshot as:\n"
    "PAGE: one line - what the screen/page is, plus any visible URL, tab or "
    "window title.\n"
    "ELEMENTS: one line per visible interactive element, exactly:\n"
    "  [type] 'label or placeholder' center=(x,y)\n"
    "where type is one of button|link|input|textarea|checkbox|radio|select|"
    "tab|menuitem|icon|other and (x,y) is the element center normalized to "
    "0-1000 across the image width and height (x=0 left edge, y=0 top edge). "
    "For inputs include the current value as 'label=<value>'. Include login "
    "forms, search bars and dialogs.\n"
    "FOCUS: the focused/active element if identifiable, else 'unknown'.\n"
    "TEXT: terse list of other important visible text (headings, messages, "
    "errors).\n"
    "No prose. No markdown. Coordinates must be numbers 0-1000."
)


def _log(msg: str) -> None:
    if LOG_BRIDGE:
        print(f"[vision-bridge {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------
# Image-part detection across OpenAI chat / responses / Anthropic shapes
# --------------------------------------------------------------------------
def _image_url_from(part: Any) -> Optional[str]:
    """Extract an image URL (usually a data: URL) from a content part, or
    None if the part is not an image. Handles the shapes in the wild."""
    if not isinstance(part, dict):
        return None
    ptype = str(part.get("type", "")).lower()
    if ptype in ("image_url", "input_image"):
        iu = part.get("image_url")
        if isinstance(iu, dict) and iu.get("url"):
            return str(iu["url"])
        if isinstance(iu, str) and iu:
            return iu
        if part.get("url"):
            return str(part["url"])
        return None
    if ptype == "image":  # Anthropic messages shape
        src = part.get("source") or {}
        if isinstance(src, dict) and src.get("type") == "base64":
            media = src.get("media_type", "image/png")
            return f"data:{media};base64,{src.get('data', '')}"
        if isinstance(src, dict) and src.get("type") == "url":
            return str(src.get("url", ""))
    return None


def _has_image(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(_image_url_from(p) is not None for p in content)


# --------------------------------------------------------------------------
# Captioner chain: local sensor first, remote fallback second
# --------------------------------------------------------------------------
def _captioner_chain() -> List[Tuple[str, str, str, str]]:
    chain: List[Tuple[str, str, str, str]] = []
    if _flag("CAPTIONER_LOCAL_ENABLED", "1") and LOCAL_CAPTIONER_URL:
        chain.append(
            ("local-hub", LOCAL_CAPTIONER_URL, LOCAL_CAPTIONER_MODEL, LOCAL_CAPTIONER_KEY)
        )
    if _flag("CAPTIONER_REMOTE_ENABLED", "1") and REMOTE_CAPTIONER_URL:
        chain.append(
            (
                "abliteration-remote",
                REMOTE_CAPTIONER_URL,
                REMOTE_CAPTIONER_MODEL,
                REMOTE_CAPTIONER_KEY,
            )
        )
    return chain


async def _caption_once(url: str, model: str, key: str, image_url: str) -> str:
    assert httpx is not None, "httpx missing - reinstall litellm[proxy]"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": CAPTION_PROMPT},
                ],
            }
        ],
        "max_tokens": CAPTIONER_MAX_TOKENS,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=CAPTIONER_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    choices = payload.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    caption = ""
    for field in ("content", "reasoning"):
        c = message.get(field)
        if isinstance(c, list):  # some servers return content-part lists
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        if c:
            caption = str(c).strip()
            if caption:
                break
    if not caption:
        raise RuntimeError(f"empty caption from {model}")
    return caption


async def caption_image(image_url: str) -> str:
    """Caption one image via the first healthy sensor in the chain."""
    errors: List[str] = []
    for name, endpoint, model, key in _captioner_chain():
        try:
            caption = await _caption_once(endpoint, model, key, image_url)
            _log(f"captioned image via {name} sensor ({model})")
            return caption
        except Exception as exc:  # noqa: BLE001 - chain must keep trying
            errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:160]}")
            _log(f"sensor {name} failed: {errors[-1]}")
    return (
        "[SCREENSHOT unavailable - all vision sensors failed: "
        + "; ".join(errors)[:400]
        + " - act on the text context only]"
    )

# --------------------------------------------------------------------------
# The LiteLLM proxy callback
# --------------------------------------------------------------------------
try:
    from litellm.integrations.custom_logger import CustomLogger

    _CallbackBase = CustomLogger
except Exception:  # pragma: no cover - standalone import (tests, lint)
    _CallbackBase = object


class VisionBridgeCallback(_CallbackBase):
    """LiteLLM proxy callback. `async_pre_call_hook` fires before every
    proxied call; the signature drifted across LiteLLM versions (older:
    (user, debug, data, call_type); newer: (user_api_key_dict, data,
    call_type)), so we normalize defensively and only ever mutate `data`."""

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _extract(args, kwargs):
        data = kwargs.get("data")
        call_type = kwargs.get("call_type") or kwargs.get("type")
        if data is None:
            for a in args:
                if isinstance(a, dict):
                    data = a
                    break
        if call_type is None:
            for a in args:
                if isinstance(a, str):
                    call_type = a
        return data, call_type

    def _should_bridge(self, data: Dict[str, Any]) -> bool:
        if not BRIDGE_ENABLED:
            return False
        if BRIDGE_ALL_MODELS:
            return True
        model = str(data.get("model", ""))
        return model in BRIDGED_MODELS or "large-v2" in model

    # ---- the hook ---------------------------------------------------------
    async def async_pre_call_hook(self, *args: Any, **kwargs: Any):
        data, call_type = self._extract(args, kwargs)
        if not isinstance(data, dict):
            return data
        if not self._should_bridge(data):
            return data

        # Both /v1/chat/completions ("messages") and bridged /v1/responses
        # ("input" as a list of {role, content} items) carry content lists.
        if isinstance(data.get("messages"), list):
            targets: List[Any] = data["messages"]
        elif isinstance(data.get("input"), list):
            targets = data["input"]
        else:
            return data

        counter = 0
        msgs_touched = 0
        for item in targets:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not _has_image(content):
                continue
            msgs_touched += 1
            new_content: List[Any] = []
            for part in content:
                image_url = _image_url_from(part)
                if image_url is None:
                    new_content.append(part)
                    continue
                counter += 1
                if counter > MAX_IMAGES_PER_REQUEST:
                    new_content.append(
                        {"type": "text", "text": "[SCREENSHOT dropped: image limit reached]"}
                    )
                    continue
                caption = await caption_image(image_url)
                new_content.append(
                    {
                        "type": "text",
                        "text": (
                            f"[SCREENSHOT {counter} - structured caption from the vision "
                            f"sensor (the controller model is text-only); element "
                            f"coordinates are 0-1000 normalized]\n{caption}"
                        ),
                    }
                )
            item["content"] = new_content

        if msgs_touched:
            _log(
                f"bridged {msgs_touched} image-bearing message(s), "
                f"{counter} caption(s), model={data.get('model')} "
                f"call_type={call_type}"
            )
        return data


# LiteLLM 1.106+ requires litellm_settings.callbacks to point at an INSTANCE
# (a bare class raises "neither a CustomLogger instance nor a callable"):
#   litellm_settings:
#     callbacks:
#       - vision_bridge.proxy_handler_instance
proxy_handler_instance = VisionBridgeCallback()

