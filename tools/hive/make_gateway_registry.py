"""Build gateway_registry.json: Hive models published as named API models.

The gateway resolves the client's `model` field through this registry
(providers.py), so a peer on the tailnet can call:

    model: "deepseek-4.1-flash"   -> hive: deepseek-ai/deepseek-v4.1-flash-1017
    model: "glm-5.3-flash"        -> hive: zai-org/glm-5.3-flash

The file holds deployment state, not source (gitignored).

S-B (2026-10-22): the Hive plaintext key is NO LONGER written here - the
hive provider is written with a BLANK key and providers.Registry resolves
it from the HIVE_SECRET_KEY env var at load time (process env, then the
persistent User/Machine scope). The file keeps only topology.
"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
UFO_ENV = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "gateway_registry.json"))

HIVE_BASE = "https://api-cdn.thehive.ai/api/v3"
HUB_BASE = "http://100.67.13.78:4000/v1"      # tailnet; works off-subnet


def key(name):
    for line in io.open(UFO_ENV, encoding="utf-8", errors="ignore").read().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{name} not found in {UFO_ENV}")


def hive_key_present():
    """The key is env-only now: report presence without ever embedding it."""
    if os.getenv("HIVE_SECRET_KEY"):
        return True
    try:  # ufo.env fallback = presence evidence only
        return bool(key("HIVE_SECRET_KEY"))
    except SystemExit:
        return False


doc = {
    "providers": {
        "hive": {
            "api": "openai",
            "base_url": HIVE_BASE,
            "key": "",  # S-B: env-only (HIVE_SECRET_KEY); Registry resolves it
            "models": {
                "deepseek-4.1-flash": "deepseek-ai/deepseek-v4.1-flash-1017",
                "glm-5.3-flash": "zai-org/glm-5.3-flash",
            },
        },
        "cyberhub": {
            "api": "openai",
            "base_url": HUB_BASE,
            "key": "none",
            "models": {},
        },
    },
    "defaults": {"primary": "hive", "worker": "cyberhub"},
}

io.open(OUT, "w", encoding="utf-8").write(json.dumps(doc, indent=2))
print(f"wrote {OUT}")
print("published models:", ", ".join(sorted(
    m for p in doc["providers"].values() for m in p["models"])))
print("hive key env-only (HIVE_SECRET_KEY present):", hive_key_present())
