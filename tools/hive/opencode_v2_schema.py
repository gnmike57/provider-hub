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
    local = [
        ("cyberhub", "cyber.local model hub", "http://cyber.local:4000/v1", "sk-local",
         ["qwen2.4t", "qwen3-coder-480b", "gpt-oss-120b", "unc72b", "gemma3-27b-heretic-vl",
          "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw", "cyberfrost", "cyber35b", "qwen3.8-flash-next",
          "glm-5.3", "kimi-k3", "k2-375b"]),
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
