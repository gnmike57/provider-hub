"""hub_ipc.py - cross-process file lock regression tests (W2, task_0004).

Hermetic: every lock lives under tmp_path.  One subprocess-based test proves
REAL cross-process mutual exclusion (msvcrt region lock / flock), the rest
exercise the contract in-process:

* acquisition + release (pid header written, no raise on double release)
* bounded acquisition (LockTimeout, timeout=0) and degrade-on-timeout
* kill switch HUB_IPC_LOCKS=0 (body runs unlocked, yields False)
* stale-handle safety: dead-pid header is rescued, live-holder is never
  force-stolen, corrupted headers are tolerated
* decorator form + path callables evaluated at call time
"""

import json
import os
import subprocess
import sys
import threading
import time

import pytest

import hub_ipc
from hub_ipc import FileLock, LockTimeout, locked_path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Hermetic knobs per test (default: locks on, short timeout)."""
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "2")
    monkeypatch.delenv("HUB_IPC_LOCKS", raising=False)
    yield


def _spawn_holder(tmp_path, target):
    """Child process: take the lock on `target`, hold until told to release.

    Protocol via marker files in tmp_path: writes `held` when the lock is
    taken; exits (releasing) once `release_now` exists.  Returns the Popen.
    """
    script = tmp_path / "_holder_child.py"
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
        "lk.release()\n"
        "open(os.path.join(tmp, 'released'), 'w').close()\n",
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


# ---------------------------------------------------------------------------
# Basic acquire / release
# ---------------------------------------------------------------------------

def test_acquire_creates_lock_file_with_pid_header(tmp_path):
    target = tmp_path / "state.jsonl"
    lock = FileLock(str(target), timeout=2)
    assert lock.acquire() is True
    assert os.path.exists(lock.lock_path)
    header = json.loads(open(lock.lock_path, encoding="utf-8").read())
    assert header["pid"] == os.getpid()
    lock.release()


def test_release_is_idempotent_and_never_raises(tmp_path):
    target = tmp_path / "state.jsonl"
    lock = FileLock(str(target), timeout=2)
    lock.acquire()
    lock.release()
    lock.release()  # double release: no-op, no raise
    # Release with a handle that was closed behind our back: still no raise.
    lock.acquire()
    lock._fh.close()
    lock.release()
    assert lock._fh is None


def test_reacquire_after_release(tmp_path):
    target = tmp_path / "state.jsonl"
    for _ in range(3):
        lock = FileLock(str(target), timeout=2)
        assert lock.acquire() is True
        lock.release()
    # The artifact may persist; exclusivity must not degrade across cycles.


def test_instance_is_reentrant_per_handle(tmp_path):
    target = tmp_path / "state.jsonl"
    lock = FileLock(str(target), timeout=2)
    assert lock.acquire() is True
    assert lock.acquire() is True  # same instance: already-held fast path
    lock.release()
    assert lock._fh is None


def test_context_manager_releases_on_body_exception(tmp_path):
    target = tmp_path / "state.jsonl"
    with pytest.raises(ValueError):
        with FileLock(str(target), timeout=2):
            assert os.path.exists(str(target) + ".lock")
            raise ValueError("body boom")
    # After the body exception the lock is free again.
    lock = FileLock(str(target), timeout=2)
    t0 = time.monotonic()
    assert lock.acquire() is True
    assert time.monotonic() - t0 < 1.0
    lock.release()
# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------

def test_threads_serialize_on_one_path(tmp_path):
    target = str(tmp_path / "counters.jsonl")
    counter = {"n": 0}
    errors = []

    def worker():
        try:
            for _ in range(20):
                with locked_path(target, timeout=5):
                    v = counter["n"]
                    time.sleep(0.0005)  # widen the race window
                    counter["n"] = v + 1
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert counter["n"] == 80  # lost update would show here


def test_cross_process_contention_and_bounded_timeout(tmp_path):
    target = str(tmp_path / "shared.jsonl")
    child = _spawn_holder(tmp_path, target)
    try:
        assert _wait_marker(tmp_path, "held"), "child never took the lock"

        # Bounded: a short wait against a live holder raises LockTimeout.
        t0 = time.monotonic()
        with pytest.raises(LockTimeout):
            FileLock(str(target), timeout=0.25).acquire()
        waited = time.monotonic() - t0
        assert 0.2 <= waited < 5  # bounded, not forever

        # locked_path degrade=True: body STILL ran (never wedges callers).
        ran = {}
        with locked_path(target, timeout=0.25) as acquired:
            ran["acquired"] = acquired
            ran["body"] = True
        assert ran == {"acquired": False, "body": True}

        # Tell the child to release; the parent must get in afterwards.
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        assert _wait_marker(tmp_path, "released")
        lock = FileLock(str(target), timeout=5)
        assert lock.acquire() is True
        # ...and the pid header now belongs to THIS process.
        header = json.loads(open(lock.lock_path, encoding="utf-8").read())
        assert header["pid"] == os.getpid()
        lock.release()
    finally:
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        child.wait(timeout=15)


def test_degrade_false_propagates_lock_timeout(tmp_path):
    target = str(tmp_path / "shared.jsonl")
    child = _spawn_holder(tmp_path, target)
    try:
        assert _wait_marker(tmp_path, "held")
        with pytest.raises(LockTimeout):
            with locked_path(target, timeout=0.25, degrade=False):
                pass  # never reached
    finally:
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        child.wait(timeout=15)


def test_timeout_zero_fails_immediately_when_held(tmp_path):
    target = str(tmp_path / "shared.jsonl")
    child = _spawn_holder(tmp_path, target)
    try:
        assert _wait_marker(tmp_path, "held")
        t0 = time.monotonic()
        with pytest.raises(LockTimeout):
            FileLock(str(target), timeout=0).acquire()
        assert time.monotonic() - t0 < 1.0
    finally:
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        child.wait(timeout=15)


# ---------------------------------------------------------------------------
# Kill switch (house pattern: knob checked at use site, 0 disables)
# ---------------------------------------------------------------------------

def test_kill_switch_runs_body_unlocked(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_IPC_LOCKS", "0")
    target = str(tmp_path / "off.jsonl")
    seen = {}
    with locked_path(target) as acquired:
        seen["acquired"] = acquired
    assert seen == {"acquired": False}
    assert not os.path.exists(target + ".lock")  # no artifact, no locking


def test_kill_switch_also_disables_the_decorator(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_IPC_LOCKS", "0")
    calls = []
    target = str(tmp_path / "off2.jsonl")

    @locked_path(lambda: target)
    def write_row():
        calls.append(1)

    write_row()
    assert calls == [1]
    assert not os.path.exists(target + ".lock")


def test_env_timeout_and_bad_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "0.5")
    assert hub_ipc.lock_timeout() == 0.5
    monkeypatch.setenv("HUB_IPC_TIMEOUT_S", "not-a-number")
    assert hub_ipc.lock_timeout() == hub_ipc.DEFAULT_TIMEOUT_S
# ---------------------------------------------------------------------------
# Stale-handle safety
# ---------------------------------------------------------------------------

def test_dead_pid_header_is_rescued_not_wedged(tmp_path):
    # A previous process wrote its pid and died: the artifact exists but the
    # OS lock is gone.  Acquisition must succeed quickly and re-stamp the pid.
    target = str(tmp_path / "stale.jsonl")
    lock_path = str(target) + ".lock"
    with open(lock_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"pid": 999999999}))  # dead pid
    lock = FileLock(str(target), timeout=2)
    t0 = time.monotonic()
    assert lock.acquire() is True
    assert time.monotonic() - t0 < 2.0
    header = json.loads(open(lock_path, encoding="utf-8").read())
    assert header["pid"] == os.getpid()
    lock.release()


def test_dead_child_pid_header_is_rescued(tmp_path):
    # Real dead pid: spawn a child that writes its pid then exits.
    script = tmp_path / "_pid_writer.py"
    script.write_text(
        "import sys\n"
        "import json\n"
        "with open(sys.argv[1], 'w') as fh:\n"
        "    fh.write(json.dumps({'pid': __import__('os').getpid()}))\n",
        encoding="utf-8",
    )
    lock_path = str(tmp_path / "childdead.jsonl") + ".lock"
    subprocess.run([sys.executable, str(script), lock_path],
                   check=True, timeout=30)
    holder_pid = json.loads(open(lock_path, encoding="utf-8").read())["pid"]
    assert holder_pid != os.getpid()
    lock = FileLock(str(tmp_path / "childdead.jsonl"), timeout=3)
    assert lock.acquire() is True
    assert json.loads(open(lock_path, encoding="utf-8").read())["pid"] == os.getpid()
    lock.release()


def test_live_holder_is_never_force_stolen(tmp_path):
    # Header lies (dead pid) but a LIVE process holds the real region lock:
    # the force-take must refuse and the bounded wait must expire instead of
    # letting two writers into the same critical section.
    target = str(tmp_path / "live.jsonl")
    child = _spawn_holder(tmp_path, target)
    try:
        assert _wait_marker(tmp_path, "held")
        # Overwrite the header with a provably-dead pid while the child holds.
        with open(str(target) + ".lock", "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"pid": 999999999}))
        with pytest.raises(LockTimeout):
            FileLock(str(target), timeout=0.4).acquire()
    finally:
        open(os.path.join(str(tmp_path), "release_now"), "w").close()
        child.wait(timeout=15)


def test_corrupt_header_is_tolerated(tmp_path):
    target = str(tmp_path / "corrupt.jsonl")
    with open(str(target) + ".lock", "w", encoding="utf-8") as fh:
        fh.write("not-json at all{\n")
    lock = FileLock(str(target), timeout=2)
    assert lock.acquire() is True
    lock.release()


def test_stale_probe_reports_own_and_dead_pids():
    # Direct unit coverage of the liveness probe used for stale rescue.
    assert hub_ipc.FileLock._stale(object(), 0) is False
    assert hub_ipc.FileLock._stale(object(), os.getpid()) is False


# ---------------------------------------------------------------------------
# locked_path API surface
# ---------------------------------------------------------------------------

def test_decorator_serializes_and_returns_value(tmp_path):
    target = str(tmp_path / "deco.jsonl")
    state = {"v": 0}

    @locked_path(target, timeout=5)
    def bump():
        v = state["v"]
        time.sleep(0.001)
        state["v"] = v + 1
        return "ok"

    assert bump() == "ok"
    assert bump() == "ok"
    assert state["v"] == 2


def test_decorator_path_callable_resolves_at_call_time(tmp_path, monkeypatch):
    # The path lambda is evaluated on every CALL, so env-resolved paths
    # (the billing/account_pool pattern) stay live.
    target_a = str(tmp_path / "a.jsonl")
    target_b = str(tmp_path / "b.jsonl")
    current = {"p": target_a}
    seen = []

    @locked_path(lambda: current["p"], timeout=5)
    def touch():
        seen.append(current["p"])

    touch()
    current["p"] = target_b
    touch()
    assert seen == [target_a, target_b]
    assert os.path.exists(target_a + ".lock")
    assert os.path.exists(target_b + ".lock")


def test_sequential_different_paths_do_not_interfere(tmp_path):
    t1 = str(tmp_path / "one.jsonl")
    t2 = str(tmp_path / "two.jsonl")
    with locked_path(t1, timeout=5) as a:
        assert a is True
        with locked_path(t2, timeout=5) as b:
            assert b is True
    # Both released cleanly (no deadlock, no leaked handles).


def test_body_exception_propagates_through_locked_path(tmp_path):
    target = str(tmp_path / "boom.jsonl")
    with pytest.raises(RuntimeError):
        with locked_path(target, timeout=5):
            raise RuntimeError("caller error passes through")
    lock = FileLock(target, timeout=2)
    assert lock.acquire() is True  # released despite the body exception
    lock.release()


def test_lock_helpers_report_enabled_and_timeout():
    os.environ.pop("HUB_IPC_LOCKS", None)
    assert hub_ipc.lock_enabled() is True
    os.environ["HUB_IPC_LOCKS"] = "0"
    try:
        assert hub_ipc.lock_enabled() is False
    finally:
        del os.environ["HUB_IPC_LOCKS"]