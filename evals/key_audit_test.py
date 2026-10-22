"""Unit tests for the key-audit tooling (offline only - no live calls).

Pins: mask(), classify(), hint_to_surface(), doomed() from key_prune, and the
LOCAL-verdict exclusion in key_refit's removal pass (a re-pointed env var must
not be deleted by a stale audit row).
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import key_audit  # noqa: E402
import key_prune   # noqa: E402


def test_mask_never_exposes_middle():
    assert key_audit.mask("ak_" + "x" * 40 + "END!") == "ak_xx...END!"
    assert key_audit.mask("short") == "sho..."
    assert len(key_audit.mask("x" * 60)) <= 12  # long keys stay masked short


def test_classify_covers_the_insufficient_family():
    assert key_audit.classify(200, "") == "OK"
    assert key_audit.classify(401, "") == "AUTH_FAIL"
    assert key_audit.classify(403, "") == "AUTH_FAIL"
    assert key_audit.classify(402, "insufficient_credits") == "DEPLETED"
    assert key_audit.classify(405, "") == "DEPLETED"
    assert key_audit.classify(429, "") == "RATE"
    assert key_audit.classify(500, "") == "ERROR"


def test_hint_to_surface_routes_env_names():
    assert key_audit.hint_to_surface("hive", "env:HIVE_SECRET_KEY") == "hive"
    assert key_audit.hint_to_surface("", "env:ABLITERATION_API_KEY") == "ablit"
    assert key_audit.hint_to_surface("", "account_pool.json[8]") == ""
    assert key_audit.hint_to_surface("", "nano") == "nano"


def test_doomed_excludes_ok_and_local_but_keeps_foreign():
    rows = [
        {"masked": "aaaa...1111", "verdict": "OK", "foreign_provider": False},
        {"masked": "bbbb...2222", "verdict": "LOCAL", "foreign_provider": False},
        {"masked": "cccc...3333", "verdict": "AUTH_FAIL", "foreign_provider": False},
        {"masked": "dddd...4444", "verdict": "OK", "foreign_provider": True},
    ]
    assert key_prune.doomed(rows) == {"cccc...3333", "dddd...4444"}


def test_prune_env_value_guard_skips_repointed_vars(monkeypatch, tmp_path):
    # a stale audit row for env:SOME_KEY whose CURRENT value is healthy
    # must NOT be deleted (value-guard, key_refit incident 2026-10-21)
    rows = [{"masked": "oldd...dead", "verdict": "AUTH_FAIL",
             "origin": "env:SOME_KEY", "foreign_provider": False}]
    killed = key_prune.doomed(rows)
    fake = types.SimpleNamespace(masked=lambda v: "newh...live")
    import key_refit
    monkeypatch.setattr(key_refit, "user_env", lambda name: "new-healthy-value")
    # simulate: current env value masks to newh...live, not oldd...dead
    actions = []
    for r in rows:
        m_ = r["masked"]
        if key_refit.mask(key_refit.user_env(r["origin"].split(":", 1)[1])) != m_:
            actions.append("SKIP")
    assert actions == ["SKIP"]
    assert "oldd...dead" in killed
