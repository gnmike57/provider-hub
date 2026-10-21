"""Runtime switch tests: /v1/switch unit + endpoint integration.

Covers the model_switch module (parse/resolve/savepoint/rollback/swap/
snapshot/verify) and the gateway endpoints that front it (body shapes,
errors, metrics, healthz surface), ending with the seamlessness contract:
an in-flight stream keeps the binding it started on while new requests
pick up the switched one.

Run: evals\\run_tests.bat  (offline; no real upstream is contacted)
"""

import asyncio
import contextlib
import json
import threading
import types

import httpx
import pytest
from fastapi.testclient import TestClient

import model_switch
import proxy_gateway
import providers
from helpers import PRIMARY, WORKER, chunk, DONE, script  # noqa: F401

PRINCIPAL = proxy_gateway.PRINCIPAL_HEADER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _registry_file(tmp_path):
    """A deterministic 4-provider registry (includes an ambiguity pair)."""
    data = {
        "providers": {
            "alt": {"api": "openai", "base_url": "http://alt.test/v1",
                    "key": "k-alt", "models": {"alt": "alt-upstream"}},
            "solo": {"api": "openai", "base_url": "http://solo.test/v1",
                     "key": "", "models": {"solo-model": "solo-upstream"}},
            "dupa": {"api": "openai", "base_url": "http://dupa.test/v1",
                     "key": "", "models": {"shared": "dupa-upstream"}},
            "dupb": {"api": "openai", "base_url": "http://dupb.test/v1",
                     "key": "", "models": {"shared": "dupb-upstream"}},
        },
        "defaults": {},
    }
    path = tmp_path / "gateway_registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return providers.Registry(path=str(path))


@pytest.fixture()
def reg(tmp_path):
    """Point the gateway's registry() singleton at the tmp registry file."""
    saved = proxy_gateway._registry
    proxy_gateway._registry = _registry_file(tmp_path)
    yield proxy_gateway._registry
    proxy_gateway._registry = saved


@pytest.fixture()
def gw(script, reg):
    """TestClient over the real app + mock upstreams + /models probe steps."""
    sc = script
    for url in ("http://alt.test/v1/models", "http://solo.test/v1/models",
                "http://raw.test/v1/models", "http://dupa.test/v1/models",
                "http://dupb.test/v1/models", "http://primary.test/v1/models",
                "http://worker.test/v1/models"):
        sc.script(url, [("json", {"data": []})])
    with TestClient(proxy_gateway.app) as tc:
        yield tc


@pytest.fixture(autouse=True)
def fresh_switch_state(script):
    """A pristine SlotManager bound to the live SETTINGS for every test."""
    key = id(proxy_gateway.SETTINGS)
    saved = model_switch._managers.get(key)
    model_switch._managers[key] = model_switch.SlotManager(proxy_gateway.SETTINGS)
    yield
    if saved is None:
        model_switch._managers.pop(key, None)
    else:
        model_switch._managers[key] = saved


def _dummy_settings():
    s = types.SimpleNamespace()
    s.primary_api_url = PRIMARY
    s.primary_api_key = ""
    s.primary_model = "primary"
    s.fallback_api_url = WORKER
    s.fallback_api_key = "none"
    s.fallback_model = "worker"
    return s


# ---------------------------------------------------------------------------
# Unit: parse_switch_request
# ---------------------------------------------------------------------------
def test_parse_empty_body_is_status():
    req = model_switch.parse_switch_request({})
    assert req.target == "status"
    assert req.verify is True and req.rollback is False


def test_parse_slot_target_with_model():
    req = model_switch.parse_switch_request({"target": "worker", "model": "solo-model"})
    assert req.target == "worker" and req.model == "solo-model"


def test_parse_unknown_target_is_400():
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.parse_switch_request({"target": "bogus"})
    assert ei.value.status_code == 400
    assert "unknown target" in str(ei.value)


def test_parse_slot_without_model_is_400():
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.parse_switch_request({"target": "primary"})
    assert ei.value.status_code == 400
    assert "needs a 'model'" in str(ei.value)


def test_parse_slot_rollback_needs_no_model():
    req = model_switch.parse_switch_request({"target": "worker", "rollback": True})
    assert req.rollback is True and req.target == "worker"


def test_parse_non_object_body_is_400():
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.parse_switch_request(["nope"])
    assert "JSON object" in str(ei.value)


def test_parse_raw_target_keeps_key_and_verify_flag():
    req = model_switch.parse_switch_request(
        {"target": "worker", "url": "http://x/v1", "model": "m", "key": "sk",
         "verify": False}
    )
    assert req.url == "http://x/v1" and req.key == "sk" and req.verify is False


# ---------------------------------------------------------------------------
# Unit: resolve_target (tmp registry + Frost fallback)
# ---------------------------------------------------------------------------
def test_resolve_raw_override():
    got = model_switch.resolve_target(
        model_switch.parse_switch_request(
            {"target": "worker", "url": "http://raw.test/v1/", "model": "raw-model",
             "key": "rk"}
        ),
        _dummy_settings(),
    )
    assert got == {"url": "http://raw.test/v1", "key": "rk",
                   "model": "raw-model", "provider_id": "raw"}


def test_resolve_explicit_provider(tmp_path):
    got = model_switch.resolve_target(
        model_switch.parse_switch_request(
            {"target": "primary", "provider": "alt", "model": "alt"}
        ),
        _dummy_settings(), registry=_registry_file(tmp_path),
    )
    assert got["url"] == "http://alt.test/v1/chat/completions"
    assert got["key"] == "k-alt" and got["model"] == "alt-upstream"
    assert got["provider_id"] == "alt"


def test_resolve_unknown_provider_is_404(tmp_path):
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.resolve_target(
            model_switch.parse_switch_request(
                {"target": "worker", "provider": "nosuch", "model": "m"}
            ),
            _dummy_settings(), registry=_registry_file(tmp_path),
        )
    assert ei.value.status_code == 404
    assert "unknown provider" in str(ei.value)


def test_resolve_provider_missing_model_is_404(tmp_path):
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.resolve_target(
            model_switch.parse_switch_request(
                {"target": "worker", "provider": "alt", "model": "nope"}
            ),
            _dummy_settings(), registry=_registry_file(tmp_path),
        )
    assert ei.value.status_code == 404
    assert "does not expose" in str(ei.value)


def test_resolve_bare_model_unique_provider(tmp_path):
    got = model_switch.resolve_target(
        model_switch.parse_switch_request({"target": "worker", "model": "solo-model"}),
        _dummy_settings(), registry=_registry_file(tmp_path),
    )
    assert got["provider_id"] == "solo"
    assert got["model"] == "solo-upstream"


def test_resolve_bare_model_exposed_upstream_id(tmp_path):
    got = model_switch.resolve_target(
        model_switch.parse_switch_request({"target": "worker", "model": "alt-upstream"}),
        _dummy_settings(), registry=_registry_file(tmp_path),
    )
    assert got["provider_id"] == "alt"


def test_resolve_ambiguous_bare_model_is_400(tmp_path):
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.resolve_target(
            model_switch.parse_switch_request({"target": "worker", "model": "shared"}),
            _dummy_settings(), registry=_registry_file(tmp_path),
        )
    assert ei.value.status_code == 400
    assert "several providers" in str(ei.value)
    assert "dupa" in str(ei.value) and "dupb" in str(ei.value)


def test_resolve_frost_name_maps_to_slot_binding():
    s = _dummy_settings()
    got = model_switch.resolve_target(
        model_switch.parse_switch_request({"target": "worker", "model": "CyberFrost"}),
        s,
    )
    assert got["url"] == WORKER and got["provider_id"] == "frost:worker"
    # CYBER-FROST RETIRED (2026-10-21): the legacy name resolves to the
    # constellation's uncensored TERMINAL (abliterated-model-large-v2).
    assert got["model"] == "abliterated-model-large-v2"
    got2 = model_switch.resolve_target(
        model_switch.parse_switch_request({"target": "primary", "model": "DeepFrost v4.1"}),
        s,
    )
    assert got2["url"] == PRIMARY and got2["provider_id"] == "frost:primary"
    assert got2["model"] == "deepseek-ai/deepseek-v4.1-flash"


def test_resolve_unresolvable_model_is_404():
    with pytest.raises(model_switch.SwitchError) as ei:
        model_switch.resolve_target(
            model_switch.parse_switch_request({"target": "worker", "model": "ghost"}),
            _dummy_settings(),
        )
    assert ei.value.status_code == 404
    assert "could not resolve" in str(ei.value)


# ---------------------------------------------------------------------------
# Unit: SlotManager
# ---------------------------------------------------------------------------
def test_apply_writes_slot_and_settings():
    s = _dummy_settings()
    mgr = model_switch.SlotManager(s)
    b = mgr.apply(target="worker", url="http://alt.test/v1", key="k",
                  model="alt-upstream", provider_id="alt",
                  request_id="req-1", principal="tester")
    assert (s.fallback_api_url, s.fallback_api_key, s.fallback_model) == (
        "http://alt.test/v1", "k", "alt-upstream")
    assert (b.model, b.url, b.provider_id, b.key_present, b.updated_by) == (
        "alt-upstream", "http://alt.test/v1", "alt", True, "req-1")
    p = mgr.apply(target="primary", url="http://solo.test/v1", key="",
                  model="solo-upstream", provider_id="solo",
                  request_id="req-2", principal="tester")
    assert (s.primary_api_url, s.primary_api_key, s.primary_model) == (
        "http://solo.test/v1", "", "solo-upstream")
    assert p.key_present is False


def test_savepoint_rollback_restores_both_slots():
    s = _dummy_settings()
    mgr = model_switch.SlotManager(s)
    mgr.apply(target="worker", url="http://alt.test/v1", key="k",
              model="alt-upstream", provider_id="alt")
    mgr.savepoint()
    assert mgr.has_savepoint() is True
    mgr.apply(target="primary", url="http://solo.test/v1", key="",
              model="solo-upstream")
    assert mgr.rollback(request_id="req-r", principal="tester") is True
    assert (s.primary_api_url, s.primary_model) == (PRIMARY, "primary")
    assert (s.fallback_api_url, s.fallback_model) == (WORKER, "worker")
    assert mgr.primary.provider_id == "" and mgr.worker.provider_id == ""
    assert mgr.worker.updated_by == "req-r"
    assert [e.action for e in mgr.events] == ["rolled_back"]


def test_rollback_without_savepoint_is_noop():
    mgr = model_switch.SlotManager(_dummy_settings())
    assert mgr.has_savepoint() is False
    assert mgr.rollback() is False


def test_swap_exchanges_slots():
    s = _dummy_settings()
    mgr = model_switch.SlotManager(s)
    mgr.apply(target="worker", url="http://alt.test/v1", key="k",
              model="alt-upstream", provider_id="alt")
    mgr.swap(request_id="req-s", principal="tester")
    assert (s.primary_api_url, s.primary_api_key, s.primary_model) == (
        "http://alt.test/v1", "k", "alt-upstream")
    assert (s.fallback_api_url, s.fallback_api_key, s.fallback_model) == (
        PRIMARY, "", "primary")
    assert mgr.primary.provider_id == "alt" and mgr.worker.provider_id == ""
    assert mgr.primary.updated_by == "req-s" and mgr.worker.updated_by == "req-s"


def test_event_ring_buffer_keeps_last_eight():
    mgr = model_switch.SlotManager(_dummy_settings())
    for i in range(12):
        mgr.record(f"req-{i}", "tester", "worker", "applied")
    assert len(mgr.events) == 8
    assert mgr.events[0].request_id == "req-4"
    assert mgr.events[-1].request_id == "req-11"
    snap = mgr.snapshot()
    assert len(snap["last_events"]) == 8
    assert snap["last_events"][-1]["request_id"] == "req-11"


def test_snapshot_shape():
    mgr = model_switch.SlotManager(_dummy_settings())
    snap = mgr.snapshot()
    assert snap["primary"] == {"model": "primary", "url": PRIMARY,
                               "key_present": False, "provider_id": "",
                               "updated_ts": None, "updated_by": ""}
    assert set(snap["worker"]) == set(snap["primary"])


# ---------------------------------------------------------------------------
# Unit: perform_switch orchestration (fake http probe, no endpoint involved)
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status):
        self.status_code = status

    async def aclose(self):
        pass


class _FakeHttp:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return _FakeResp(self.status)


def test_perform_switch_status_payload():
    s = _dummy_settings()
    payload = asyncio.run(model_switch.perform_switch(
        {}, settings=s, http=_FakeHttp(), audit_log=""))
    assert payload["ok"] is True and payload["switched"] == "status"
    assert payload["primary"]["url"] == PRIMARY
    assert payload["worker"]["model"] == "worker"


def test_perform_switch_rollback_needs_savepoint():
    s = _dummy_settings()
    with pytest.raises(model_switch.SwitchError) as ei:
        asyncio.run(model_switch.perform_switch(
            {"target": "primary", "rollback": True},
            settings=s, http=_FakeHttp(), audit_log=""))
    assert ei.value.status_code == 400
    assert "nothing to roll back" in str(ei.value)


def test_perform_switch_applies_verified_target(tmp_path):
    s = _dummy_settings()
    payload = asyncio.run(model_switch.perform_switch(
        {"target": "worker", "model": "solo-model"},
        settings=s, http=_FakeHttp(200), registry=_registry_file(tmp_path),
        request_id="req-9", principal="tester", audit_log=""))
    assert payload["ok"] is True and payload["switched"] == "worker"
    assert payload["provider_id"] == "solo" and payload["model"] == "solo-upstream"
    assert payload["verified"] is True and payload["rollback_available"] is True
    assert (s.fallback_api_url, s.fallback_model) == (
        "http://solo.test/v1/chat/completions", "solo-upstream")
    mgr = model_switch._manager_for(s)
    assert mgr.events[-1].target == "worker" and mgr.events[-1].action == "verified"


def test_perform_switch_verify_failure_still_applies(tmp_path):
    """Fail-open: a failed probe is disclosed (verified:false) but the switch
    is still applied - the operator decides via rollback:true, not the probe."""
    s = _dummy_settings()
    payload = asyncio.run(model_switch.perform_switch(
        {"target": "worker", "url": "http://dead.test/v1", "model": "m"},
        settings=s, http=_FakeHttp(404), request_id="req-x", principal="tester",
        audit_log=""))
    assert payload["ok"] is True and payload["verified"] is False
    assert "HTTP 404" in payload["verify_detail"]
    assert s.fallback_api_url == "http://dead.test/v1"
    mgr = model_switch._manager_for(s)
    assert mgr.events[-1].action == "verify_failed"


# ==== PART4 ====
