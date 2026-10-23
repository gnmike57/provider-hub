"""Publish per-model gateway endpoints on the tailnet (one port per model).

Any peer on the tailnet can then call a "special endpoint" per model, with the
model field optional (the port already defaults it):

   9314  deepfrost max think -> Hive deepseek-ai/deepseek-v4.1-flash-1017 (no hedge)
   9315  glmfrost max think  -> Hive zai-org/glm-5.3-flash          (no hedge)
   9316  /team               -> the always-on team surface (V2 Large terminal)
   9310  (general)           -> any id in the body; hedge worker = Ablit V2 Large

All of them accept any model id in the body as an override, and `"hedge": true`
forces the speculative dual-dispatch. Secrets stay in ufo.env; never printed.

CYBER-FROST IS DELETED (2026-10-23): the local weights and their TabbyAPI
server are gone, so the divert/fallback target is the uncensored Abliteration
LARGE V2 brain (abliterated-model-large-v2) with its key BUILT IN
(ABLITERATION_API_KEY - proxy_gateway._specialist_key resolves it last).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Shared core (task 0007 extraction): the launch/env/secret logic lives in
# serve_module.py; this file keeps the per-host constants + the INSTANCES
# table. No-flag invocations behave exactly as before the extraction.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import serve_module  # noqa: E402  (path bootstrap above)
from serve_module import serve_all  # noqa: E402  (path bootstrap above)

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
UFO_ENV = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"

HIVE_URL = "https://api-cdn.thehive.ai/api/v3/chat/completions"
HUB_URL = "http://100.67.13.78:4000/v1/chat/completions"
# Divert target (CYBER-FROST deleted 2026-10-23): the uncensored TERMINAL - the
# Abliteration LARGE V2 brain, reachable through the built-in
# ABLITERATION_API_KEY (see proxy_gateway._specialist_key).
SPECIALIST = "abliterated-model-large-v2"

INSTANCES = [
    # Max-think ports default the max-think NAME (not the raw upstream id):
    # the gateway recognises it and injects the reasoning knobs itself. The
    # race is disabled at the env layer too (COMMIT_TOKENS=100000) - the
    # gateway already skips hedging for max-think names, this keeps the
    # process honest if the name is ever overridden in a request body.
    serve_module.EndpointConfig("deepfrost max think", 9314, HIVE_URL,
                                "deepfrost max think", False),
    serve_module.EndpointConfig("glmfrost max think", 9315, HIVE_URL,
                                "glmfrost max think", False),
    serve_module.EndpointConfig("team (always-on)", 9316, HIVE_URL,
                                "team", False),
    serve_module.EndpointConfig("general (any name / raw id)", 9310, HIVE_URL,
                                "deepseek-ai/deepseek-v4.1-flash-1017", True),
]

# NOTE: 9301 is owned by the ufo bridge (uvicorn fails to bind with winerror
# 10048 and the endpoint silently does not exist) - never publish there.

_DISPLAY_HOST = "100.113.176.84"
_HEADER = f"provider-hub endpoints (0.0.0.0, tailnet {_DISPLAY_HOST}):"


def key(name):
    """Legacy single-name reader (kept for existing importers).

    Env-first via serve_module.resolve_secret; falls back to this host's
    plaintext ufo.env (with the loud legacy-fallback warning); SystemExit with
    the same message shape when the key is nowhere.
    """
    values = serve_module.parse_ufo_env(UFO_ENV)
    value, _source = serve_module.resolve_secret(
        name, values, UFO_ENV if name == serve_module.SECRET_NAME else "n/a")
    if value is None:
        raise SystemExit(f"{name} not found in {UFO_ENV}")
    return value


def launch(name, port, primary_url, model, hedged):
    """Backward-compatible wrapper: the copies' positional launch signature.

    Builds an EndpointConfig (bind/dry_run from the current plan state) and
    delegates to serve_module.launch. Pre-extraction callers that unpacked the
    INSTANCES 5-tuples keep working unchanged.
    """
    cfg = serve_module.EndpointConfig(name, port, primary_url, model, hedged)
    return serve_module.launch(
        cfg, ufo_env=UFO_ENV, root=ROOT, display_host=_DISPLAY_HOST,
        fallback_url=HUB_URL, fallback_model=SPECIALIST)


if __name__ == "__main__":
    raise SystemExit(serve_all(
        sys.argv[1:], instances=INSTANCES, ufo_env=UFO_ENV, root=ROOT,
        header=_HEADER, display_host=_DISPLAY_HOST, fallback_url=HUB_URL,
        fallback_model=SPECIALIST))

