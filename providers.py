"""Dynamic provider registry + wire adapters for the interception gateway.

Makes POST /v1/chat/completions provider-agnostic: the client's `model` field
selects among registered providers (Anthropic, OpenAI, xAI/Grok, the local
hub, ...) via this resolution order:

  1. explicit "provider_id:model" (e.g. "anthropic:claude-sonnet-4-5")
  2. a model name registered by exactly one provider
  3. the registry default primary

Back-compat: with no registry file, an implicit registry is synthesised from
the legacy env surface (PRIMARY_* / FALLBACK_*), so existing deployments keep
working unchanged.

Two wire APIs are supported:
  - "openai"     - chat/completions passthrough (covers OpenAI, xAI, Grok,
                   OpenRouter, the llama hub, ...)
  - "anthropic"  - /v1/messages: request transform (system hoist, tools ->
                   input_schema, mandatory max_tokens) and SSE translation
                   (content_block_delta/input_json_delta/stop_reason ...) into
                   the gateway's canonical Event stream.

Keys persist in the registry JSON (env GATEWAY_REGISTRY, default
gateway_registry.json beside this module). Keys are masked in every read-back
(mask_key); a blank key on update keeps the stored one.
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, List, Optional, Tuple

__all__ = [
    "Event",
    "Target",
    "Provider",
    "Registry",
    "load_registry",
    "mask_key",
    "build_upstream_request",
    "request_headers",
    "normalize_stream",
    "to_openai_chunk",
    "openai_anthropic_messages",
    "anthropic_finish_reason",
    "FROST_ALIASES",
    "MAX_THINK_NAMES",
    "resolve_frost_alias",
]

# --------------------------------------------------------------------------
# Frost names (2026-10-07): the operator's brand for the specialised
# speculative systems, addressable as model ids. Each name maps to the slot the
# gateway already has configured - "primary" = PRIMARY_API_URL/KEY (the Hive
# provider), "worker" = FALLBACK_API_URL/KEY (the gx10 hub specialist) - plus
# the exact upstream model id, so one endpoint can serve any of them.
# --------------------------------------------------------------------------
FROST_ALIASES = {
    "deepfrost v4.1": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost-v4.1": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost-v41": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    # Max-think variants (operator request, 2026-10): the SAME upstream models
    # with reasoning pushed to maximum - the gateway injects the knob set and
    # skips the hedge race (see proxy_gateway.wants_max_think / chat_proxy).
    "deepfrost max think": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost-max-think": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "glmfrost 5.3 flash": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost-5.3-flash": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost5.3flash": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost max think": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost-max-think": ("primary", "zai-org/glm-5.3-flash"),
    "cyberfrost 3.8 sage": ("worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"),
    "cyberfrost-3.8-sage": ("worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"),
    "cyberfrost": ("worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"),
}

# The max-think subset of the Frost names (operator request, 2026-10): the SAME
# upstream models addressed through names that demand extra-hard reasoning. Kept
# here, beside FROST_ALIASES, as the single source of truth for the alias data;
# proxy_gateway imports it and injects the reasoning knobs server-side.
MAX_THINK_NAMES = frozenset({
    "deepfrost max think", "deepfrost-max-think",
    "glmfrost max think", "glmfrost-max-think",
})


def resolve_frost_alias(model: str):
    """`"DeepFrost v4.1"` -> `("primary", "deepseek-ai/deepseek-v4.1-flash")`.

    Returns None for anything that is not a Frost name, so raw upstream ids and
    every other model keep their existing behaviour.
    """
    if not model:
        return None
    key = " ".join(str(model).strip().lower().replace("_", " ").split())
    if key in FROST_ALIASES:
        return FROST_ALIASES[key]
    return FROST_ALIASES.get(key.replace(" ", "-"))


ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_MAX_TOKENS = 4096


# --------------------------------------------------------------------------
# Canonical stream events (adapter output; gateway/hedge input).
# --------------------------------------------------------------------------
@dataclass
class Event:
    """One normalised upstream event.

    kind:
      content   - visible token (counts toward commit/refusal screens)
      reasoning - thinking delta (forwarded live, never screened)
      tool_call - tool_call delta: index set; id/name on first, args after
      finish    - terminal: finish set to an OpenAI finish_reason string
      usage     - usage dict (prompt/completion token counts)
      error     - upstream error: error carries the message
    """

    kind: str
    text: str = ""
    index: int = 0
    tool_id: str = ""
    name: str = ""
    args: str = ""
    finish: Optional[str] = None
    usage: Optional[dict] = None
    error: str = ""


# --------------------------------------------------------------------------
# Provider + resolved target.
# --------------------------------------------------------------------------
@dataclass
class Provider:
    id: str
    api: str  # "openai" | "anthropic"
    base_url: str  # .../v1 for openai, root for anthropic (no /v1/messages suffix)
    key: str = ""
    # exposed_name -> upstream model id (usually identical; lets a user expose
    # "claude-fast" -> "claude-haiku-4-5" etc.)
    models: Dict[str, str] = field(default_factory=dict)

    def chat_url(self) -> str:
        root = self.base_url.rstrip("/")
        if self.api == "anthropic":
            return root + "/v1/messages"
        return root + "/chat/completions"

    def models_url(self) -> str:
        root = self.base_url.rstrip("/")
        if self.api == "anthropic":
            return root + "/v1/models"
        return root + "/models"


@dataclass
class Target:
    """A provider + chosen model, resolved for one request."""

    provider: Provider
    exposed_model: str
    upstream_model: str
    via: str  # how it was resolved: "explicit" | "named" | "default"


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "********"
    return key[:4] + "..." + key[-4:]


def request_headers(target: Target, client_key: str = "") -> dict:
    """Auth headers for the resolved provider. The provider's stored key wins;
    with none configured, a client-supplied bearer is forwarded (BYOK)."""
    p = target.provider
    key = p.key or client_key
    if p.api == "anthropic":
        headers = {"anthropic-version": ANTHROPIC_VERSION}
        if key:
            headers["x-api-key"] = key
        return headers
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


# --------------------------------------------------------------------------
# Registry: load/save/resolve. JSON on disk; mtime reload so admin-UI writes
# are picked up without a restart.
# --------------------------------------------------------------------------
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gateway_registry.json")


def _strip_chat_suffix(url: str) -> str:
    """Accept either a base (.../v1) or a full endpoint (.../v1/chat/completions)."""
    url = url.rstrip("/")
    for suffix in ("/chat/completions", "/messages"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def _legacy_env_providers() -> Tuple[Dict[str, Provider], Dict[str, str]]:
    """Synthesise the implicit registry from the legacy env surface."""
    pmodel = os.getenv("PRIMARY_MODEL", "gpt-4o")
    wmodel = os.getenv("FALLBACK_MODEL", "Qwen3.6-35B-A3B-abliterated-NVFP4-MTP")
    primary = Provider(
        id="env-primary", api="openai",
        base_url=_strip_chat_suffix(os.getenv("PRIMARY_API_URL", "https://api.openai.com/v1/chat/completions")),
        key=os.getenv("PRIMARY_API_KEY", ""),
        models={pmodel: pmodel},
    )
    worker = Provider(
        id="env-worker", api="openai",
        base_url=_strip_chat_suffix(os.getenv("FALLBACK_API_URL", "http://127.0.0.1:8000/v1/chat/completions")),
        key=os.getenv("FALLBACK_API_KEY", "none"),
        models=({wmodel: wmodel} if wmodel else {}),
    )
    return {"env-primary": primary, "env-worker": worker}, {"primary": "env-primary", "worker": "env-worker"}


class Registry:
    """Thread-safe view over gateway_registry.json (or the env fallback)."""

    def __init__(self, path: str = ""):
        self.path = path or os.getenv("GATEWAY_REGISTRY", "") or DEFAULT_PATH
        self._lock = threading.Lock()
        self._mtime = 0.0
        self.providers: Dict[str, Provider] = {}
        self.defaults: Dict[str, str] = {}
        self.reload(force=True)

    # ---- persistence ------------------------------------------------------
    def reload(self, force: bool = False):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = 0.0
        with self._lock:
            if not force and mtime and mtime == self._mtime:
                return
            if mtime:
                try:
                    with open(self.path, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    providers = {
                        pid: Provider(
                            id=pid,
                            api=p.get("api", "openai"),
                            base_url=p["base_url"],
                            key=p.get("key", ""),
                            models=dict(p.get("models") or {}),
                        )
                        for pid, p in (raw.get("providers") or {}).items()
                    }
                    defaults = dict(raw.get("defaults") or {})
                    if providers:
                        self.providers, self.defaults = providers, defaults
                        self._mtime = mtime
                        return
                except (OSError, json.JSONDecodeError, KeyError):
                    pass  # fall through to env back-compat
            self.providers, self.defaults = _legacy_env_providers()
            self._mtime = 0.0

    def save(self):
        """Atomic write: temp file + replace."""
        data = {
            "providers": {
                pid: {"api": p.api, "base_url": p.base_url, "key": p.key, "models": p.models}
                for pid, p in self.providers.items()
            },
            "defaults": self.defaults,
        }
        tmp = self.path + ".tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
