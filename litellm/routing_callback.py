"""Non-streaming repair inside LiteLLM (RoutingFootnoteCallback).

Imports is_routable / footnote from routing_patterns (single source, F3) and
never re-declares ROUTING_RE - duplicated detection logic was the root cause
of defects B20/B21 and E1/E2/E3. litellm itself is imported lazily inside the
hook methods, so this module (and its tests) load without litellm installed.

Register with litellm (PYTHONPATH must include reference-implementation/):

    litellm_settings:
      callbacks: routing_callback.RoutingFootnoteCallback
"""

import os

from ingress_assembler import audit_record
from routing_patterns import footnote, is_routable

__all__ = ["RoutingFootnoteCallback"]


class RoutingFootnoteCallback:
    """Post-call hook: when a NON-STREAMING primary response is a refusal,
    append the provenance footnote and emit an audit line.

    Scope note: the actual divert lives in the streaming gateway
    (proxy_gateway.fallback_stream). Inside LiteLLM this hook guarantees
    disclosure + signal on the non-streaming paths; a full in-LiteLLM repair
    can be layered later by calling the specialist here.
    """

    def __init__(self, audit_log: str = None):
        self.audit_log = audit_log if audit_log is not None else (os.getenv("AUDIT_LOG") or "")
        self.model_label = os.getenv("LITELLM_ROUTING_FOOTNOTE_MODEL", "specialist")

    # -- testable core ------------------------------------------------------
    @staticmethod
    def _extract_text(response) -> str:
        try:
            return response.choices[0].message.content or ""
        except Exception:
            return ""

    def apply(self, response):
        """Detect + disclose. Returns (response, routed: bool). Never raises
        into the request path (design rule 7)."""
        try:
            text = self._extract_text(response)
            if not text or not is_routable(text):
                return response, False
            try:
                response.choices[0].message.content = text + footnote(self.model_label)
            except Exception:
                pass
            try:
                audit_record(
                    request_id="litellm-callback",
                    primary_model=getattr(response, "model", "") or "primary",
                    worker_model=self.model_label,
                    signal="tier3_refusal",
                    mode="litellm_post_call",
                    artifact="",
                    deliverable="",
                    audit_log=self.audit_log,
                )
            except Exception:
                pass
            return response, True
        except Exception:
            return response, False

    # -- litellm hook protocol (signatures vary across versions) ------------
    async def async_post_call_success_hook(self, *args, **kwargs):
        import litellm  # lazy: only needed when actually registered

        for arg in (args[1], kwargs.get("response")):
            if arg is not None and hasattr(arg, "choices"):
                self.apply(arg)
                break
        return args[1] if args and args[1] is not None and hasattr(args[1], "choices") else kwargs.get("response")

    def post_call_success_hook(self, *args, **kwargs):
        for arg in (args[1], kwargs.get("response")):
            if arg is not None and hasattr(arg, "choices"):
                self.apply(arg)
                break
        return args[1] if args and args[1] is not None and hasattr(args[1], "choices") else kwargs.get("response")
