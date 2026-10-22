"""User credit billing + usage metering for the Frost interception gateway."""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import hub_ipc  # cross-process file locks for the JSONL state files (W2)
from cryptography.fernet import Fernet

__all__ = [
    "KeyVault",
    "UserBilling",
    "UsageTracker",
    "SimpleAI",
    "KEY_VAULT",
    "BILLING",
    "USAGE",
    "SIMPLE_AI",
]

ROOT = os.path.dirname(os.path.abspath(__file__))
USER_KEYS_PATH = os.getenv("USER_KEYS_FILE", os.path.join(ROOT, "user_keys.jsonl"))
USERS_PATH = os.getenv("USERS_FILE", os.path.join(ROOT, "users.jsonl"))
USAGE_PATH = os.getenv("USAGE_FILE", os.path.join(ROOT, "usage_events.jsonl"))

CREDIT_COST_PER_TOKEN = float(os.getenv("CREDIT_COST_PER_TOKEN", "0.002"))
CREDIT_TOPUP_AMOUNT = float(os.getenv("CREDIT_TOPUP_AMOUNT", "10.00"))
CREDIT_LOW_THRESHOLD = float(os.getenv("CREDIT_LOW_THRESHOLD", "2.00"))
CREDIT_FREE_TIER = float(os.getenv("CREDIT_FREE_TIER", "1.00"))
# Cap on how many users may receive the signup free tier.  get_or_create()
# mints CREDIT_FREE_TIER for every NEW user id, and user ids arrive from an
# unauthenticated X-User-Id header - without a cap every unique header value
# would mint free credits forever.  Users created past the cap start at $0.
FREE_TIER_MAX_USERS = int(os.getenv("FREE_TIER_MAX_USERS", "100"))

# --------------------------------------------------------------------------
# Adaptive auto top-up (investigative tuning).
#
# When a user's credit balance falls to the trigger threshold, the gateway
# tops up automatically so the session is never interrupted.  The amount is "just less than" the
# configured top-up amount and is re-tuned after every event to discover the
# optimal top-up amount (most successful requests per dollar) and the optimal
# consumption velocity (credits burned per request).
# --------------------------------------------------------------------------
# OPT-IN (2026-10-20): _auto_topup() mints credits without a card charge, so
# leaving it on by default silently turned every low-balance deduct() into free
# money (constellation_test::test_billing_registry_basic caught the balance
# RISING right after a deduction). Enable only in deployments that really want
# free-mint behaviour; the amount/velocity tuning machinery is unchanged.
AUTO_TOPUP_ENABLED = os.getenv("AUTO_TOPUP_ENABLED", "false").strip().lower() in ("1", "true", "on", "yes")
AUTO_TOPUP_BASE_AMOUNT = float(os.getenv("AUTO_TOPUP_BASE_AMOUNT", str(CREDIT_TOPUP_AMOUNT)))
AUTO_TOPUP_MIN_AMOUNT = float(os.getenv("AUTO_TOPUP_MIN_AMOUNT", "1.00"))
AUTO_TOPUP_MAX_AMOUNT = float(os.getenv("AUTO_TOPUP_MAX_AMOUNT", "50.00"))
# Target balance to restore after an auto top-up (just above the low threshold).
AUTO_TOPUP_RESTORE_TARGET = float(
    os.getenv("AUTO_TOPUP_RESTORE_TARGET", str(CREDIT_LOW_THRESHOLD + 1.0))
)
# "Just less than" factor: top up slightly under the computed amount so each
# event stays investigative rather than blindly refilling.
AUTO_TOPUP_JUST_LESS_FACTOR = float(os.getenv("AUTO_TOPUP_JUST_LESS_FACTOR", "0.95"))
# Per-event adjustment step (USD) applied when re-tuning the top-up amount.
AUTO_TOPUP_ADJUST_STEP = float(os.getenv("AUTO_TOPUP_ADJUST_STEP", "1.00"))
# Balance level that fires the auto top-up: as soon as a user's balance
# falls to this threshold (default $2.00) rather than waiting for full
# depletion.
AUTO_TOPUP_TRIGGER = float(os.getenv("AUTO_TOPUP_TRIGGER", "2.00"))
# Card the auto top-up charges/records when no proven audit combo exists.
AUTO_TOPUP_CARD_ID = os.getenv("AUTO_TOPUP_CARD_ID", "")

RETENTION_DAYS = int(os.getenv("USAGE_RETENTION_DAYS", "7"))

# --------------------------------------------------------------------------
# Cross-process write coordination (W2, additive).
#
# The JSONL state files can be written by more than one process (gateway,
# admin CLIs, maintenance scripts).  Each individual write is already atomic
# (tmp + os.replace) but two concurrent FULL rewrites could still drop the
# other side's rows; a shared advisory lock closes that window.  Semantics:
#
#   * BILLING_FILE_LOCKS=0 (or HUB_IPC_LOCKS=0) keeps the exact pre-lock
#     behaviour: writes go straight through _atomic_write_jsonl unlocked.
#     Default is ON ("1") because the lock degrades to unlocked-on-timeout,
#     i.e. it can only serialize, never wedge, billing writes.
#   * BILLING_COMPACT_INTERVAL: only the append-only fast path (below) is
#     affected.  Unset/0 = the historical full-rewrite path on EVERY record()
#     (default, byte-identical persistence semantics).
#   * The threading.RLock()es above stay authoritative within the process;
#     hub_ipc only adds the cross-process half.
# --------------------------------------------------------------------------
BILLING_FILE_LOCKS = os.getenv("BILLING_FILE_LOCKS", "1").strip().lower() in (
    "1", "true", "on", "yes")
# Append-only fast path for UsageTracker.record(): 0/unset = full rewrite
# every event (historical), N>0 = append JSONL directly and fully rewrite
# (compact) only every Nth event.  In-memory _events stays the complete
# authoritative list in both modes, so user_usage/system_usage are identical.
BILLING_COMPACT_INTERVAL = int(os.getenv("BILLING_COMPACT_INTERVAL", "0") or 0)


def _file_locks_enabled() -> bool:
    """Use-site kill switch for cross-process persistence locking.

    Env wins when set (live tunability, the account_pool ACCOUNT_POOL_ENABLED
    pattern); the import-time BILLING_FILE_LOCKS constant is the fallback so
    tests/embedders can also monkeypatch the module attribute.
    """
    raw = os.getenv("BILLING_FILE_LOCKS", "")
    if raw:
        return raw.strip().lower() in ("1", "true", "on", "yes")
    return BILLING_FILE_LOCKS


def _compact_interval() -> int:
    """Use-site read of the append fast-path knob (0 = historical rewrite)."""
    raw = os.getenv("BILLING_COMPACT_INTERVAL", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 0
    return BILLING_COMPACT_INTERVAL

ABLITERATION_ADMIN_KEY = os.getenv(
    "ABLITERATION_ADMIN_KEY", os.getenv("ABLITERATION_API_KEY", "")
)
ABLITERATION_ADMIN_BASE = os.getenv(
    "ABLITERATION_ADMIN_BASE", "https://api.abliteration.ai/v1"
)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
_FERNET = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet():
    """The module Fernet, lazily (re)initialized from ENCRYPTION_KEY.

    Lazy resolution lets tests and embedders configure the key after import
    without re-importing billing.  When no key is configured this returns
    None: plaintext WRITES are then refused (fail closed), while READS of
    legacy plaintext rows stay lenient.
    """
    global _FERNET
    if _FERNET is None:
        key = os.getenv("ENCRYPTION_KEY", "").strip()
        if key:
            _FERNET = Fernet(key.encode())
    return _FERNET


def _encrypt(plaintext: str) -> str:
    f = _fernet()
    if f is None:
        # Refuse the previously SILENT plaintext write: without this the key
        # material hit user_keys.jsonl unencrypted whenever ENCRYPTION_KEY
        # was not configured.
        raise RuntimeError(
            "ENCRYPTION_KEY not configured; refusing to store API key in plaintext"
        )
    return f.encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    # Lenient on purpose: rows written before a key was pinned (plaintext
    # legacy) stay readable; encrypted rows decrypt normally.
    f = _fernet()
    if f is None:
        return ciphertext
    return f.decrypt(ciphertext.encode()).decode()


def _atomic_write_jsonl(path: str, rows: List[dict]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _persist_jsonl(path: str, rows: List[dict]) -> None:
    """Atomic write, serialized across processes when locks are enabled.

    Additive wrapper around _atomic_write_jsonl: identical bytes on disk,
    identical OSError-swallowing at call sites (callers keep their
    ``try/except OSError: pass``), plus an advisory cross-process lock so
    concurrent FULL rewrites from gateway + admin CLIs cannot drop each
    other's rows.  BILLING_FILE_LOCKS=0 / HUB_IPC_LOCKS=0 (or a lock timeout
    - see hub_ipc.locked_path degrade) preserves the exact unlocked path.
    """
    if not _file_locks_enabled():
        _atomic_write_jsonl(path, rows)  # pre-hub_ipc behaviour
        return
    try:
        with hub_ipc.locked_path(path):
            _atomic_write_jsonl(path, rows)
    except hub_ipc.LockTimeout:
        # Lock could not be taken within the budget: fall back to the
        # historical unlocked write rather than raise into billing paths.
        _atomic_write_jsonl(path, rows)


def _append_and_maybe_compact(path: str, row: dict, rows: List[dict],
                              tail: int, counter: "List[int]") -> None:
    """Append-only fast path for UsageTracker.record() (BILLING_COMPACT_INTERVAL).

    Appends ONE line to the JSONL instead of rewriting the whole file, then
    fully rewrites (compacts) every ``BILLING_COMPACT_INTERVAL``-th event.
    ``rows`` stays the authoritative in-memory list (the compaction snapshot
    is taken under the caller's threading lock BEFORE calling this), so reads
    are unchanged.  ``counter`` is a one-element mutable count shared by the
    tracker; compaction fires when ``counter[0] % interval == 0``.

    Kill switch: BILLING_COMPACT_INTERVAL unset/0 -> callers must use the
    historical full-rewrite path (enforced at the use site).
    """
    interval = _compact_interval()
    interval = interval if interval and interval > 0 else 0
    counter[0] = int(counter[0]) + 1
    fire_compact = bool(interval) and (counter[0] % interval == 0)
    if not _file_locks_enabled():
        if fire_compact:
            _atomic_write_jsonl(path, rows[-tail:])
        else:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return
    try:
        with hub_ipc.locked_path(path):
            if fire_compact:
                _atomic_write_jsonl(path, rows[-tail:])
            else:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except hub_ipc.LockTimeout:
        # Degraded: historical full rewrite is always safe fallback.
        _atomic_write_jsonl(path, rows[-tail:])


def _load_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    rows: List[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


# ============================================================================
# KeyVault - encrypted per-user API key storage
# ============================================================================
class KeyVault:
    """Stores per-user API keys (Hive + Abliteration) encrypted at rest.

    Key shape per row:
        {"user_id": "...", "provider": "hive"|"abliteration", "key_encrypted": "...",
         "updated_at": "..."}
    """

    def __init__(self, path: str = ""):
        self.path = path or USER_KEYS_PATH
        self._lock = threading.RLock()
        self._rows: List[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            rows = _load_jsonl(self.path)
        except OSError:
            rows = []
        with self._lock:
            self._rows = rows

    def store_key(self, user_id: str, provider: str, key: str) -> None:
        """Encrypt and store a user's API key for a provider."""
        row = {
            "user_id": user_id,
            "provider": provider,
            "key_encrypted": _encrypt(key),
            "updated_at": _now(),
        }
        with self._lock:
            self._rows = [r for r in self._rows
                          if not (r.get("user_id") == user_id and r.get("provider") == provider)]
            self._rows.append(row)
            try:
                _persist_jsonl(self.path, self._rows)
            except OSError:
                pass

    def get_key(self, user_id: str, provider: str) -> Optional[str]:
        """Decrypt and return a user's API key for a provider. Never raises."""
        with self._lock:
            for r in self._rows:
                if r.get("user_id") == user_id and r.get("provider") == provider:
                    try:
                        return _decrypt(r.get("key_encrypted", ""))
                    except Exception:
                        return None
        return None

    def has_key(self, user_id: str, provider: str) -> bool:
        return self.get_key(user_id, provider) is not None

    def list_users(self) -> List[str]:
        with self._lock:
            return sorted({r.get("user_id") for r in self._rows if r.get("user_id")})


# ============================================================================
# UserBilling - credit balance + Abliteration.ai admin charging
# ============================================================================
class UserBilling:
    """Per-user credit balance + Abliteration.ai admin charging.

    Shape per row in users.jsonl:
        {"user_id": "...", "credits_usd": 5.00, "total_tokens": 0,
         "total_requests": 0, "total_cost_usd": 0.0, "created_at": "...",
         "last_topup_at": null, "last_charge_at": null, "admin_key": null}
    """

    def __init__(self, path: str = ""):
        self.path = path or USERS_PATH
        self._lock = threading.RLock()
        self._rows: List[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            rows = _load_jsonl(self.path)
        except OSError:
            rows = []
        with self._lock:
            self._rows = rows

    def _find(self, user_id: str) -> Optional[dict]:
        for r in self._rows:
            if r.get("user_id") == user_id:
                return r
        return None

    def get_or_create(self, user_id: str) -> dict:
        with self._lock:
            row = self._find(user_id)
            if row is None:
                # Bounded free-credit minting: the signup free tier is only
                # granted while the registry is under FREE_TIER_MAX_USERS.
                # Past the cap a new (possibly spoofed X-User-Id) user starts
                # at $0 instead of minting CREDIT_FREE_TIER forever.
                grant_free_tier = len(self._rows) < FREE_TIER_MAX_USERS
                row = {
                    "user_id": user_id,
                    "credits_usd": CREDIT_FREE_TIER if grant_free_tier else 0.0,
                    "total_tokens": 0,
                    "total_requests": 0,
                    "total_cost_usd": 0.0,
                    "created_at": _now(),
                    "last_topup_at": None,
                    "last_charge_at": None,
                    "admin_key": None,
                    # Adaptive auto top-up state.
                    "topup_amount": AUTO_TOPUP_BASE_AMOUNT,
                    "topup_history": [],
                    "requests_since_topup": 0,
                    "cost_since_topup": 0.0,
                    "last_auto_topup_at": None,
                    "auto_topup_count": 0,
                }
                self._rows.append(row)
                try:
                    _persist_jsonl(self.path, self._rows)
                except OSError:
                    pass
            return row

    def get_balance(self, user_id: str) -> float:
        row = self.get_or_create(user_id)
        return float(row.get("credits_usd", 0.0))

    def deduct(self, user_id: str, tokens: int, cost_usd: float) -> None:
        """Deduct cost from user's credit balance after a request.

        Tracks per-top-up-period velocity (credits burned per request) and
        triggers an adaptive auto top-up when the balance falls to the
        trigger threshold (AUTO_TOPUP_TRIGGER, default $2.00) so the
        session is never interrupted.
        """
        with self._lock:
            row = self._find(user_id)
            if row is None:
                row = self.get_or_create(user_id)
            row["credits_usd"] = max(0.0, float(row.get("credits_usd", 0.0)) - cost_usd)
            row["total_tokens"] = int(row.get("total_tokens", 0)) + tokens
            row["total_requests"] = int(row.get("total_requests", 0)) + 1
            row["total_cost_usd"] = float(row.get("total_cost_usd", 0.0)) + cost_usd
            # Velocity tracking for investigative top-up tuning.
            row["requests_since_topup"] = int(row.get("requests_since_topup", 0) or 0) + 1
            row["cost_since_topup"] = float(row.get("cost_since_topup", 0.0) or 0.0) + cost_usd
            balance_after = float(row.get("credits_usd", 0.0))
            try:
                _persist_jsonl(self.path, self._rows)
            except OSError:
                pass
        # Auto top-up when the balance falls to the trigger threshold
        # (outside the write so a failed top-up never rolls back the
        # recorded deduction).
        if AUTO_TOPUP_ENABLED and balance_after <= AUTO_TOPUP_TRIGGER:
            self._auto_topup(user_id)

    def add_credits(self, user_id: str, amount_usd: float,
                    source: str = "admin") -> None:
        """Add credits to a user's balance (after successful charge)."""
        with self._lock:
            row = self.get_or_create(user_id)
            row["credits_usd"] = float(row.get("credits_usd", 0.0)) + amount_usd
            row["last_topup_at"] = _now()
            try:
                _persist_jsonl(self.path, self._rows)
            except OSError:
                pass

    def is_low(self, user_id: str) -> bool:
        return self.get_balance(user_id) < CREDIT_LOW_THRESHOLD

    def is_depleted(self, user_id: str) -> bool:
        return self.get_balance(user_id) <= 0.0

    # ------------------------------------------------------------------
    # Adaptive auto top-up (investigative tuning)
    # ------------------------------------------------------------------
    def _auto_topup(self, user_id: str) -> None:
        """Top up a user whose balance fell to the trigger threshold.

        The amount is "just less than" the configured top-up amount so each
        event stays investigative rather than blindly refilling.  After every
        event the per-user top-up amount is re-tuned to discover the optimal
        top-up amount (most successful requests per dollar) and the optimal
        consumption velocity (credits burned per request).
        """
        if not AUTO_TOPUP_ENABLED:
            return
        with self._lock:
            row = self._find(user_id)
            if row is None:
                return
            balance = float(row.get("credits_usd", 0.0))
            if balance > AUTO_TOPUP_TRIGGER:
                return  # still above the trigger threshold

            # Capture velocity *before* resetting the period counters.
            reqs_since_last = int(row.get("requests_since_topup", 0) or 0)
            cost_since_last = float(row.get("cost_since_topup", 0.0) or 0.0)
            velocity = cost_since_last / reqs_since_last if reqs_since_last else 0.0

            current = float(
                row.get("topup_amount") or AUTO_TOPUP_BASE_AMOUNT
            )
            current = min(max(current, AUTO_TOPUP_MIN_AMOUNT), AUTO_TOPUP_MAX_AMOUNT)

            # Amount needed to restore the balance to the restore target.
            restore_needed = max(AUTO_TOPUP_RESTORE_TARGET - balance, 0.0)

            # "Just less than" the top-up amount: bias downward so the refill
            # stays conservative and investigative.
            amount = round(
                min(current, restore_needed) * AUTO_TOPUP_JUST_LESS_FACTOR, 2
            )
            amount = min(max(amount, AUTO_TOPUP_MIN_AMOUNT), AUTO_TOPUP_MAX_AMOUNT)
            if amount <= 0:
                amount = AUTO_TOPUP_MIN_AMOUNT

            # Intelligent card-aware selection: prefer an amount that PROVABLY
            # worked on a real card (from the SIPHON card-amount audit ledger,
            # populated by completely real testing) over the adaptive guess.
            card_id_used = None
            proven_from_audit = False
            try:
                import siphon as siphon_mod  # lazy: no import cycle
                combo = siphon_mod.SIPHON.intelligent_topup_combo()
                if combo:
                    combo_card, combo_amount = combo
                    if AUTO_TOPUP_MIN_AMOUNT <= combo_amount <= AUTO_TOPUP_MAX_AMOUNT:
                        amount = round(combo_amount, 2)
                        card_id_used = combo_card
                        proven_from_audit = True
            except Exception:
                pass

            # Fall back to the configured top-up card (if any) when no proven
            # audit combo exists, so the auto top-up is always card-aware.
            if not card_id_used and AUTO_TOPUP_CARD_ID:
                card_id_used = AUTO_TOPUP_CARD_ID

            # Apply the credit.
            row["credits_usd"] = round(float(row.get("credits_usd", 0.0)) + amount, 4)
            row["last_topup_at"] = _now()

            # Record history for investigative tuning.
            history = row.get("topup_history") or []
            history.append(
                {
                    "ts": _now(),
                    "amount_usd": amount,
                    "balance_before": balance,
                    "balance_after": round(
                        float(row.get("credits_usd", 0.0)), 4
                    ),
                    "velocity_usd_per_req": round(velocity, 6),
                    "requests_since_last_topup": reqs_since_last,
                    "card_id": card_id_used,
                    "proven_from_audit": proven_from_audit,
                }
            )
            row["topup_history"] = history[-200:]
            row["last_auto_topup_at"] = _now()
            row["auto_topup_count"] = int(row.get("auto_topup_count", 0) or 0) + 1

            # Reset the velocity window for the new top-up period.
            row["requests_since_topup"] = 0
            row["cost_since_topup"] = 0.0

            # Re-tune the per-user top-up amount for the next event.
            row["topup_amount"] = self._adjust_topup_amount(
                current, reqs_since_last, velocity
            )

            try:
                _persist_jsonl(self.path, self._rows)
            except OSError:
                pass

    @staticmethod
    def _adjust_topup_amount(
        current: float, reqs_since_last: int, velocity: float
    ) -> float:
        """Re-tune a user's top-up amount after an auto top-up event.

        Investigative heuristic:
          * Re-depleted almost immediately (few requests)  -> amount too small,
            increase it.
          * Top-up lasted many requests at low burn        -> can be more
            conservative, decrease toward the minimum.
          * Otherwise                                      -> keep the amount.
        """
        step = AUTO_TOPUP_ADJUST_STEP
        if reqs_since_last <= 2:
            return round(
                min(current + step, AUTO_TOPUP_MAX_AMOUNT), 2
            )
        if reqs_since_last >= 10 and velocity < (AUTO_TOPUP_RESTORE_TARGET / 10.0):
            return round(
                max(current - step, AUTO_TOPUP_MIN_AMOUNT), 2
            )
        return current

    def all_users(self) -> List[dict]:
        with self._lock:
            return [dict(r) for r in self._rows]


# ============================================================================
# UsageTracker - per-request usage metering
# ============================================================================
class UsageTracker:
    """Records per-request usage events for metering and monitoring.

    Shape per row in usage_events.jsonl:
        {"user_id": "...", "timestamp": "...", "model": "...",
         "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
         "provider": "hive"|"abliteration"|"nano", "request_id": "..."}
    """

    def __init__(self, path: str = ""):
        self.path = path or USAGE_PATH
        self._lock = threading.RLock()
        self._events: List[dict] = []
        # One-element mutable counter shared with the append fast path
        # (_append_and_maybe_compact): counts record() calls in THIS process
        # so compaction can fire on every Nth event.  Unused (stays 0) on the
        # historical full-rewrite path (BILLING_COMPACT_INTERVAL unset/0).
        self._persist_count = [0]
        self._load()

    def _load(self) -> None:
        cutoff = time.time() - RETENTION_DAYS * 86400
        try:
            rows = _load_jsonl(self.path)
        except OSError:
            rows = []
        kept: List[dict] = []
        for r in rows:
            if not isinstance(r, dict) or not isinstance(r.get("timestamp"), str):
                continue
            try:
                ts = datetime.fromisoformat(r["timestamp"]).timestamp()
            except (ValueError, TypeError):
                # Malformed timestamp: skip the row instead of raising.  This
                # runs at import time (USAGE singleton), so one corrupt line
                # used to mean the whole hub would not boot.
                continue
            if ts > cutoff:
                kept.append(r)
        with self._lock:
            self._events = kept

    def record(self, user_id: str, model: str, tokens_in: int,
               tokens_out: int, cost_usd: float, provider: str,
               request_id: str = "") -> None:
        event = {
            "user_id": user_id,
            "timestamp": _now(),
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 6),
            "provider": provider,
            "request_id": request_id,
        }
        with self._lock:
            self._events.append(event)
            try:
                interval = _compact_interval()
                if interval and interval > 0:
                    # Append-only fast path (opt-in via BILLING_COMPACT_INTERVAL):
                    # one-line append, full rewrite every Nth event.  In-memory
                    # _events stays authoritative either way, so user_usage /
                    # system_usage are identical across both paths.
                    _append_and_maybe_compact(
                        self.path, event, self._events, 10000, self._persist_count
                    )
                else:
                    # Historical path (default, interval unset/0): full
                    # rewrite of the tail on every event - byte-identical
                    # persistence semantics to pre-W2.
                    _persist_jsonl(self.path, self._events[-10000:])
            except OSError:
                pass

    def user_usage(self, user_id: str) -> dict:
        with self._lock:
            events = [e for e in self._events if e.get("user_id") == user_id]
        total_tokens = sum(e.get("tokens_in", 0) + e.get("tokens_out", 0) for e in events)
        total_cost = sum(e.get("cost_usd", 0.0) for e in events)
        return {
            "user_id": user_id,
            "total_requests": len(events),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "last_event": events[-1]["timestamp"] if events else None,
        }

    def system_usage(self) -> dict:
        with self._lock:
            events = list(self._events)
        total_tokens = sum(e.get("tokens_in", 0) + e.get("tokens_out", 0) for e in events)
        total_cost = sum(e.get("cost_usd", 0.0) for e in events)
        users = {e.get("user_id") for e in events if e.get("user_id")}
        return {
            "total_requests": len(events),
            "total_users": len(users),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
        }


# ============================================================================
# SimpleAI - ultra-simple free AI for credit reminders
# ============================================================================
class SimpleAI:
    """Template-based conversational AI for credit reminders and basic queries.

    Requires no external model - completely free.
    """

    CREDIT_LOW_TEMPLATES = [
        "Your credit balance is running low (${balance:.2f}). Please top up to keep using the service.",
        "Heads up: your balance is ${balance:.2f}. Add credits to avoid interruption.",
        "Credit alert: only ${balance:.2f} remaining. Top up to continue uninterrupted access.",
    ]

    CREDIT_DEPLETED_TEMPLATES = [
        "Your credit balance is depleted. Please add credits to continue using the service.",
        "Out of credits. Top up your account to resume.",
        "Balance is $0.00. Please top up to continue.",
    ]

    GREETING_TEMPLATES = [
        "Hello! I'm your assistant. How can I help you today?",
        "Hi there! What can I do for you?",
        "Hello! Ready to help. What do you need?",
    ]

    def credit_reminder(self, user_id: str, balance: float,
                        is_depleted: bool = False) -> str:
        """Generate a credit reminder message for a user."""
        import random
        if is_depleted or balance <= 0:
            template = random.choice(self.CREDIT_DEPLETED_TEMPLATES)
        else:
            template = random.choice(self.CREDIT_LOW_TEMPLATES)
        return template.format(balance=round(balance, 2))

    def status(self, user_id: str, balance: float, tokens_used: int) -> str:
        """Generate a status message for a user."""
        return (
            f"Account status for {user_id}:\n"
            f"  Balance: ${balance:.2f}\n"
            f"  Tokens used: {tokens_used}\n"
            f"  Status: {'active' if balance > CREDIT_LOW_THRESHOLD else 'low credit - top up soon'}\n"
        )

    def help(self) -> str:
        return (
            "Available commands:\n"
            "  /balance - Check your credit balance\n"
            "  /topup - Add credits to your account\n"
            "  /status - View account status\n"
            "  /help - Show this help message\n"
            "Just type normally to chat with the AI.\n"
        )

    def respond(self, message: str, user_id: str = "", balance: float = 0.0,
                tokens_used: int = 0) -> str:
        """Route a user message to the appropriate response."""
        msg = message.strip().lower()
        if msg in ("/help", "help", "commands"):
            return self.help()
        if msg in ("/balance", "balance"):
            return self.status(user_id, balance, tokens_used)
        if msg in ("/status", "status"):
            return self.status(user_id, balance, tokens_used)
        if msg in ("/topup", "topup"):
            return (
                f"Your balance is ${balance:.2f}. "
                f"Please contact an administrator or use the top-up endpoint to add credits.\n"
                f"Free tier: ${CREDIT_FREE_TIER:.2f} on signup."
            )
        if msg in ("/hello", "hi", "hello", "hey"):
            import random
            return random.choice(self.GREETING_TEMPLATES)
        return (
            f"I received your message: '{message}'\n"
            f"Your current balance is ${balance:.2f}. "
            f"Type /help for available commands."
        )


# ============================================================================
# Module-level singletons
# ============================================================================
KEY_VAULT = KeyVault()
BILLING = UserBilling()
USAGE = UsageTracker()
SIMPLE_AI = SimpleAI()