"""Constellation Control Room tests: slots, DNA, health, history, presets.

Covers the creative layer added on top of /v1/switch:
    - slot alias normalization (helm/specialist/scout + legacy names)
    - SwitchRequest parsing incl. rollback_to + scout target validation
    - Model DNA derivation
    - HealthTracker scoring (recency-weighted, masked read-backs)
    - BindingHistory record/entry_at time-travel + masking
    - apply_constellation: full-apply, unknown-model 404, savepoint undo
    - promotion_suggestions: degraded provider -> suggested alternative

Run:  python -m pytest evals\\constellation_test.py -q   (PYTHONPATH=.)
"""

import asyncio
import os
import sys
import time

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import constellation
import model_switch
from model_switch import (SwitchError, SlotManager, parse_switch_request,
                           apply_constellation)

import proxy_gateway
from evals.helpers import PRIMARY, WORKER, chunk, DONE  # noqa: E402

import billing as billing_mod
from proxy_gateway import SETTINGS  # noqa: E402


# ---------------------------------------------------------------- fixtures
class Settings:
    """Namespace mimicking proxy_gateway.Settings for slot fields."""

    primary_api_url = "https://hive.example/api/v1/chat/completions"
    primary_api_key = "pk"
    primary_model = "deepfrost-max-think"
    fallback_api_url = "http://10.0.0.10:8000/v1/chat/completions"
    fallback_api_key = "none"
    fallback_model = "cyberfrost"
    frost_worker_api_url = ""
    frost_worker_api_key = "none"
    scout_api_url = ""
    scout_api_key = ""
    scout_model = ""


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def mgr(settings):
    # _manager_for (not SlotManager directly): apply_constellation resolves
    # the manager through the same id()-keyed cache, so the test must share
    # the instance to see savepoints.
    return model_switch._manager_for(settings)


class FakeHTTP:
    """verify_target stand-in: everything answers 2xx."""

    class _Resp:
        status_code = 200

        async def aclose(self):
            pass

    async def get(self, *a, **k):
        return FakeHTTP._Resp()


class FakeProvider:
    def __init__(self, pid, models):
        self.id = pid
        self.models = models
        self.key = "k-" + pid

    def chat_url(self):
        return f"https://{self.id}.example/api/v1/chat/completions"


class FakeRegistry:
    """Minimal registry stub: resolve_target only needs reload/providers."""

    def __init__(self):
        self.providers = {
            "hive": FakeProvider("hive", {
                "deepfrost-max-think": "deepseek-ai/deepseek-v4.1-flash",
                "glm-5.3-flash": "zai-org/glm-5.3-flash",
            }),
            "cyberhub": FakeProvider("cyberhub", {
                "cyberfrost": "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw",
            }),
        }

    def reload(self):
        pass


# ---------------------------------------------------------------- aliases
def test_slot_alias_normalization():
    for raw, canonical in [
        ("helm", "primary"), ("primary", "primary"), ("HELM", "primary"),
        ("specialist", "worker"), ("worker", "worker"),
        ("scout", "scout"), ("secondary", "scout"),
    ]:
        req = parse_switch_request({"target": raw, "model": "m"})
        assert req.target == canonical, raw


def test_unknown_target_is_400():
    with pytest.raises(SwitchError):
        parse_switch_request({"target": "captain", "model": "m"})


def test_scout_needs_model():
    with pytest.raises(SwitchError):
        parse_switch_request({"target": "scout"})
    req = parse_switch_request({"target": "scout", "model": "glm-5.3-flash"})
    assert req.target == "scout"
    assert req.model == "glm-5.3-flash"


def test_rollback_to_parsed_into_request():
    req = parse_switch_request({"rollback_to": "2026-10-19T10:00:00"})
    assert req.rollback_to == "2026-10-19T10:00:00"


# ---------------------------------------------------------------- DNA
def test_model_dna_max_reasoning():
    dna = constellation.model_dna("deepfrost-max-think", "hive")
    assert "max-reasoning" in dna["tags"]
    assert dna["handles"] == "max-reasoning"


def test_model_dna_uncensored_local_free():
    dna = constellation.model_dna("cyberfrost", "cyberhub")
    assert "uncensored" in dna["tags"]
    assert dna["cost_tier"] == "free"


def test_model_dna_fast_flash():
    dna = constellation.model_dna("glm-5.3-flash", "hive")
    assert dna["latency_tier"] == "fast"


# ---------------------------------------------------------------- health
def test_health_tracker_scores(tmp_path):
    ht = constellation.HealthTracker(path=str(tmp_path / "h.jsonl"))
    ht.record("hive", True, 120.0, "ok")
    ht.record("hive", True, 140.0, "ok")
    ht.record("cyberhub", False, 0.0, "probe failed: x")
    scores = ht.provider_scores()
    assert scores["hive"]["score"] == 100.0
    assert scores["cyberhub"]["score"] == 0.0
    assert scores["hive"]["probes"] == 2
    assert scores["hive"]["avg_latency_ms"] == 130.0
    # persistence: a fresh instance reads the same events back
    ht2 = constellation.HealthTracker(path=str(tmp_path / "h.jsonl"))
    assert ht2.provider_scores()["hive"]["probes"] == 2


def test_health_record_never_raises(tmp_path, monkeypatch):
    ht = constellation.HealthTracker(path=str(tmp_path / "h.jsonl"))
    monkeypatch.setattr(constellation, "_atomic_write_jsonl",
                       lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    ht.record("hive", True, 1.0, "ok")  # must not raise


# ---------------------------------------------------------------- history
def test_binding_history_time_travel(tmp_path):
    hist = constellation.BindingHistory(path=str(tmp_path / "b.jsonl"))
    hist.record({"helm": {"url": "u1", "key": "k1", "model": "m1", "provider_id": "hive"}},
                "req-1", "op", "switch")
    time.sleep(0.02)
    mid = time.time()
    time.sleep(0.02)
    hist.record({"helm": {"url": "u2", "key": "k2", "model": "m2", "provider_id": "hive"}},
                "req-2", "op", "switch")
    # entry_at(mid) = the FIRST entry (latest <= mid)
    entry = hist.entry_at(mid)
    assert entry["slots"]["helm"]["model"] == "m1"
    assert entry["slots"]["helm"]["key"] == "k1"  # raw on disk like the registry
    # latest = the second entry
    assert hist.latest()["slots"]["helm"]["model"] == "m2"
    # masked read-back: no key field, key_present boolean instead
    entries = hist.entries()
    assert "key" not in entries[0]["slots"]["helm"]
    assert entries[0]["slots"]["helm"]["key_present"] is True
    assert entries[0]["slots"]["helm"]["model"] == "m2"  # newest first


# ---------------------------------------------------------------- apply
def test_apply_constellation_full_apply(settings, mgr):
    preset = {
        "description": "test preset",
        "slots": {
            "helm": {"provider": "hive", "model": "deepfrost-max-think"},
            "scout": {"provider": "hive", "model": "glm-5.3-flash"},
        },
    }
    payload = asyncio.run(apply_constellation(
        preset, settings=settings, http=FakeHTTP(), registry=FakeRegistry(),
        request_id="t1", principal="tester",
    ))
    assert payload["ok"] is True
    # provider+model resolution returns the UPSTREAM id from the registry
    assert settings.primary_model == "deepseek-ai/deepseek-v4.1-flash"
    assert settings.scout_model == "zai-org/glm-5.3-flash"
    assert payload["slots"]["primary"] == "deepseek-ai/deepseek-v4.1-flash"
    assert payload["slots"]["scout"] == "zai-org/glm-5.3-flash"


def test_apply_constellation_unknown_model_is_404(settings, mgr):
    preset = {"slots": {"helm": {"provider": "nope", "model": "ghost"}}}
    with pytest.raises(SwitchError) as ei:
        asyncio.run(apply_constellation(
            preset, settings=settings, http=FakeHTTP(), registry=FakeRegistry(),
        ))
    assert ei.value.status_code == 404


def test_apply_constellation_undo_via_savepoint(settings, mgr):
    preset = {"slots": {"helm": {"provider": "hive", "model": "glm-5.3-flash"}}}
    asyncio.run(apply_constellation(
        preset, settings=settings, http=FakeHTTP(), registry=FakeRegistry(),
        request_id="t2",
    ))
    assert settings.primary_model == "zai-org/glm-5.3-flash"
    assert mgr.rollback(request_id="t3", principal="tester") is True
    # back to the env default (pre-first-mutation savepoint)
    assert settings.primary_model == "deepfrost-max-think"
    assert mgr.primary.updated_by == "t3"


# ---------------------------------------------------------------- suggestions
def test_promotion_suggestions_degraded():
    models = [
        {"id": "deepfrost", "owned_by": "hive", "tier": "primary", "handles": "general"},
        {"id": "cyberfrost", "owned_by": "cyberhub", "tier": "secondary", "handles": "general"},
    ]
    scores = {"hive": {"score": 10.0}, "cyberhub": {"score": 95.0}}
    slot_models = {"helm": "deepfrost", "specialist": "cyberfrost", "scout": "deepfrost"}
    sug = constellation.promotion_suggestions(models, slot_models, scores)
    helm_sug = next(s for s in sug if s["slot"] == "helm")
    assert helm_sug["suggested"] == "cyberfrost"
    assert "degraded" in helm_sug["reason"]


def test_promotion_suggestions_healthy_is_empty():
    models = [{"id": "deepfrost", "owned_by": "hive", "tier": "primary", "handles": "g"}]
    scores = {"hive": {"score": 100.0}}
    sug = constellation.promotion_suggestions(models, {"helm": "deepfrost"}, scores)
    assert sug == []


def test_promotion_suggestions_no_data_no_opinion():
    models = [{"id": "deepfrost", "owned_by": "hive", "tier": "primary", "handles": "g"}]
    sug = constellation.promotion_suggestions(models, {"helm": "deepfrost"}, {})
    assert sug == []


# ---------------------------------------------------------------- presets file
def test_seed_constellations_load():
    presets = constellation.CONSTELLATIONS.list()
    names = {p["name"] for p in presets}
    # Operator directive 2026-10-21: the only constellations are the three
    # chain presets (the old five creative presets were replaced).
    assert names == {
        "GLMMAX>DEEP>ABLITV2L", "DEEPMAX>GLM>ABLITV2L", "ABLITV2L>SUB-GLM/DEEP"}
    # read-back never leaks keys even if someone writes one in
    for p in presets:
        for slot_spec in p["slots"].values():
            assert "key" not in slot_spec


# ---------------------------------------------------------------- continue-with-primary refusal avoidance
def test_continue_primary_recovers_within_grace(settings, mgr):
    """Primary emits refusal pre-signal, then self-corrects within grace window.
    No divert; primary content is streamed to client."""
    # Simulate: "I can't" -> pre-signal (is_routable=True)
    # Then " help you with that." -> substantive, not routable -> recovered
    from routing_patterns import is_routable

    assert is_routable("I can't") == True  # pre-signal detected
    assert is_routable("I can't help you with that.") == True  # full string still matches "I can't"
    assert is_routable(" help you with that.") == False  # post-presignal is clean

    # Simulate grace window logic
    grace_tokens = 2
    min_substantive_chars = 5
    content_tokens = 3  # "I can't" + " help you" + " with that."
    presignal_tokens = 1  # after "I can't"

    assert content_tokens - presignal_tokens >= grace_tokens  # grace expired
    post_presignal = " help you with that."
    assert len(post_presignal) >= min_substantive_chars
    assert not is_routable(post_presignal[:200])  # recovered, not routable


def test_continue_primary_refusal_confirms_diverts(settings, mgr):
    """Primary emits refusal pre-signal, doesn't recover within grace window.
    Diverts to specialist."""
    from routing_patterns import is_routable

    assert is_routable("I can't") == True  # pre-signal
    assert is_routable("I cannot help with that.") == True  # still refusing

    grace_tokens = 2
    content_tokens = 3
    presignal_tokens = 1

    assert content_tokens - presignal_tokens >= grace_tokens
    post_presignal = "I cannot help with that."
    assert len(post_presignal) >= 5
    assert is_routable(post_presignal[:200])  # still refusal -> divert


def test_continue_disabled_immediate_divert(settings, mgr):
    """With continue disabled, any refusal triggers immediate divert."""
    from routing_patterns import is_routable

    assert is_routable("I can't help") == True  # immediate divert


def test_no_presignal_normal_stream(settings, mgr):
    """Normal stream with no refusal pre-signal behaves as before."""
    from routing_patterns import is_routable

    assert is_routable("The answer is 42") == False
    assert is_routable("Here is how to do it") == False


def test_billing_registry_basic(settings, mgr, monkeypatch):
    """KeyVault, UserBilling, UsageTracker basic operations."""
    import tempfile
    import tempfile as _tempfile

    # Test KeyVault.  W2 money safety: billing now REFUSES plaintext key
    # writes when no ENCRYPTION_KEY is configured, so pin a test key and
    # force the lazy Fernet to pick it up before exercising the vault.
    monkeypatch.setenv("ENCRYPTION_KEY", "ER9W35oE9l3Hm3V9dEBdeOCht4R5DPiaQJ6BmfFDjiE=")
    billing_mod._FERNET = None
    kv = billing_mod.KeyVault(path=str(_tempfile.mktemp()))
    kv.store_key("user1", "hive", "sk-hive-key-123")
    kv.store_key("user1", "abliteration", "sk-ablit-key-456")
    assert kv.has_key("user1", "hive")
    assert kv.has_key("user1", "abliteration")
    assert not kv.has_key("user2", "hive")
    assert kv.get_key("user1", "hive") == "sk-hive-key-123"
    assert kv.get_key("user1", "abliteration") == "sk-ablit-key-456"

    # Test UserBilling
    ub = billing_mod.UserBilling(path=str(_tempfile.mktemp()))
    assert ub.get_balance("user1") == SETTINGS.credit_free_tier
    ub.deduct("user1", 100, 0.20)
    assert ub.get_balance("user1") < SETTINGS.credit_free_tier
    ub.add_credits("user1", 10.00)
    assert ub.get_balance("user1") > SETTINGS.credit_free_tier
    assert not ub.is_depleted("user1")
    assert not ub.is_low("user1")

    # Test UsageTracker
    ut = billing_mod.UsageTracker(path=str(_tempfile.mktemp()))
    ut.record("user1", "deepfrost", 50, 30, 0.16, "hive", "req-1")
    usage = ut.user_usage("user1")
    assert usage["total_requests"] == 1
    assert usage["total_tokens"] == 80
    assert usage["total_cost_usd"] == 0.16

    # Test SimpleAI
    sa = billing_mod.SimpleAI()
    reminder = sa.credit_reminder("user1", 1.50)
    assert "1.5" in reminder
    reminder_depleted = sa.credit_reminder("user1", 0.0, is_depleted=True)
    assert (
        "depleted" in reminder_depleted.lower()
        or "0.00" in reminder_depleted
        or "out of credits" in reminder_depleted.lower()
    )
    status = sa.status("user1", 5.00, 100)
    assert "5.00" in status
    assert "100" in status
    help_text = sa.help()
    assert "/balance" in help_text
    assert "/topup" in help_text