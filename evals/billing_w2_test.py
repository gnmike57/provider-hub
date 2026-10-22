"""billing.py W2 additions - cross-process lock + append fast path (task_0004).

Hermetic regression tests for the additive W2 behaviour ONLY (existing
billing tests in constellation_test/money_guard_test/stage0_restore_test are
untouched and keep covering the base class):

* knob defaults: BILLING_COMPACT_INTERVAL unset -> full-rewrite path on every
  record(); BILLING_FILE_LOCKS on by default.
* kill switches: BILLING_COMPACT_INTERVAL=0 and BILLING_FILE_LOCKS=0 preserve
  the pre-W2 behaviour exactly.
* append fast path equivalence: file content + user_usage()/system_usage()
  identical to the full-rewrite path for the same event stream.
* cross-process serialization: hub_ipc lock is taken around persist sites
  (holder process blocks the write until it releases).
* degrade-on-LockTimeout: write STILL happens (unlocked) - never-raises
  billing persists.
* UsageTracker record() keeps its OSError-swallowing contract on both paths.
* account_pool metrics_snapshot(): new counter names only, never raises.
"""

import json
import os
import subprocess
import sys
import threading
import time

import pytest

import billing
import hub_ipc


@pytest.fixture()
def ub(tmp_path, monkeypatch):
    """UserBilling on a private file with locks + default (rewrite) path."""
    monkeypatch.delenv("BILLING_COMPACT_INTERVAL", raising=False)
    monkeypatch.delenv("BILLING_FILE_LOCKS", raising=False)
    monkeypatch.delenv("HUB_IPC_LOCKS", raising=False)
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "2")
    return billing.UserBilling(path=str(tmp_path / "users.jsonl"))


@pytest.fixture()
def ut(tmp_path, monkeypatch):
    """UsageTracker on a private file with default (full-rewrite) path."""
    monkeypatch.delenv("BILLING_COMPACT_INTERVAL", raising=False)
    monkeypatch.delenv("BILLING_FILE_LOCKS", raising=False)
    monkeypatch.delenv("HUB_IPC_LOCKS", raising=False)
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "2")
    return billing.UsageTracker(path=str(tmp_path / "usage.jsonl"))


# ---------------------------------------------------------------------------
# Knob defaults (hard law: default = historical behaviour)
# ---------------------------------------------------------------------------

def test_compact_interval_defaults_to_zero(monkeypatch):
    monkeypatch.delenv("BILLING_COMPACT_INTERVAL", raising=False)
    assert billing.BILLING_COMPACT_INTERVAL == 0


def test_file_locks_default_on_and_parse():
    assert billing.BILLING_FILE_LOCKS is True


def test_record_default_path_is_full_rewrite(ut):
    # Default (interval unset/0): the file is the full tail snapshot - the
    # historical _atomic_write_jsonl semantics, byte-for-byte.
    ut.record("u1", "m", 1, 2, 0.5, "hive", "r1")
    ut.record("u2", "m", 3, 4, 0.25, "ablit", "r2")
    lines = open(ut.path, encoding="utf-8").read().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["user_id"] == "u1"
    assert json.loads(lines[1])["user_id"] == "u2"
    assert [json.loads(l)["request_id"] for l in lines] == ["r1", "r2"]


# ---------------------------------------------------------------------------
# Append fast path (BILLING_COMPACT_INTERVAL >= 1)
# ---------------------------------------------------------------------------

def _stream(ut, n, prefix="u"):
    for i in range(n):
        ut.record(f"{prefix}{i % 3}", "model", i, i, 0.01 * i, "hive", f"req-{i}")


def test_fast_path_appends_and_compacts_on_interval(ut, monkeypatch):
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 3)
    _stream(ut, 7)
    # 7 events; compaction fired at event 3 and 6 -> file rewritten then.
    lines = open(ut.path, encoding="utf-8").read().splitlines()
    # After the last compaction (event 6) one more append (event 7) happened:
    # the file holds events 1..6 compacted + event 7 appended = 7 lines.
    assert len(lines) == 7
    assert [json.loads(l)["request_id"] for l in lines] == [f"req-{i}" for i in range(7)]


def test_fast_path_in_memory_events_stay_authoritative(ut, monkeypatch):
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 2)
    _stream(ut, 5)
    assert len(ut._events) == 5
    assert ut.system_usage()["total_requests"] == 5


def test_fast_path_tail_cap_still_enforced_on_compact(tmp_path, monkeypatch):
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 1)
    tracker = billing.UsageTracker(path=str(tmp_path / "cap.jsonl"))
    _stream(tracker, 5, prefix="cap")
    # Every event compacts with tail=10000; small stream -> all rows present.
    assert len(open(tracker.path, encoding="utf-8").read().splitlines()) == 5


def test_record_never_raises_on_append_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 3)
    tracker = billing.UsageTracker(path=str(tmp_path / "boom.jsonl"))

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(billing, "_append_and_maybe_compact", boom)
    tracker.record("u", "m", 1, 1, 0.1, "hive")  # must not raise
    assert tracker.system_usage()["total_requests"] == 1


def test_record_never_raises_on_rewrite_failure(ut, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(billing, "_persist_jsonl", boom)
    ut.record("u", "m", 1, 1, 0.1, "hive")  # must not raise (historical pact)
    assert ut.system_usage()["total_requests"] == 1


def test_append_fast_path_survives_process_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 2)
    tracker = billing.UsageTracker(path=str(tmp_path / "restart.jsonl"))
    _stream(tracker, 3, prefix="rs")
    # Fresh tracker over the same file: _load() reads appended rows back.
    again = billing.UsageTracker(path=str(tmp_path / "restart.jsonl"))
    assert again.system_usage()["total_requests"] == 3
# ---------------------------------------------------------------------------
# Fast-path vs full-rewrite equivalence (fixed clock -> byte-identical files)
# ---------------------------------------------------------------------------

def test_fast_path_equivalence_with_fixed_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "2")
    fixed = "2026-10-21T00:00:00+00:00"
    monkeypatch.setattr(billing, "_now", lambda: fixed)

    a = billing.UsageTracker(path=str(tmp_path / "fast2.jsonl"))
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 4)
    _stream(a, 11, prefix="eq")
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 0)
    b = billing.UsageTracker(path=str(tmp_path / "slow2.jsonl"))
    _stream(b, 11, prefix="eq")
    assert open(a.path, encoding="utf-8").read() == open(b.path, encoding="utf-8").read()
    assert a.user_usage("eq1") == b.user_usage("eq1")
    assert a.system_usage() == b.system_usage()


def test_kill_switch_zero_keeps_rewrite_path(ut, monkeypatch):
    monkeypatch.setattr(billing, "BILLING_COMPACT_INTERVAL", 0)
    _stream(ut, 6)
    lines = open(ut.path, encoding="utf-8").read().splitlines()
    assert len(lines) == 6  # full rewrite each event: exactly one row each


def test_billing_file_locks_zero_skips_locking(tmp_path, monkeypatch):
    monkeypatch.setenv("BILLING_FILE_LOCKS", "0")
    path = str(tmp_path / "nolock.jsonl")
    tracker = billing.UsageTracker(path=path)
    tracker.record("u", "m", 1, 1, 0.1, "hive")
    assert not os.path.exists(path + ".lock")  # pre-W2: no lock artifacts
    assert len(open(path, encoding="utf-8").read().splitlines()) == 1


# ---------------------------------------------------------------------------
# Cross-process serialization + degrade
# ---------------------------------------------------------------------------

def _spawn_holder(tmp_path, target):
    script = tmp_path / "_bill_holder.py"
    script.write_text(
        "import sys, time, os\n"
        "import hub_ipc\n"
        "target, tmp = sys.argv[1], sys.argv[2]\n"
        "lk = hub_ipc.FileLock(target, timeout=10)\n"
        "lk.acquire()\n"
        "open(os.path.join(tmp, 'held'), 'w').close()\n"
        "deadline = time.time() + 15\n"
        "while not os.path.exists(os.path.join(tmp, 'release_now')):\n"
        "    if time.time() > deadline:\n"
        "        break\n"
        "    time.sleep(0.02)\n"
        "lk.release()\n",
        encoding="utf-8",
    )
    return subprocess.Popen(
        [sys.executable, str(script), str(target), str(tmp_path)],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env={**os.environ,
             "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))},
    )


def _wait_marker(tmp_path, name, timeout=15.0):
    p = os.path.join(str(tmp_path), name)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(p):
            return True
        time.sleep(0.02)
    return False


def test_persist_waits_for_cross_process_holder(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "10")
    path = str(tmp_path / "contended.jsonl")
    child = _spawn_holder(tmp_path, path)
    try:
        assert _wait_marker(tmp_path, "held")
        done = {}

        def writer():
            tracker = billing.UsageTracker(path=path)
            tracker.record("u", "m", 1, 1, 0.1, "hive")
            done["ok"] = True

        t = threading.Thread(target=writer)
        t0 = time.monotonic()
        t.start()
        time.sleep(0.4)  # holder still owns the file lock
        assert not done  # writer is blocked on the cross-process lock...
        # 2026-10-23 tolerance fix: Windows timer granularity measured the
        # 0.4s sleep as 0.391s elapsed (a boundary flake); the invariant
        # is "the writer stayed blocked for (almost) the whole sleep", not
        # the exact boundary.
        assert time.monotonic() - t0 >= 0.3
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        t.join(timeout=20)
        assert done.get("ok")  # ...and completes once released
        assert len(open(path, encoding="utf-8").read().splitlines()) == 1
    finally:
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        child.wait(timeout=15)


def test_persist_degrades_to_unlocked_write_on_lock_timeout(tmp_path, monkeypatch):
    # Lock budget exhausted -> the historical unlocked write must still land
    # (billing never raises, never silently drops a persist).
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "0.3")
    path = str(tmp_path / "degrade.jsonl")
    child = _spawn_holder(tmp_path, path)
    try:
        assert _wait_marker(tmp_path, "held")
        t0 = time.monotonic()
        billing._persist_jsonl(path, [{"user_id": "u", "n": 1}])
        took = time.monotonic() - t0
        assert 0.25 <= took < 5  # bounded wait, then degrade
        assert len(open(path, encoding="utf-8").read().splitlines()) == 1
    finally:
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        child.wait(timeout=15)
def test_userbilling_persist_roundtrip_with_locks(ub):
    ub.get_or_create("alice")
    ub.deduct("alice", 10, 0.25)
    ub.add_credits("alice", 1.0, "admin")
    again = billing.UserBilling(path=ub.path)
    assert round(again.get_balance("alice"), 6) == round(
        ub.get_balance("alice"), 6)


def test_keyvault_store_still_never_raises_on_write_failure(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet as _F
    monkeypatch.setenv("ENCRYPTION_KEY", _F.generate_key().decode())
    vault = billing.KeyVault(path=str(tmp_path / "keys.jsonl"))

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(billing, "_persist_jsonl", boom)
    vault.store_key("u", "hive", "secret")  # must not raise
    assert vault.get_key("u", "hive") == "secret"  # in-memory read still works


def test_deduct_persists_through_persist_jsonl(ub):
    ub.get_or_create("bob")
    before = ub.get_balance("bob")
    ub.deduct("bob", 5, 0.10)
    assert ub.get_balance("bob") == before - 0.10
    # File got the updated row through the locked wrapper.
    rows = [json.loads(l) for l in open(ub.path, encoding="utf-8") if l.strip()]
    assert rows[-1]["user_id"] == "bob"


# ---------------------------------------------------------------------------
# account_pool additive metrics (W2)
# ---------------------------------------------------------------------------

def test_metrics_snapshot_keys_are_new_names_only():
    import account_pool

    snap = account_pool.metrics_snapshot()
    assert isinstance(snap, dict) and snap
    # Existing public API keys in pool_summary() are untouched (superset law):
    summary = account_pool.pool_summary()
    for legacy in ("enabled", "size", "accounts"):
        assert legacy in summary
    for name in ("pick_attempts", "pick_sticky_hit", "pick_wlif_fallback",
                 "pick_no_token", "pick_empty_pool", "sticky_divert",
                 "acquire_none", "reload_file", "reload_env",
                 "reload_locked", "reload_lock_skipped",
                 "depleted_events", "cooldown_events"):
        assert name in snap


def test_metrics_counters_move_on_pick_and_result(monkeypatch):
    import account_pool

    monkeypatch.setenv("ACCOUNT_POOL_ENABLED", "1")
    monkeypatch.setenv("ACCOUNT_POOL_KEYS", "hive:aaaa==")
    account_pool.reset_metrics()
    account_pool.reload_pool()
    acct = account_pool.POOL.acquire("https://api.thehive.ai/v1", "route-1")
    assert acct is not None
    snap = account_pool.metrics_snapshot()
    assert snap["pick_attempts"] >= 1
    assert snap["pick_sticky_hit"] >= 1
    assert snap["reload_env"] >= 1
    account_pool.observe_result(acct, 429)
    assert account_pool.metrics_snapshot()["cooldown_events"] >= 1
    account_pool.observe_result(acct, 402)
    assert account_pool.metrics_snapshot()["depleted_events"] >= 1


def test_metrics_kill_switch_freezes_counters(monkeypatch):
    import account_pool

    monkeypatch.setenv("ACCOUNT_POOL_METRICS", "0")
    before = account_pool.metrics_snapshot()
    account_pool._bump("pick_attempts", 5)
    assert account_pool.metrics_snapshot() == before


def test_metrics_bump_never_raises(monkeypatch):
    import account_pool

    monkeypatch.setenv("ACCOUNT_POOL_METRICS", "1")

    class Bad:
        def __enter__(self):
            raise RuntimeError("lock exploded")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(account_pool, "_METRICS_LOCK", Bad())
    account_pool._bump("pick_attempts", 1)  # must not raise (rule 7)
    monkeypatch.setattr(account_pool, "_METRICS_LOCK", threading.Lock())


def test_pool_reload_runs_locked_by_default(tmp_path, monkeypatch):
    import account_pool

    monkeypatch.setenv("ACCOUNT_POOL_ENABLED", "1")
    monkeypatch.delenv("ACCOUNT_POOL_KEYS", raising=False)
    monkeypatch.delenv("HUB_IPC_LOCKS", raising=False)
    # Private pool file (conftest quarantine law: never touch the repo's
    # production account_pool.json from a test).
    pool_file = tmp_path / "pool.json"
    pool_file.write_text('{"accounts": [{"provider": "hive", "key": "zz=="}]}',
                         encoding="utf-8")
    monkeypatch.setenv("ACCOUNT_POOL_FILE", str(pool_file))
    account_pool.reset_metrics()
    account_pool.reload_pool()
    snap = account_pool.metrics_snapshot()
    assert snap["reload_file"] >= 1
    assert snap["reload_locked"] >= 1  # default: locks on -> locked reload
    assert account_pool.POOL.acquire("https://api.thehive.ai/v1", "rk") is not None


def test_pool_reload_lock_skipped_when_hub_ipc_disabled(tmp_path, monkeypatch):
    import account_pool

    monkeypatch.setenv("ACCOUNT_POOL_ENABLED", "1")
    monkeypatch.delenv("ACCOUNT_POOL_KEYS", raising=False)
    monkeypatch.setenv("HUB_IPC_LOCKS", "0")
    pool_file = tmp_path / "pool2.json"
    pool_file.write_text('{"accounts": [{"provider": "hive", "key": "zz=="}]}',
                         encoding="utf-8")
    monkeypatch.setenv("ACCOUNT_POOL_FILE", str(pool_file))
    account_pool.reset_metrics()
    account_pool.reload_pool()
    snap = account_pool.metrics_snapshot()
    assert snap["reload_file"] >= 1
    assert snap["reload_lock_skipped"] >= 1  # kill switch honoured
    assert not os.path.exists(str(pool_file) + ".lock")  # no artifacts at all


def test_pool_fail_closed_unchanged_with_locks(monkeypatch):
    import account_pool

    monkeypatch.setenv("ACCOUNT_POOL_ENABLED", "1")
    monkeypatch.setenv("ACCOUNT_POOL_KEYS", "hive:bbbb==")
    account_pool.reload_pool()
    headers, acct = account_pool.routed_headers(
        {"x-old": "1"}, "https://api.thehive.ai/v1", "rk")
    assert headers["Authorization"] == "Bearer bbbb=="
    assert acct is not None
    account_pool.observe_result(acct, 401)
    headers2, acct2 = account_pool.routed_headers(
        {"x-old": "1"}, "https://api.thehive.ai/v1", "rk")
    assert acct2 is None and headers2 == {"x-old": "1"}  # fail-closed preserved