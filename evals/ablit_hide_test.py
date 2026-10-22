"""HIDE_ABLIT_MODELS pins (operator directive 2026-10-22, TEMP).

The default catalog hides every entry whose id STARTS with "ablit" (the
ABLITV2L-helm chains and the abliterated registry ids); the ablit TERMINAL
hops of the remaining chains are untouched. =0 restores the full listing.
"""
from fastapi.testclient import TestClient

import proxy_gateway

ALL_CHAIN_IDS = [
    "GLMMAX>DEEP>ABLITV2L", "DEEPMAX>GLM>ABLITV2L",
    "ABLITV2L>SUB-GLM/DEEP", "GLMMAX>ABLIT-UNC>ABLITV2L",
    "RACE:DEEPMAX/GLMMAX>ABLITV2L", "GLMMAX-CONDUCTOR>DEEP+ABLITV2L",
    "ABLITV2L-HELM>GLM-PROBE>DEEP-VERIFY",
]


def _ids(monkeypatch, constellation_only=None, hide=None):
    if constellation_only is not None:
        monkeypatch.setenv("CONSTELLATION_ONLY", constellation_only)
    else:
        monkeypatch.delenv("CONSTELLATION_ONLY", raising=False)
    if hide is not None:
        monkeypatch.setenv("HIDE_ABLIT_MODELS", hide)
    else:
        monkeypatch.delenv("HIDE_ABLIT_MODELS", raising=False)
    with TestClient(proxy_gateway.app) as tc:
        return [m["id"] for m in tc.get("/v1/models").json()["data"]]


def test_default_catalog_hides_ablit_prefixed_ids(monkeypatch):
    ids = _ids(monkeypatch)
    assert ids, "the catalog must stay populated"
    assert not any(i.lower().startswith("ablit") for i in ids)
    # the ablit-TERMINAL chains stay visible (they do not START with ablit)
    assert "GLMMAX>DEEP>ABLITV2L" in ids
    assert "DEEPMAX>GLM>ABLITV2L" in ids
    assert "RACE:DEEPMAX/GLMMAX>ABLITV2L" in ids
    # exactly the two ablit-helm chains are hidden
    assert set(ALL_CHAIN_IDS) - set(ids) == {
        "ABLITV2L>SUB-GLM/DEEP", "ABLITV2L-HELM>GLM-PROBE>DEEP-VERIFY"}


def test_kill_switch_restores_the_full_catalog(monkeypatch):
    ids = _ids(monkeypatch, hide="0")
    assert sorted(ids) == sorted(ALL_CHAIN_IDS)


def test_legacy_catalog_branch_hides_ablit_too(monkeypatch):
    ids = _ids(monkeypatch, constellation_only="0")
    assert ids
    assert not any(i.lower().startswith("ablit") for i in ids)
    # the legacy branch keeps its real shapes (FROST_REGISTRY + the
    # lowercase hub aliases) - only ablit-prefixed ids would drop
    assert "deepfrost" in ids
    assert "deepmaxnano" in ids
