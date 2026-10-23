"""Wire the corrected Hive provider into both agent harnesses (2026-10-07).

Verified recipe: base https://api-cdn.thehive.ai/api/v3 (+ /chat/completions),
auth Bearer <HIVE_SECRET_KEY> (SECRET key), models deepseek-ai/deepseek-v4.1-flash-1017
and zai-org/glm-5.3-flash. The Hive catalog (2026-10-21) lists only the
deepseek-ai/deepseek-v4.1-flash-1017 deployment - the plain id is gone.

- Cline CLI  : ~/.cline/data/settings/providers.json  (restore the local hub
  entry that `cline auth` clobbered, then add a separate `hive` provider)
- opencode   : ~/.config/opencode/opencode.json (merge a `hive` provider,
  keeping cyberhub / gx10 / 111-gx10 untouched)

Secrets are read from ufo.env and never printed.
"""
import datetime
import io
import json
import os

ENV_FILE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"
BASE_URL = "https://api-cdn.thehive.ai/api/v3"
HIVE_MODELS = ["deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash"]


def hive_env():
    env = {}
    for line in io.open(ENV_FILE, encoding="utf-8", errors="ignore").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def fix_cline(secret):
    path = os.path.expanduser(r"~\.cline\data\settings\providers.json")
    with io.open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    prov = doc["providers"]

    # 1) restore the LOCAL HUB that `cline auth -p openai` overwrote.
    # The constellation's uncensored terminal is Abliteration.ai; the :4000
    # gx10 llm-hub is a legacy catalog only.
    prov["openai-compatible"] = {
        "settings": {
            "provider": "openai-compatible",
            "apiKey": "sk-local",
            "model": "abliterated-model-large-v2",
            "baseUrl": "https://api.abliteration.ai/v1",
            "reasoning": {"enabled": False},
        },
        "updatedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "tokenSource": "manual",
    }

    # 2) add Hive as its own provider id (ids are arbitrary: cf. tinfoil, nvidia)
    prov["hive"] = {
        "settings": {
            "provider": "openai-compatible",
            "apiKey": secret,
            "model": HIVE_MODELS[0],
            "baseUrl": BASE_URL,
            "reasoning": {"enabled": True, "effort": "high"},
        },
        "updatedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "tokenSource": "manual",
    }
    doc["lastUsedProvider"] = "nvidia"  # as it was before we touched anything
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return sorted(prov.keys())


def fix_opencode():
    path = os.path.expanduser(r"~\.config\opencode\opencode.json")
    with io.open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc.setdefault("provider", {})["hive"] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Hive (thehive.ai)",
        "options": {
            "baseURL": BASE_URL,
            "apiKey": "{env:HIVE_SECRET_KEY}",
            "timeout": 600000,
            "chunkTimeout": 180000,
        },
        "models": {
            "deepseek-ai/deepseek-v4.1-flash-1017": {
                "name": "DeepSeek 4.1 Flash 1017 (1M ctx, vision, tools)",
                "attachment": True,
                "tool_call": True,
                "reasoning": True,
                "limit": {"context": 1000000, "output": 65536},
            },
            "zai-org/glm-5.3-flash": {
                "name": "GLM 5.3 Flash (1M ctx, vision/video, tools)",
                "attachment": True,
                "tool_call": True,
                "reasoning": True,
                "limit": {"context": 1000000, "output": 65536},
            },
        },
    }
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return sorted(doc["provider"].keys())


if __name__ == "__main__":
    env = hive_env()
    secret = env["HIVE_SECRET_KEY"]
    print("cline providers :", fix_cline(secret))
    print("opencode providers:", fix_opencode())
    print("secret used from ufo.env, length", len(secret))
