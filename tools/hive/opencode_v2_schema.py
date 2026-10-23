"""Rewrite ~/.config/opencode/opencode.json in opencode v2's OWN schema.

opencode 2.0.24 silently drops v1 keys ("kind=unsupported ... legacy setting")
and does not resolve custom providers written in the old `provider`/`npm`/
`options` shape - it failed even for the pre-existing 111-gx10 provider. The
shape below is taken verbatim from `opencode debug config` (its normalized
output): `providers` (plural), `package: aisdk:@ai-sdk/openai-compatible`,
`settings`, and a `model` object {providerID, model}.
"""
import io
import json
import os
import sys

CONFIG = os.path.expanduser(r"~\.config\opencode\opencode.json")
BASE = "https://api-cdn.thehive.ai/api/v3"


def main(secret):
    with io.open(CONFIG, encoding="utf-8") as fh:
        old = json.load(fh)
    # Featherless cloud aliases dropped 2026-10-23 (stale key, not to be
    # enabled). `cyberfrost` is the constellation's uncensored terminal on
    # Abliteration.ai (abliterated-model-large-v2); the :4000 gx10 llm-hub is a
    # legacy catalog, not the hub.
    local = [
        ("ablit", "Abliteration.ai (uncensored terminal)", "https://api.abliteration.ai/v1",
         "sk-local", ["abliterated-model-large-v2", "cyberfrost"]),
        ("cyberhub", "cyber.local (legacy gx10 llm-hub catalog)",
         "http://cyber.local:4000/v1", "sk-local",
         ["deepseek-ai/deepseek-v4.1-flash-1017", "glm-5.3-flash"]),
        ("gx10", "local LiteLLM gateway (127.0.0.1:4000)", "http://127.0.0.1:4000/v1", "sk-local",
         ["ufo-host-model", "ufo-vision-model"]),
        ("111-gx10", "111-gx10 brain (DGX Spark @ cyber.local:8015)", "http://cyber.local:8015/v1",
         "sk-local", ["qwen2.5-72b-abliterated"]),
        ("hive", "Hive (thehive.ai)", BASE, secret,
         ["deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash"]),
    ]
    providers = {}
    for pid, name, url, key, models in local:
        providers[pid] = {
            "name": name,
            "package": "aisdk:@ai-sdk/openai-compatible",
            "settings": {"baseURL": url, "apiKey": key, "timeout": 600000,
                         "chunkTimeout": 180000},
            "models": {m: {"name": m} for m in models},
        }
    providers["hive"]["models"]["deepseek-ai/deepseek-v4.1-flash-1017"]["name"] = \
        "DeepSeek 4.1 Flash 1017 (1M ctx, vision, tools)"
    providers["hive"]["models"]["zai-org/glm-5.3-flash"]["name"] = \
        "GLM 5.3 Flash (1M ctx, vision/video, tools)"

    doc = {
        "$schema": "https://opencode.ai/config.json",
        "model": {"providerID": "hive", "model": "deepseek-ai/deepseek-v4.1-flash-1017"},
        "small_model": {"providerID": "hive", "model": "zai-org/glm-5.3-flash"},
        "providers": providers,
    }
    with io.open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    print("providers written:", sorted(providers))
    print("default model:", doc["model"])


if __name__ == "__main__":
    env_file = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"
    env = {}
    for line in io.open(env_file, encoding="utf-8", errors="ignore").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    main(env["HIVE_SECRET_KEY"])
