"""Build gateway_registry.json: Hive models published as named API models.

The gateway resolves the client's `model` field through this registry
(providers.py), so a peer on the tailnet can call:

    model: "deepseek-4.1-flash"   -> hive: deepseek-ai/deepseek-v4.1-flash
    model: "glm-5.3-flash"        -> hive: zai-org/glm-5.3-flash

The file holds a live key, so it is gitignored (deployment state, not source).
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


doc = {
    "providers": {
        "hive": {
            "api": "openai",
            "base_url": HIVE_BASE,
            "key": key("HIVE_SECRET_KEY"),
            "models": {
                "deepseek-4.1-flash": "deepseek-ai/deepseek-v4.1-flash",
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
print("key present:", bool(doc["providers"]["hive"]["key"]))
