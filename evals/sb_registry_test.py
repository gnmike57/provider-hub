"""S-B (2026-10-22): no plaintext provider keys in gateway_registry.json.

Pins:
  - the deployed registry file carries NO key for hive/ablit (env-only)
  - providers.Registry resolves blank keys from the env overlay
    (HIVE_SECRET_KEY / ABLITERATION_API_KEY) - /v1/switch consumers see
    the same key as before
  - redhands's literal "none" placeholder survives (it is not a secret)
  - tools/hive/make_gateway_registry.py no longer embeds the key either
"""
import json
import pathlib

import pytest

import providers

ROOT = pathlib.Path(__file__).resolve().parents[1]
REG = ROOT / "gateway_registry.json"


def test_registry_file_has_no_plaintext_secrets():
    if not REG.exists():
        pytest.skip("gateway_registry.json not deployed")
    doc = json.loads(REG.read_text(encoding="utf-8"))
    for pid, prov in doc["providers"].items():
        if pid == "redhands":
            continue  # literal "none" placeholder, not a secret
        assert prov.get("key", "") == "", \
            f"{pid} key must be env-only (S-B)"


def test_builder_no_longer_embeds_the_key():
    src = (ROOT / "tools" / "hive" / "make_gateway_registry.py").read_text(
        encoding="utf-8")
    assert 'key: key("HIVE_SECRET_KEY")' not in src
    assert '"key": ""' in src  # the hive provider is written blank


def test_env_overlay_resolves_blank_keys(tmp_path, monkeypatch):
    reg_path = tmp_path / "reg.json"
    reg_path.write_text(json.dumps({
        "providers": {
            "hive": {"api": "openai", "base_url": "https://h/v3",
                     "key": "", "models": {"m": "m"}},
            "redhands": {"api": "openai", "base_url": "http://c/v1",
                         "key": "none", "models": {}}},
        "defaults": {}}), encoding="utf-8")
    monkeypatch.setenv("HIVE_SECRET_KEY", "sk-test-hive")
    reg = providers.Registry(str(reg_path))
    assert reg.providers["hive"].key == "sk-test-hive"
    assert reg.providers["redhands"].key == "none"   # untouched
    # no env value -> the blank stays blank (no guessing)
    monkeypatch.setenv("HIVE_SECRET_KEY", "")
    reg2 = providers.Registry(str(reg_path))
    assert reg2.providers["hive"].key == ""
