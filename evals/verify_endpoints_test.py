"""Offline tests for tools/hive/verify_endpoints.py (no network, no servers).

Coverage:
  - the PORTS table stays in lockstep with the serve_endpoints family
    (9310 general / 9314 deepfrost max think / 9315 glmfrost max think /
     9316 team always-on);
  - the --fast preset (_apply_fast) implies skip-chat/skip-execute, caps the
    timeout only when --timeout was left at its default, and is a no-op
    without --fast (legacy behavior preserved).
"""

import argparse
import importlib.util
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC_PATH = os.path.join(_ROOT, "tools", "hive", "verify_endpoints.py")
_SPEC = importlib.util.spec_from_file_location("verify_endpoints_under_test", _SPEC_PATH)
ve = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("verify_endpoints_under_test", ve)
_SPEC.loader.exec_module(ve)


# --- expected port family (serves as a regression pin) -----------------------
EXPECTED_PORTS = [
    (9310, "frost-general"),
    (9314, "deepfrost max think"),
    (9315, "glmfrost max think"),
    (9316, "team (always-on)"),
]


def test_ports_include_team_9316():
    # 9316 is the team surface (serve_endpoints.py REGISTRY) and MUST be probed.
    assert (9316, "team (always-on)") in ve.PORTS


def test_ports_table_matches_expected_family():
    assert list(ve.PORTS) == EXPECTED_PORTS


def test_ports_have_unique_numbers_and_names():
    ports = [p for p, _ in ve.PORTS]
    names = [n for _, n in ve.PORTS]
    assert len(ports) == len(set(ports)), "duplicate port in PORTS"
    assert len(names) == len(set(names)), "duplicate name in PORTS"


# --- --fast preset ------------------------------------------------------------
def _ns(**kw):
    """Build an argparse.Namespace shaped exactly like main()'s args."""
    base = dict(base="http://127.0.0.1:9000", ports_host="", timeout=ve.DEFAULT_TIMEOUT,
                skip_chat=False, skip_execute=False, skip_ports=False, fast=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_apply_fast_noop_when_flag_absent():
    args = _ns()
    ve._apply_fast(args)
    assert args.timeout == ve.DEFAULT_TIMEOUT
    assert args.skip_chat is False
    assert args.skip_execute is False


def test_apply_fast_implies_skip_chat_and_execute():
    args = _ns(fast=True)
    ve._apply_fast(args)
    assert args.skip_chat is True
    assert args.skip_execute is True
    # per-model port probes stay ON: the cheap liveness sweep is the point.
    assert args.skip_ports is False


def test_apply_fast_caps_default_timeout_only():
    args = _ns(fast=True)
    ve._apply_fast(args)
    assert args.timeout == ve.FAST_TIMEOUT


def test_apply_fast_explicit_timeout_wins():
    args = _ns(fast=True, timeout=30.0)
    ve._apply_fast(args)
    assert args.timeout == 30.0


def test_default_timeout_constant_unchanged():
    # The historical default (8.0s) must not drift for non-fast invocations.
    assert ve.DEFAULT_TIMEOUT == 8.0
    assert ve.FAST_TIMEOUT == 2.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
