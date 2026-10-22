"""Primary (R1) binding resolution - Phase 0, 2026-10-16.

The primary slot must be thehive.ai. Before this phase it was not durably
wired: PRIMARY_API_URL/KEY/MODEL were absent from HKCU and from the process
env, so `Settings` defaulted to api.openai.com with an EMPTY key, and the live
:9000 gateway only had the right values because they had been exported inline
in the shell that launched it (lost on restart). `tools/hive/serve_endpoints.py`
honoured HIVE_SECRET_KEY, but a hand-started gateway did not.

The bridge mirrors the specialist's existing _specialist_key() pattern: it
reads the ALREADY-persisted HIVE_SECRET_KEY/HIVE_API_BASE rather than copying
the secret into a second variable (S-A).
"""

import pytest
from fastapi.testclient import TestClient

import proxy_gateway
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401  (fixtures)


@pytest.fixture()
def client(script):
    """Script-backed gateway client (same shape as routing_test.py's)."""
    with TestClient(proxy_gateway.app) as tc:
        yield tc


def test_hive_base_strips_the_trailing_slash(monkeypatch):
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3/")
    assert proxy_gateway._hive_base() == "https://api-cdn.thehive.ai/api/v3"


def test_hive_base_absent_is_empty_string(monkeypatch):
    monkeypatch.delenv("HIVE_API_BASE", raising=False)
    assert proxy_gateway._hive_base() == ""


def test_primary_url_explicit_wins_over_hive(monkeypatch):
    monkeypatch.setenv("PRIMARY_API_URL", "http://other.example/v1/chat/completions")
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3")
    assert proxy_gateway._primary_url() == "http://other.example/v1/chat/completions"


def test_primary_url_bridges_to_hive_base(monkeypatch):
    """The core Phase 0 behaviour: no PRIMARY_API_URL -> Hive, not OpenAI."""
    monkeypatch.delenv("PRIMARY_API_URL", raising=False)
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3")
    assert proxy_gateway._primary_url() == "https://api-cdn.thehive.ai/api/v3/chat/completions"


def test_primary_url_does_not_double_the_suffix(monkeypatch):
    monkeypatch.delenv("PRIMARY_API_URL", raising=False)
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3/chat/completions")
    assert proxy_gateway._primary_url() == "https://api-cdn.thehive.ai/api/v3/chat/completions"


def test_primary_url_without_hive_keeps_the_openai_default(monkeypatch):
    monkeypatch.delenv("PRIMARY_API_URL", raising=False)
    monkeypatch.delenv("HIVE_API_BASE", raising=False)
    assert proxy_gateway._primary_url() == "https://api.openai.com/v1/chat/completions"


def test_primary_key_resolution_precedence(monkeypatch):
    monkeypatch.setenv("PRIMARY_API_KEY", "explicit")
    monkeypatch.setenv("HIVE_SECRET_KEY", "hive")
    assert proxy_gateway._primary_key() == "explicit"
    monkeypatch.delenv("PRIMARY_API_KEY")
    assert proxy_gateway._primary_key() == "hive"
    monkeypatch.delenv("HIVE_SECRET_KEY")
    assert proxy_gateway._primary_key() == ""


def test_primary_model_follows_the_url(monkeypatch):
    """Hive URL + gpt-4o model would be a guaranteed upstream 400, so the model
    id must be derived from the same condition as the URL."""
    monkeypatch.delenv("PRIMARY_MODEL", raising=False)
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3")
    assert proxy_gateway._primary_model() == "zai-org/glm-5.3-flash"
    monkeypatch.delenv("HIVE_API_BASE")
    assert proxy_gateway._primary_model() == "gpt-4o"


def test_explicit_primary_model_wins_over_hive(monkeypatch):
    monkeypatch.setenv("PRIMARY_MODEL", "deepseek-ai/deepseek-v4.1-flash-1017")
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3")
    assert proxy_gateway._primary_model() == "deepseek-ai/deepseek-v4.1-flash-1017"


def test_settings_bridges_when_primary_is_unset(monkeypatch):
    """End-to-end through Settings: no PRIMARY_* at all, Hive in the env."""
    for name in ("PRIMARY_API_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HIVE_API_BASE", "https://api-cdn.thehive.ai/api/v3")
    monkeypatch.setenv("HIVE_SECRET_KEY", "sk-hive-test")
    s = proxy_gateway.Settings()
    assert s.primary_api_url == "https://api-cdn.thehive.ai/api/v3/chat/completions"
    assert s.primary_api_key == "sk-hive-test"
    assert s.primary_model == "zai-org/glm-5.3-flash"


def test_settings_openai_default_when_no_provider_is_configured(monkeypatch):
    for name in ("PRIMARY_API_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL",
                 "HIVE_API_BASE", "HIVE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    s = proxy_gateway.Settings()
    assert s.primary_api_url == "https://api.openai.com/v1/chat/completions"
    assert s.primary_api_key == ""
    assert s.primary_model == "gpt-4o"


def test_healthz_reports_the_binding_without_leaking_the_key(client, script):
    """Assert the primary slot is observable - the whole point of Phase 0."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    cfg = resp.json()["config"]
    assert "primary_url" in cfg
    assert isinstance(cfg["primary_key_present"], bool)
    # the raw secret must never appear in an unauthenticated liveness probe
    assert "primary_api_key" not in cfg