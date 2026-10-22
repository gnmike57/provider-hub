"""Cross-process file locks (hub_ipc) - one purpose, no dependencies.

The hub's state files (billing.py users/usage JSONL, account_pool.json) are
written by potentially several processes: the gateway, admin CLIs, and test
harnesses.  ``os.replace`` makes each single write atomic, but two processes
replacing the same path concurrently can still lose one side's rows entirely.
hub_ipc adds the missing mutual exclusion: an advisory, best-effort lock file
per protected path.

Design (kept deliberately small):

* ``FileLock`` - advisory lock on ``<target>.lock``.  On Windows the critical
  section is guarded with ``msvcrt.locking``; on POSIX with ``fcntl.flock``.
  Both are advisory: a writer that never takes the lock is not stopped, so
  every writer must cooperate through :func:`locked_path`.
* ``locked_path()`` - context manager + decorator.  Decorated write helpers
  serialize across processes with zero per-caller boilerplate.
* Bounded acquisition: ``HUB_IPC_TIMEOUT_S`` (default 10) caps how long a
  caller blocks.  On timeout, ``locked_path`` DEGRADES to running unprotected
  rather than raising into egress/billing paths (house rule: hooks never
  raise); ``FileLock.acquire()`` itself surfaces :class:`LockTimeout` for
  direct users.
* Crash safety: a lock file whose recorded holder pid is provably dead is
  force-opened, so a killed gateway cannot wedge billing forever.  When pid
  liveness cannot be proven, the timeout still bounds the wait.

Env knobs (read at use site, house kill-switch pattern):
    HUB_IPC_LOCKS       "0" disables locking entirely - ``locked_path`` then
                        runs the body immediately (default "1").
    HUB_IPC_TIMEOUT_S   seconds to wait for the lock before degrading
                        (float, default 10.0).

Never-raises contract: :func:`locked_path` never propagates an exception from
the locking machinery itself (only body exceptions pass through); ``release``
is best-effort and swallows everything.
"""

import errno
import json
import os
import time
from contextlib import contextmanager

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # POSIX
    _msvcrt = None

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None

__all__ = ["FileLock", "LockTimeout", "locked_path", "lock_enabled",
           "lock_timeout"]

DEFAULT_TIMEOUT_S = 10.0
# Windows: the exclusive byte-range lock lives at this offset in the lock
# file, far from the pid header at offset 0.  Windows region locks block ALL
# other handles' reads/writes on the locked range, so locking byte 0 would
# hide the header from contenders (and break stale-pid rescue).  Locking a
# byte beyond EOF is legal and keeps the header freely readable.
_LOCK_BYTE_OFFSET = 512

# msvcrt.LK_NBLCK is the non-blocking region lock used for the poll loop.
_LK_NBLCK = getattr(_msvcrt, "LK_NBLCK", 0) if _msvcrt else 0


def lock_enabled() -> bool:
    """Kill switch: HUB_IPC_LOCKS=0 turns every lock into a no-op."""
    return os.getenv("HUB_IPC_LOCKS", "1") != "0"


def lock_timeout() -> float:
    """Bounded wait for lock acquisition (seconds)."""
    try:
        return max(0.0, float(os.getenv("HUB_IPC_TIMEOUT_S", "") or DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


class LockTimeout(RuntimeError):
    """Raised by FileLock.acquire when the lock could not be taken in time."""


class FileLock:
    """Advisory cross-process lock around one target path.

    The lock artifact is ``<target>.lock`` beside the protected file.  On
    POSIX the exclusivity comes from ``flock``; on Windows from ``msvcrt``
    region locking plus a pid header (which also powers stale-lock rescue:
    a lock held by a dead pid is force-released).
    """

    def __init__(self, target_path: str, timeout: float = None):
        self.target_path = os.path.abspath(target_path)
        self.timeout = lock_timeout() if timeout is None else float(timeout)
        self._lock_path = self.target_path + ".lock"
        self._fh = None

    @property
    def lock_path(self) -> str:
        return self._lock_path

    # -- acquisition ------------------------------------------------------
    def acquire(self) -> bool:
        """Take the lock, polling up to ``self.timeout`` seconds.

        Returns True when held.  Raises :class:`LockTimeout` when the wait
        budget is exhausted; raises OSError only for unexpected I/O errors.
        """
        if self._fh is not None:
            return True  # already held (re-entrant per FileLock instance)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if self._try_once():
                    return True
            except (OSError, ValueError):
                pass  # transient (e.g. lock file vanished): retry
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"hub_ipc: could not acquire {self._lock_path} "
                    f"within {self.timeout}s"
                )
            time.sleep(0.01)

    def _try_once(self) -> bool:
        """One non-blocking acquisition attempt on the platform backend."""
        if _msvcrt is not None:
            return self._try_once_windows()
        return self._try_once_posix()

    def _open_lock_file(self):
        # r+ keeps the pid header readable; create when missing.
        if os.path.exists(self._lock_path):
            return open(self._lock_path, "r+", encoding="utf-8")
        return open(self._lock_path, "w+", encoding="utf-8")

    def _read_holder_pid(self, fh) -> int:
        try:
            fh.seek(0)
            raw = fh.read(64).strip()
            return int(json.loads(raw)["pid"]) if raw else 0
        except (ValueError, OSError, AttributeError, TypeError):
            return 0

    def _write_header(self, fh) -> None:
        """(Re)stamp the pid header.  Truncates stale longer content so the
        first line is always parseable JSON."""
        payload = json.dumps({"pid": os.getpid()})
        fh.seek(0)
        fh.write(payload)
        fh.truncate(len(payload))
        fh.seek(0)

    def _try_once_windows(self) -> bool:
        # The exclusive region lock sits FAR from the pid header (offset
        # _LOCK_BYTE_OFFSET): Windows byte-range locks also block other
        # handles' read()/write() on the locked region, so locking byte 0
        # would make the header unreadable to contenders.  A far byte keeps
        # the header inspectable for stale-pid rescue while the OS lock
        # still arbitrates exclusivity.  Locking beyond EOF is legal.
        fh = self._open_lock_file()
        try:
            try:
                fh.seek(_LOCK_BYTE_OFFSET)
                _msvcrt.locking(fh.fileno(), _LK_NBLCK, 1)
            except OSError as exc:
                fh.close()
                if exc.errno not in (errno.EACCES, errno.EDEADLK):
                    return False
                holder = 0
                try:
                    with open(self._lock_path, "r", encoding="utf-8") as pf:
                        holder = self._read_holder_pid(pf)
                except OSError:
                    holder = 0
                if self._stale(holder):
                    return self._force_take()
                return False  # someone live holds it: keep waiting
            self._write_header(fh)
            self._fh = fh
            return True
        except Exception:
            try:
                fh.close()
            except OSError:
                pass
            raise

    def _try_once_posix(self) -> bool:
        fh = self._open_lock_file()
        try:
            try:
                _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except OSError as exc:
                fh.close()
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    return False  # someone else holds it: keep waiting
                raise
            self._write_header(fh)
            self._fh = fh
            return True
        except Exception:
            try:
                fh.close()
            except OSError:
                pass
            raise

    def _stale(self, holder_pid: int) -> bool:
        """True when the recorded holder pid provably no longer exists."""
        if not holder_pid or holder_pid == os.getpid():
            return False
        if _fcntl is not None:
            try:
                os.kill(holder_pid, 0)
                return False  # alive
            except ProcessLookupError:
                return True  # dead: safe to force
            except OSError:
                return False  # cannot prove: do not force
        # Windows: pid liveness via kernel32.OpenProcess (PROCESS_QUERY_
        # LIMITED_INFORMATION).  GetLastError()==87 (ERROR_INVALID_PARAMETER)
        # is how Windows reports a nonexistent pid.  When the probe is
        # unavailable we conservatively report "not provably stale" and let
        # the timeout bound the wait instead of stealing a live lock.
        try:
            import ctypes  # stdlib only, lazy

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, 0, holder_pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return False  # alive
            return ctypes.windll.kernel32.GetLastError() == 87
        except Exception:
            return False

    def _force_take(self) -> bool:
        """Steal a provably-stale lock (holder process is gone).

        The region/flock lock must also come free (a dead holder's OS lock
        is auto-released); otherwise we keep waiting instead of piling two
        writers into the same critical section.
        """
        try:
            fh = self._open_lock_file()
        except OSError:
            return False
        try:
            if _msvcrt is not None:
                try:
                    fh.seek(_LOCK_BYTE_OFFSET)
                    _msvcrt.locking(fh.fileno(), _LK_NBLCK, 1)
                except OSError:
                    fh.close()
                    return False
            elif _fcntl is not None:
                try:
                    _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                except OSError:
                    fh.close()
                    return False
            self._write_header(fh)
            self._fh = fh
            return True
        except OSError:
            try:
                fh.close()
            except OSError:
                pass
            return False

    # -- release ----------------------------------------------------------
    def release(self) -> None:
        """Best-effort unlock.  Never raises (house never-raises rule)."""
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if _msvcrt is not None:
                try:
                    fh.seek(_LOCK_BYTE_OFFSET)
                    _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)
                except (OSError, ValueError):
                    pass  # already unlocked / handle closed: still not raising
            elif _fcntl is not None:
                try:
                    _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                fh.close()
            except OSError:
                pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


@contextmanager
def _locked(target_path: str, timeout: float, degrade: bool):
    """Core context manager.  ``degrade`` runs the body unlocked on timeout."""
    if not lock_enabled():
        yield False  # kill switch: caller ran UNLOCKED (pre-hub_ipc path)
        return
    lock = FileLock(target_path, timeout=timeout)
    acquired = False
    try:
        lock.acquire()
        acquired = True
    except LockTimeout:
        if not degrade:
            raise
        # Degraded mode: run the body without the cross-process gate rather
        # than raise into billing/egress paths (the old pre-lock behaviour).
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def locked_path(target_path, timeout: float = None, degrade: bool = True):
    """Serialize a block (or a whole function) across processes.

    Context manager::

        with hub_ipc.locked_path(USERS_PATH):
            _atomic_write_jsonl(USERS_PATH, rows)

    Decorator (path callable is evaluated at CALL time, so env-resolved paths
    stay live)::

        @hub_ipc.locked_path(lambda: USERS_PATH)
        def _persist(rows): ...

    ``degrade=True`` (default) runs the body unlocked when the wait budget
    expires - preserving the pre-lock never-raises behaviour of writers;
    ``degrade=False`` propagates :class:`LockTimeout` for callers that would
    rather fail loudly.  With HUB_IPC_LOCKS=0 the body always runs unlocked
    (old behaviour fully preserved), and the context yields False so callers
    can assert the kill switch.
    """
    if callable(target_path):
        path_of = target_path

        def deco(fn):
            def wrapper(*args, **kwargs):
                to = lock_timeout() if timeout is None else timeout
                with _locked(path_of(), to, degrade):
                    return fn(*args, **kwargs)
            return wrapper
        return deco

    to = lock_timeout() if timeout is None else timeout
    return _locked(target_path, to, degrade)