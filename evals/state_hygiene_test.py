"""W5 statewarden regression tests: state quarantine + switch integrity + hygiene.

One test per fix (evals/state_hygiene_test.py):
  1. conftest.py quarantine - state env vars point OUT of the repo, and the
     import-time singletons (constellation.BINDING_HISTORY, ...) are bound to
     the quarantine, so a switch can never append tester rows to the production
     slot_bindings.json / cards.jsonl again (they were poisoned 2026-10-20).
  2. model_switch savepoint semantics - every switch RE-ARMS its own rollback
     (rollback:true undoes the LAST switch, not everything since the first),
     and rollback CONSUMES the savepoint instead of leaving it armed forever.
  3. resolve_target key=None vs key="" - None keeps the slot's current key,
     "" clears it (None used to be flattened to "", silently clearing it).
  4. SlotManager.apply() rejects blank url/model instead of blanking a slot.
  5. One asyncio.Lock serialises savepoint -> verify -> apply.
  6. Time-travel rollback_to skips slots the old entry never bound.
  7. providers __all__ has no phantom entries (import * works).
  8. _HUB_DISPLAY is derived from HUB_MODEL_ALIASES (pinned).
  9. Dead code removed: Tier4Classifier/TIER4, requests_clean, buffered_text.

Run: py -3.12 -m pytest evals/state_hygiene_test.py -q
"""

import asyncio
import json
import os
import tempfile
import time
import types

import pytest

import model_switch
from model_switch import SwitchError, SlotManager, SwitchRequest, perform_switch, resolve_target

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ns():
    """Fresh settings namespace (unique object -> unique SlotManager)."""
    s = types.SimpleNamespace()
    s.primary_api_url = "http://orig.test/v1/chat/completions"
    s.primary_api_key = "k-orig"
    s.primary_model = "m0"
    s.fallback_api_url = "http://work.test/v1/chat/completions"
    s.fallback_api_key = "k-work"
    s.fallback_model = "mw"
    s.scout_api_url = "http://scout.test/v1/chat/completions"
    s.scout_api_key = "k-scout"
    s.scout_model = "ms"
    return s


class _Resp:
    status_code = 200

    async def aclose(self):
        pass


class _FakeHttp:
    """verify_target stand-in: everything answers 2xx."""

    async def get(self, url, headers=None, timeout=None):
        return _Resp()


class _GatedHttp:
    """Blocks the FIRST verify probe until .gate is set; records call order."""

    def __init__(self):
        self.order = []
        self.gate = None
        self._first = True

    async def get(self, url, headers=None, timeout=None):
        self.order.append(url)
        if self._first:
            self._first = False
            await self.gate.wait()
        return _Resp()


# --- END PART 1 ---
# ---------------------------------------------------------------------------
# 1. conftest quarantine
# ---------------------------------------------------------------------------
def test_conftest_quarantines_state_files():
    """Every state env var points into the session temp dir, not the repo."""
    import billing
    import constellation
    import siphon

    for var in ("SLOT_HISTORY_FILE", "SIPHON_CARDS_FILE", "SIPHON_STATE_FILE",
                "USERS_FILE", "USAGE_FILE"):
        value = os.environ[var]
        assert value.startswith(tempfile.gettempdir()), (var, value)
        assert not os.path.dirname(value).startswith(ROOT), (var, value)

    # module constants resolved the redirected values at import time...
    assert constellation.HISTORY_PATH == os.environ["SLOT_HISTORY_FILE"]
    assert siphon.CARDS_PATH == os.environ["SIPHON_CARDS_FILE"]
    assert siphon.STATE_PATH == os.environ["SIPHON_STATE_FILE"]
    assert billing.USERS_PATH == os.environ["USERS_FILE"]
    assert billing.USAGE_PATH == os.environ["USAGE_FILE"]
    # ...and so did the import-time singletons (the actual poison vector).
    assert constellation.BINDING_HISTORY.path == os.environ["SLOT_HISTORY_FILE"]
    assert constellation.HEALTH.path == os.environ["MODEL_HEALTH_FILE"]


def test_runtime_switch_writes_quarantine_not_production():
    """A perform_switch round-trip appends to the QUARANTINE history only."""
    import constellation

    prod = os.path.join(constellation.ROOT, "slot_bindings.json")
    before = open(prod, "rb").read() if os.path.exists(prod) else b""

    s = _ns()
    payload = asyncio.run(perform_switch(
        {"target": "primary", "url": "http://qt.test/v1", "model": "qm"},
        settings=s, http=_FakeHttp(), request_id="w5-quarantine-probe",
        principal="tester", audit_log="",
    ))
    assert payload["ok"] is True

    after = open(prod, "rb").read() if os.path.exists(prod) else b""
    assert after == before, "a test wrote the production slot_bindings.json"

    quarantined = os.environ["SLOT_HISTORY_FILE"]
    assert os.path.exists(quarantined)
    rows = [json.loads(l) for l in open(quarantined, encoding="utf-8") if l.strip()]
    assert rows and rows[-1]["request_id"] == "w5-quarantine-probe"


# --- END PART 2 ---
# ---------------------------------------------------------------------------
# 2. savepoint re-arm + consume
# ---------------------------------------------------------------------------
def test_savepoint_rearms_after_each_switch():
    """rollback:true undoes the LAST switch, not everything since the first."""
    s = _ns()
    http = _FakeHttp()
    asyncio.run(perform_switch(
        {"target": "primary", "url": "http://a.test/v1", "model": "ma"},
        settings=s, http=http, request_id="r1", principal="tester", audit_log=""))
    asyncio.run(perform_switch(
        {"target": "primary", "url": "http://b.test/v1", "model": "mb"},
        settings=s, http=http, request_id="r2", principal="tester", audit_log=""))

    payload = asyncio.run(perform_switch(
        {"target": "primary", "rollback": True},
        settings=s, http=http, request_id="r3", principal="tester", audit_log=""))
    assert payload["ok"] is True
    # restored to the state BEFORE switch r2 (the last one), not before r1
    assert s.primary_api_url == "http://a.test/v1"
    assert s.primary_model == "ma"

    # the savepoint was CONSUMED: nothing left to roll back...
    with pytest.raises(SwitchError) as ei:
        asyncio.run(perform_switch(
            {"target": "primary", "rollback": True},
            settings=s, http=http, request_id="r4", principal="tester", audit_log=""))
    assert "nothing to roll back" in str(ei.value)
    mgr = model_switch._manager_for(s)
    assert mgr.has_savepoint() is False
    # ...and the state is untouched by the failed second rollback
    assert s.primary_api_url == "http://a.test/v1"


def test_switch_response_advertises_live_rollback_availability():
    """rollback_available reflects the actual savepoint, not a constant True."""
    s = _ns()
    mgr = model_switch._manager_for(s)
    assert mgr.has_savepoint() is False
    payload = asyncio.run(perform_switch(
        {"target": "primary", "url": "http://a.test/v1", "model": "ma"},
        settings=s, http=_FakeHttp(), request_id="r5", principal="tester", audit_log=""))
    assert payload["rollback_available"] is True
    mgr.rollback(request_id="r6", principal="tester")
    assert mgr.has_savepoint() is False


def test_explicit_savepoint_after_mutation_still_does_not_bake_in():
    """The sticky default savepoint() survives: post-mutation snapshots cannot
    make a mutation unrollbackable (the historical bug the stickiness fixed)."""
    s = _ns()
    mgr = SlotManager(s)
    mgr.apply(target="primary", url="http://a.test/v1", key="k", model="ma",
              request_id="p1")
    mgr.savepoint()  # NOT forced: must be a no-op, or ma becomes permanent
    mgr.apply(target="primary", url="http://b.test/v1", key="k", model="mb",
              request_id="p2")
    assert mgr.rollback(request_id="p3", principal="") is True
    assert s.primary_model == "m0"  # back to the pre-FIRST-mutation state


# --- END PART 3 ---
# ---------------------------------------------------------------------------
# 3. three-state key: None keeps, "" clears
# ---------------------------------------------------------------------------
def test_raw_switch_without_key_keeps_existing_key():
    s = _ns()
    resolved = resolve_target(
        SwitchRequest(target="primary", url="http://x.test/v1", model="m"), s, None)
    assert resolved["key"] is None  # used to be flattened to ""

    asyncio.run(perform_switch(
        {"target": "primary", "url": "http://x.test/v1", "model": "m"},
        settings=s, http=_FakeHttp(), request_id="k1", principal="tester", audit_log=""))
    assert s.primary_api_key == "k-orig"  # kept, not cleared

    # explicit "" clears it
    asyncio.run(perform_switch(
        {"target": "primary", "url": "http://x.test/v1", "model": "m", "key": ""},
        settings=s, http=_FakeHttp(), request_id="k2", principal="tester", audit_log=""))
    assert s.primary_api_key == ""


def test_apply_key_none_keeps_slot_key():
    mgr = SlotManager(_ns())
    mgr.apply(target="worker", url="http://w1.test/v1", key=None, model="w1",
              request_id="q1")
    assert mgr._settings.fallback_api_key == "k-work"
    assert mgr.worker.key_present is True
    mgr.apply(target="worker", url="http://w2.test/v1", key="", model="w2",
              request_id="q2")
    assert mgr._settings.fallback_api_key == ""
    assert mgr.worker.key_present is False


# ---------------------------------------------------------------------------
# 4. apply() validation
# ---------------------------------------------------------------------------
def test_apply_rejects_blank_url_or_model():
    mgr = SlotManager(_ns())
    with pytest.raises(SwitchError) as e1:
        mgr.apply(target="primary", url="", key="k", model="m", request_id="v1")
    assert "non-empty" in str(e1.value)
    with pytest.raises(SwitchError):
        mgr.apply(target="worker", url="http://w.test/v1", key="k", model="",
                  request_id="v2")
    # whitespace-only counts as blank too
    with pytest.raises(SwitchError):
        mgr.apply(target="scout", url="   ", key="k", model="m", request_id="v3")
    # nothing was applied
    assert mgr.primary.model == "m0"


# --- END PART 4 ---
# ---------------------------------------------------------------------------
# 5. asyncio.Lock across savepoint -> verify -> apply
# ---------------------------------------------------------------------------
def test_concurrent_switches_serialize():
    s = _ns()
    http = _GatedHttp()

    async def main():
        http.gate = asyncio.Event()
        a = asyncio.create_task(perform_switch(
            {"target": "primary", "url": "http://a.test/v1", "model": "ma"},
            settings=s, http=http, request_id="lock-a", principal="tester",
            audit_log=""))
        for _ in range(50):  # let A reach its (blocked) verify probe
            await asyncio.sleep(0)
        assert not a.done()
        assert s.primary_api_url == "http://orig.test/v1/chat/completions"

        b = asyncio.create_task(perform_switch(
            {"target": "primary", "url": "http://b.test/v1", "model": "mb"},
            settings=s, http=http, request_id="lock-b", principal="tester",
            audit_log=""))
        for _ in range(50):  # give B every chance to misbehave
            await asyncio.sleep(0)

        # B is parked on the lock: A's verify is still the only probe, and no
        # apply has happened (without the lock, B would have applied by now).
        assert not b.done()
        assert http.order == ["http://a.test/v1/models"]
        assert s.primary_api_url == "http://orig.test/v1/chat/completions"

        http.gate.set()
        pa, pb = await asyncio.gather(a, b)
        assert (pa["model"], pb["model"]) == ("ma", "mb")
        # serialized: A's apply ran to completion before B's probe started
        assert http.order == ["http://a.test/v1/models", "http://b.test/v1/models"]
        assert s.primary_api_url == "http://b.test/v1"

    asyncio.run(main())


# --- END PART 5 ---
# ---------------------------------------------------------------------------
# 6. time-travel skips never-bound slots
# ---------------------------------------------------------------------------
def test_rollback_to_skips_never_bound_slots():
    import constellation

    s = _ns()
    constellation.BINDING_HISTORY.record(
        {
            "helm": {"url": "http://old-helm.test/v1/chat/completions",
                     "key": "k-old", "model": "mh", "provider_id": "hive"},
            "specialist": {"url": "", "key": "", "model": "", "provider_id": ""},
            "scout": {"url": "http://old-scout.test/v1/chat/completions",
                      "key": "", "model": "msc", "provider_id": ""},
        },
        request_id="w5-craft", principal="", action="restore",
    )
    payload = asyncio.run(perform_switch(
        {"target": "primary", "rollback_to": str(time.time() + 10)},
        settings=s, http=_FakeHttp(), request_id="w5-rt", principal="tester",
        audit_log=""))
    assert payload["ok"] is True
    assert payload["switched"] == "rollback_to"
    # helm + scout restored from the entry...
    assert s.primary_api_url == "http://old-helm.test/v1/chat/completions"
    assert s.primary_model == "mh"
    assert s.scout_model == "msc"
    # ...but the never-bound specialist slot was left alone (not blanked)
    assert s.fallback_api_url == "http://work.test/v1/chat/completions"
    assert s.fallback_model == "mw"


# --- END PART 6 ---
# ---------------------------------------------------------------------------
# 7-9. hygiene pins
# ---------------------------------------------------------------------------
def test_providers_star_import_and_all_is_real():
    ns = {}
    exec("import providers; from providers import *", ns)  # used to ImportError
    import providers

    assert providers.__all__ == [
        "Event", "Target", "Provider", "Registry", "load_registry", "mask_key",
        "request_headers", "FROST_ALIASES", "MAX_THINK_NAMES", "resolve_frost_alias",
        "HUB_PROVIDERS", "HUB_MODEL_ALIASES", "resolve_hub_alias",
        "hub_models_for_listing",
    ]
    for name in providers.__all__:
        assert hasattr(providers, name), name


def test_hub_display_is_derived_from_hub_model_aliases():
    import providers

    expected = {
        "deepmaxnano": ("DeepMaxNano", "deepseek/deepseek-v4.1-flash", "nano", True),
        "glmmaxnano": ("GLMMaxNano", "zai-org/glm-5.3-flash", "nano", True),
        "deepnano": ("DeepNano", "deepseek/deepseek-v4.1-flash", "nano", False),
        "glmnano": ("GLMNano", "zai-org/glm-5.3-flash", "nano", False),
        "deepmaxablit.ai": ("DeepMaxAblit.ai", "abliterated-model-large", "ablit.ai", True),
        "glmmaxablit.ai": ("GLMMaxAblit.ai", "abliterated-model-large-v2", "ablit.ai", True),
        "deepablit.ai": ("DeepAblit.ai", "abliterated-model-large", "ablit.ai", False),
        "glmablit.ai": ("GLMAblit.ai", "abliterated-model-large-v2", "ablit.ai", False),
    }
    assert providers._HUB_DISPLAY == expected
    assert list(providers._HUB_DISPLAY) == list(providers.HUB_MODEL_ALIASES)
    listing = providers.hub_models_for_listing()
    assert [m["description"] for m in listing] == [
        "DeepMaxNano", "GLMMaxNano", "DeepNano", "GLMNano",
        "DeepMaxAblit.ai", "GLMMaxAblit.ai", "DeepAblit.ai", "GLMAblit.ai",
    ]
    # the derivation is total: an unknown stem never breaks the listing
    assert providers._hub_display_name("deepfrost") == "Deepfrost"


def test_dead_hygiene_is_gone():
    import proxy_gateway
    import speculative_hedge

    assert not hasattr(proxy_gateway, "Tier4Classifier")
    assert not hasattr(proxy_gateway, "TIER4")
    assert "requests_clean" not in proxy_gateway.metrics_snapshot()
    assert not hasattr(speculative_hedge, "buffered_text")


# --- END PART 7 ---
