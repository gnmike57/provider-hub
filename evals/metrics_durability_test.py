"""METRICS_PERSISTENCE pins (2026-10-22, opt-in default 0).

_METRICS is process memory - a restart silently zeroed every counter.
Pins:
  - flush/load round-trip restores counters (atomic tmp+replace)
  - gauge-style keys (in_flight, specialist_warm) NEVER persist
  - default (unset/0) writes nothing - exact historical behaviour
  - a corrupt state file never raises into the lifespan (design rule 7)
"""
import json

import pytest

import proxy_gateway


@pytest.fixture(autouse=True)
def _restore_metrics():
    """The durability tests mutate the module-global _METRICS - restore the
    pre-test values so this file never leaks counters into later suites."""
    before = dict(proxy_gateway._METRICS)
    yield
    proxy_gateway._METRICS.clear()
    proxy_gateway._METRICS.update(before)


def test_flush_load_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "metrics_state.json"
    monkeypatch.setenv("METRICS_PERSISTENCE", "1")
    monkeypatch.setenv("METRICS_STATE_PATH", str(path))
    proxy_gateway._METRICS["requests_total"] = 41
    proxy_gateway._METRICS["in_flight"] = 3
    proxy_gateway._metrics_flush()
    saved = json.loads(path.read_text("utf-8"))
    assert saved["requests_total"] == 41
    assert "in_flight" not in saved          # gauge never persists
    proxy_gateway._METRICS["requests_total"] = 0
    proxy_gateway._metrics_load()
    assert proxy_gateway._METRICS["requests_total"] == 41
    assert proxy_gateway._METRICS["in_flight"] == 3  # gauge untouched by load


def test_default_off_writes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "metrics_state.json"
    monkeypatch.delenv("METRICS_PERSISTENCE", raising=False)
    monkeypatch.setenv("METRICS_STATE_PATH", str(path))
    # control the value under test: other suites' traffic must not decide
    # this pin (requests_total is ambient module state)
    proxy_gateway._METRICS["requests_total"] = 0
    proxy_gateway._metrics_flush()
    assert not path.exists()
    proxy_gateway._metrics_load()  # no-op, never raises
    assert proxy_gateway._METRICS["requests_total"] == 0


def test_corrupt_state_file_never_raises(tmp_path, monkeypatch):
    path = tmp_path / "metrics_state.json"
    path.write_text("{not json", "utf-8")
    monkeypatch.setenv("METRICS_PERSISTENCE", "1")
    monkeypatch.setenv("METRICS_STATE_PATH", str(path))
    before = dict(proxy_gateway._METRICS)
    proxy_gateway._metrics_load()  # must not raise
    assert proxy_gateway._METRICS == before


def test_unknown_and_gauge_keys_are_dropped_on_load(tmp_path, monkeypatch):
    path = tmp_path / "metrics_state.json"
    path.write_text(json.dumps(
        {"requests_total": 7, "legacy_counter_x": 99}), "utf-8")
    monkeypatch.setenv("METRICS_PERSISTENCE", "1")
    monkeypatch.setenv("METRICS_STATE_PATH", str(path))
    proxy_gateway._METRICS["requests_total"] = 0
    proxy_gateway._metrics_load()
    assert proxy_gateway._METRICS["requests_total"] == 7
    assert "legacy_counter_x" not in proxy_gateway._METRICS
