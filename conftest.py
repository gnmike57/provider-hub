# Ensure the reference-implementation root is importable regardless of how
# pytest was invoked (python -m pytest, bare pytest, or an IDE runner).
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# (RACE v2, 2026-10-23) tests get FAST race timings - the production grace
# (2000ms) and peer-hold (2500ms) would otherwise add seconds to every
# race/hedge test. Production keeps its defaults; tests may still override.
for _k, _v in (("RACE_GRACE_MS", "120"),
               ("RACE_PEER_MAX_WAIT_MS", "200"),
               ("RACE_PEER_MIN_CHARS", "40")):
    os.environ.setdefault(_k, _v)

# 2026-10-06: the system Python has the full `litellm` package installed, and a
# regular package always beats the local namespace shim `./litellm/` (no
# __init__.py) in import resolution - so evals/callback_test.py's
# `from litellm.routing_callback import ...` failed with ModuleNotFoundError even
# though the file lives right here (the component documented in README and
# architecture.md as "repair inside LiteLLM"). Extend the imported package's
# __path__ with the shim directory before collection; site-packages content is
# untouched and the local file becomes litellm.routing_callback again.
try:
    import litellm as _litellm

    _shim = os.path.join(ROOT, "litellm")
    if _shim not in list(getattr(_litellm, "__path__", [])):
        _litellm.__path__.append(_shim)
except Exception:  # pragma: no cover - litellm absent: nothing to extend
    pass


# ---------------------------------------------------------------------------
# 2026-10-20 (W5 statewarden): tests must NEVER write production runtime state.
#
# The state modules resolve their file locations from env vars AT IMPORT TIME
# (constellation: SLOT_HISTORY_FILE / MODEL_HEALTH_FILE; siphon: the
# SIPHON_*_FILE family; billing: USERS_FILE / USAGE_FILE), and the
# import-time singletons (constellation.BINDING_HISTORY / HEALTH, ...) bind
# those paths when the module is first imported - which happens during test
# COLLECTION, before any fixture body can run. The redirect therefore happens
# HERE, at conftest import time (conftest is imported before the test modules),
# and the autouse session fixture below re-asserts it and cleans up afterwards.
#
# Verified poisoned 2026-10-20: every `pytest evals/` run appended tester rows
# (principal "tester", urls *.test / hive.example) to the production
# slot_bindings.json / cards.jsonl, and the hub's boot-restore then re-bound
# the LIVE slots to them (healthz showed primary=primary.test, later
# hive.example test junk).
# ---------------------------------------------------------------------------
import atexit
import shutil
import tempfile

import pytest

# env var -> the production default it would otherwise resolve to.
_STATE_ENV = {
    "SLOT_HISTORY_FILE": "slot_bindings.json",
    "MODEL_HEALTH_FILE": "model_health.jsonl",
    "SIPHON_CARDS_FILE": "cards.jsonl",
    "SIPHON_STATE_FILE": "siphon_state.json",
    "SIPHON_MEMORY_FILE": "siphon_memory.jsonl",
    "SIPHON_AUDIT_FILE": "card_amount_audit.jsonl",
    "SIPHON_INTENTS_FILE": "charge_intents.jsonl",
    "USERS_FILE": "users.jsonl",
    "USAGE_FILE": "usage_events.jsonl",
    "ABLITERATION_POOL_FILE": "abliteration_pool.json",
    # Multi-account credential pool (full key values - gitignored). Tests
    # override the live pool per-case via ACCOUNT_POOL_KEYS.
    "ACCOUNT_POOL_FILE": "account_pool.json",
}

# Per-session quarantine directory (pytest's tmp_path is a fixture and cannot
# be used at import time; mkdtemp gives the same guarantee: a fresh dir in the
# system temp root, never the repo). Removed at session end (atexit backstop).
QUARANTINE_DIR = tempfile.mkdtemp(prefix="provider-hub-test-state-")

for _var, _name in _STATE_ENV.items():
    os.environ[_var] = os.path.join(QUARANTINE_DIR, _name)

atexit.register(shutil.rmtree, QUARANTINE_DIR, ignore_errors=True)


@pytest.fixture(autouse=True, scope="session")
def quarantine_runtime_state():
    """Autouse session guard: production state files are off-limits to tests.

    The env redirect happened at conftest import - BEFORE any test module
    imported constellation / siphon / billing, so both the module-level path
    constants and the import-time singletons point into QUARANTINE_DIR. This
    fixture re-asserts the env (in case a polluting test left a stray value
    behind without undoing it) and removes the quarantine directory when the
    session ends; atexit is the crash backstop.

    A test that genuinely wants its own state file passes an explicit path= or
    monkeypatches the env var per-test (restored automatically afterwards).
    """
    for var, name in _STATE_ENV.items():
        os.environ[var] = os.path.join(QUARANTINE_DIR, name)
    yield
    shutil.rmtree(QUARANTINE_DIR, ignore_errors=True)
