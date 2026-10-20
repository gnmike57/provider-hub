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
    "request_headers",
    "FROST_ALIASES",
    "MAX_THINK_NAMES",
    "resolve_frost_alias",
    "HUB_PROVIDERS",
    "HUB_MODEL_ALIASES",
    "resolve_hub_alias",
    "hub_models_for_listing",
]

# --------------------------------------------------------------------------
# Frost names (2026-10-07): the operator's brand for the specialised
# speculative systems, addressable as model ids. Each name maps to the slot the
# gateway already has configured - "primary" = PRIMARY_API_URL/KEY (the Hive
# provider), "worker" = FALLBACK_API_URL/KEY (the gx10 hub specialist) - plus
# the exact upstream model id, so one endpoint can serve any of them.
# --------------------------------------------------------------------------
FROST_ALIASES = {
    # Plain Frost names (restored 2026-10-20): DeepFrost / GLMFrost live on
    # the PRIMARY slot (the Hive provider) with the exact upstream ids;
    # CyberFrost lives on the WORKER slot (the gx10 hub specialist). They were
    # dropped from the table when the max-think names were added, but the
    # published contract pins them: chat_proxy model addressing, /v1/models
    # discovery and /v1/switch slot-swaps all resolve through this table.
    "deepfrost v4.1": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost-v4.1": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost-v41": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "glmfrost 5.3 flash": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost-5.3-flash": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost5.3flash": ("primary", "zai-org/glm-5.3-flash"),
    "cyberfrost 3.8 sage": ("worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"),
    "cyberfrost-3.8-sage": ("worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"),
    "cyberfrost": ("worker", "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"),
    # Max-think variants (operator request, 2026-10): the SAME upstream models
    # with reasoning pushed to maximum - the gateway injects the knob set and
    # skips the hedge race (see proxy_gateway.wants_max_think / chat_proxy).
    "deepfrost max think": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "deepfrost-max-think": ("primary", "deepseek-ai/deepseek-v4.1-flash"),
    "glmfrost max think": ("primary", "zai-org/glm-5.3-flash"),
    "glmfrost-max-think": ("primary", "zai-org/glm-5.3-flash"),
    # Frost General: the primary slot's CURRENT default, not a baked-in id -
    # the literal name is not a real upstream id, so passing it through 400s
    # (measured live on Hive, "Invalid Model Name"). None = follow the slot
    # (and /v1/switch) at dispatch time.
    "frost-general": ("primary", None),
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


# --------------------------------------------------------------------------
# Hub model matrix (2026-10-18): operator-addressable model aliases that select
# a provider, an upstream model id, and a reasoning mode.
#
#   <Provider><Model><Reasoning>
#   Provider: nano        -> NanoGPT (NANOGPT_API_URL/KEY)
#             ablit.ai    -> Abliteration.ai (ABLITERATION_API_URL/KEY)
#   Model:    deep/glm name the matrix SLOT, resolved per provider (verified
#             against each live catalog, 2026-10-18):
#               nano     deep -> deepseek/deepseek-v4.1-flash (nano's own
#                                catalog id; Hive's deepseek-ai/ prefix is
#                                not carried there - measured live; a
#                                ":thinking" deployment variant also exists)
#               nano     glm  -> zai-org/glm-5.3-flash
#               ablit.ai deep -> abliterated-model-large (their catalog has no
#                                DeepSeek model; this is their other frontier
#                                reasoning model, prev-gen GLM-4 based)
#               ablit.ai glm  -> abliterated-model-large-v2 (GLM-5.3 based,
#                                confirmed by their pricing page and by the
#                                model's own self-report)
#   Reasoning: max        -> reasoning knobs pushed to maximum
#                       (absent)  -> normal reasoning
#
# Eight aliases: DeepMaxNano, GLMMaxNano, DeepNano, GLMNano,
#                DeepMaxAblit.ai, GLMMaxAblit.ai, DeepAblit.ai, GLMAblit.ai
# --------------------------------------------------------------------------

HUB_PROVIDERS = {
    "nano": {
        "url": os.getenv("NANOGPT_API_URL", "https://nano-gpt.com/api/v1/chat/completions"),
        "key": os.getenv("NANOGPT_API_KEY", ""),
    },
    "ablit.ai": {
        "url": os.getenv("ABLITERATION_API_URL", "https://api.abliteration.ai/v1/chat/completions"),
        "key": os.getenv("ABLITERATION_API_KEY", ""),
    },
}

# normalized alias -> (provider_key, upstream_model_id, max_reasoning)
HUB_MODEL_ALIASES = {
    "deepmaxnano": ("nano", "deepseek/deepseek-v4.1-flash", True),
    "glmmaxnano": ("nano", "zai-org/glm-5.3-flash", True),
    "deepnano": ("nano", "deepseek/deepseek-v4.1-flash", False),
    "glmnano": ("nano", "zai-org/glm-5.3-flash", False),
    "deepmaxablit.ai": ("ablit.ai", "abliterated-model-large", True),
    "glmmaxablit.ai": ("ablit.ai", "abliterated-model-large-v2", True),
    "deepablit.ai": ("ablit.ai", "abliterated-model-large", False),
    "glmablit.ai": ("ablit.ai", "abliterated-model-large-v2", False),
}

# Display names, DERIVED from HUB_MODEL_ALIASES (W5): the two tables used to
# be hand-maintained duplicates, and a new alias rendered the display table
# stale until someone remembered to update it too. The aliases have no word
# separators, so the display name is rebuilt token-wise from the known stems.
_HUB_DISPLAY_TOKENS = (
    # longest token first: "ablit.ai" must win over any future 1-char stem
    ("ablit.ai", "Ablit.ai"),
    ("deep", "Deep"),
    ("glm", "GLM"),
    ("max", "Max"),
    ("nano", "Nano"),
)


def _hub_display_name(alias: str) -> str:
    """`"deepmaxablit.ai"` -> `"DeepMaxAblit.ai"` (token-wise, no separators).

    An alias built from unknown stems keeps its remainder verbatim - deriving a
    display name must never crash the /v1/models listing.
    """
    out = []
    rest = str(alias or "")
    while rest:
        for token, display in _HUB_DISPLAY_TOKENS:
            if rest.startswith(token):
                out.append(display)
                rest = rest[len(token):]
                break
        else:  # unknown stem: keep the remainder verbatim
            out.append(rest)
            rest = ""
    return "".join(out)


# alias -> (display, upstream, provider_key, is_max) - single source of truth
# is HUB_MODEL_ALIASES; this view exists for hub_models_for_listing().
_HUB_DISPLAY = {
    alias: (_hub_display_name(alias), upstream, provider_key, is_max)
    for alias, (provider_key, upstream, is_max) in HUB_MODEL_ALIASES.items()
}


def _normalize_model_name(model: str) -> str:
    """Lowercase, replace hyphens/underscores with spaces, collapse whitespace."""
    return " ".join(str(model or "").strip().lower().replace("-", " ").replace("_", " ").split())


def resolve_hub_alias(model: str):
    """`"DeepMaxNano"` -> `("nano", "deepseek-ai/deepseek-v4.1-flash", True)`.

    Returns None for anything that is not a hub alias, so raw upstream ids and
    Frost names keep their existing behaviour.
    """
    if not model:
        return None
    key = _normalize_model_name(model)
    if key in HUB_MODEL_ALIASES:
        return HUB_MODEL_ALIASES[key]
    compact = key.replace(" ", "")
    if compact in HUB_MODEL_ALIASES:
        return HUB_MODEL_ALIASES[compact]
    return None


def hub_models_for_listing():
    """Hub model entries for the /v1/models endpoint."""
    out = []
    for alias, (display, upstream, provider_key, is_max) in _HUB_DISPLAY.items():
        provider = HUB_PROVIDERS[provider_key]
        out.append({
            "id": alias,
            "object": "model",
            "created": 1791338912,
            "owned_by": provider_key,
            "permission": [],
            "root": upstream,
            "parent": None,
            "description": display,
            "endpoint": provider["url"],
            "hedged": False,
            "type": "hub",
            "max_think": is_max,
            "reasoning": "max" if is_max else None,
        })
    return out


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

    # ---- provider management ----------------------------------------------
    def upsert_provider(
        self,
        pid: str,
        api: str,
        base_url: str,
        key: Optional[str] = None,
        models: Optional[Dict[str, str]] = None,
    ) -> None:
        """Create or replace provider `pid`; `key=None` keeps the stored key.

        When `pid` already exists and `models` is provided, the new model
        mappings are merged into the existing set (new keys overwrite old).
        Omitting `models` entirely leaves the existing model map untouched.
        """
        with self._lock:
            if pid in self.providers:
                existing = self.providers[pid]
                if key is None or key == "":
                    key = existing.key
                merged_models = dict(existing.models)
                if models:
                    merged_models.update(models)
            else:
                key = key or ""
                merged_models = dict(models or {})
            self.providers[pid] = Provider(
                id=pid,
                api=api,
                base_url=base_url,
                key=key,
                models=merged_models,
            )
        self.save()

    def delete_provider(self, pid: str) -> None:
        """Remove provider `pid` and prune any defaults pointing at it."""
        with self._lock:
            if pid not in self.providers:
                raise KeyError(f"provider {pid!r} not in registry")
            del self.providers[pid]
            # prune defaults that reference the removed provider
            for role in list(self.defaults):
                if self.defaults[role] == pid:
                    del self.defaults[role]
        self.save()

    def set_default(self, role: str, pid: str) -> None:
        """Set default provider for role (primary|worker); KeyError on unknown provider."""
        if role not in ("primary", "worker"):
            raise ValueError(f"invalid role {role!r}")
        with self._lock:
            if pid not in self.providers:
                raise KeyError(f"provider {pid!r} not in registry")
            self.defaults[role] = pid
        self.save()

    def catalog(self) -> List[Dict[str, object]]:
        """OpenAI-shaped model list entries from all registered providers.

        Includes `tier` (primary/worker) and `handles` (prompt class) fields
        per three-tier-routing-plan §64 for routing-topology discovery.
        """
        out = []
        for pid, p in self.providers.items():
            # Determine tier from the defaults mapping.
            tier = next(
                (role for role, default_pid in self.defaults.items() if default_pid == pid),
                "secondary",
            )
            for exposed, upstream in p.models.items():
                # Prompt-class hint based on model name patterns.
                if "max-think" in exposed.lower().replace(" ", "-"):
                    handles = "max-reasoning"
                elif "frost" in exposed.lower():
                    handles = "speculative"
                else:
                    handles = "general"
                out.append(
                    {
                        "id": exposed,
                        "object": "model",
                        "created": 0,
                        "owned_by": pid,
                        "tier": tier,
                        "handles": handles,
                    }
                )
        return out

    def masked(self) -> Dict[str, object]:
        """Return a serialization-safe view: keys masked, no raw secrets."""
        with self._lock:
            return {
                "providers": {
                    pid: {
                        "api": p.api,
                        "base_url": p.base_url,
                        "has_key": bool(p.key),
                        "models": dict(p.models),
                        "chat_url": p.base_url,
                    }
                    for pid, p in self.providers.items()
                },
                "defaults": dict(self.defaults),
                "from_env": self._mtime == 0.0,
            }


def load_registry(path: str = "") -> Registry:
    """Factory: build a Registry instance (default path = gateway_registry.json)."""
    return Registry(path or DEFAULT_PATH)
