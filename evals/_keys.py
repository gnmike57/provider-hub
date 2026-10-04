"""F25 key resolution: env -> secret file -> Cline config fallback (with warning).

The gateway itself only reads env vars; the TESTS may use this helper to pull
real keys from the operator's machine without hard-coding them.
"""

import json
import os
import sys
from pathlib import Path

__all__ = ["get_key", "warn"]


def warn(message: str) -> None:
    print(f"[keys] {message}", file=sys.stderr)


_CLINE_CONFIG_CANDIDATES = (
    os.path.expanduser("~/.cline/data/settings/cline_mcp_settings.json"),
    os.path.expanduser("~/AppData/Roaming/Cline/cline_mcp_settings.json"),
)


def _from_secret_file(path) -> str:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return ""
    # tolerate .env style lines:  KEY=value
    if "=" in text and "\n" in text:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == _LAST_REQUESTED[0]:
                return v.strip().strip('"')
        return text.splitlines()[0].strip()
    return text.splitlines()[0].strip()


def _from_cline_config(path) -> str:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    name = _LAST_REQUESTED[0]
    hits = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if name.lower() in str(k).lower() and isinstance(v, str) and v:
                    hits.append(v)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return hits[0] if hits else ""


# set by get_key() before reading files so the parsers know the key name
_LAST_REQUESTED = [""]


def get_key(env_var: str, *, secret_file=None, cline_config=None):
    """env -> secret file -> Cline config (with a warning on each fallback)."""
    _LAST_REQUESTED[0] = env_var

    value = os.environ.get(env_var, "")
    if value:
        return value

    if secret_file and os.path.isfile(secret_file):
        value = _from_secret_file(secret_file)
        if value:
            warn(f"{env_var} read from secret file {secret_file}")
            return value

    candidates = [cline_config] if cline_config else _CLINE_CONFIG_CANDIDATES
    for path in candidates:
        if path and os.path.isfile(path):
            value = _from_cline_config(path)
            if value:
                warn(f"{env_var} recovered from Cline config {path} (unofficial fallback)")
                return value

    warn(f"{env_var} not found in env, secret file, or Cline config")
    return ""
