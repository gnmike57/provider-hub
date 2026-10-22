#!/usr/bin/env bash
# Run every offline eval suite. Live-stack tests are excluded by default (they
# only run when LIVE_STACK=1 and real endpoints are provided).
set -e
cd "$(dirname "$0")"

# Python discovery: explicit override -> PATH python -> the repo .venv that
# sits one level up (ufo/.venv).
PY="${PYTHON_BIN:-}"
if [ -z "$PY" ]; then
  if command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then
    PY=python
  elif [ -x "../.venv/Scripts/python.exe" ]; then
    PY="../.venv/Scripts/python.exe"
  elif [ -x "../.venv/bin/python" ]; then
    PY="../.venv/bin/python"
  else
    PY=python3
  fi
fi


echo "== routing_probe (detection / formatter / assembler / Tier 2) =="
"$PY" -m pytest evals/routing_probe.py -q --tb=short

echo "== routing_test (authz / Tier 4 / Gate 7) =="
"$PY" -m pytest evals/routing_test.py -q --tb=short

echo "== callback_test (LiteLLM callback / single source) =="
"$PY" -m pytest evals/callback_test.py -q --tb=short

echo "== hedge_test (speculative dual-dispatch) =="
"$PY" -m pytest evals/hedge_test.py -q --tb=short

echo "== e2e_gateway_test (streaming ring buffer) =="
"$PY" -m pytest evals/e2e_gateway_test.py -q --tb=short

echo "== assembly_test (/v1/execute / audit / retry) =="
"$PY" -m pytest evals/assembly_test.py -q --tb=short

echo "== edge_test (tools / n>1 / disconnect / concurrency / metrics) =="
"$PY" -m pytest evals/edge_test.py -q --tb=short

echo
echo "ALL OFFLINE SUITES PASSED"
echo "(live stack: LIVE_STACK=1 evals/live_stack_test.py - see evals/live_stack_test.py header)"

# ---------------------------------------------------------------------------
# FAST_SET sweep (added 2026-10-21): one glob over evals/*_test.py.
#
# The explicit suites above stay exactly as they are (additive-only law) - this
# section ADDS coverage for every evals/*_test.py file, including the ones not
# yet pinned above (constellation_test, nogo/option parity siblings, hub_ipc
# and the W2/W3 additions as they land). Run the whole sweep in one pytest
# invocation, or name a subset with FAST_SET="hedge switch account_pool".
#
# Skipped by design, not silently:
#   - evals/live_stack_test.py guards every test with LIVE_STACK=1 and reports
#     "skipped" in the summary line below.
#   - evals/option_parity_test.py does not exist (parity lives in
#     evals/_probe_cl.py + its cl_test.py sibling) - never referenced here.
# An empty match list FAILS LOUDLY with exit 1 rather than reporting a
# zero-test pass. Override the interpreter with PYTHON_BIN (used as
# "$PYTHON_BIN -m pytest", same discovery as the explicit suites above) or
# FAST_PY (a bare pytest binary path, e.g. /usr/local/bin/pytest).
# ---------------------------------------------------------------------------
if [ "${RUN_FAST_SET:-0}" != "0" ]; then
  # One pytest process for the whole sweep. Default: reuse the interpreter
  # already discovered above (same order: PYTHON_BIN override -> PATH python
  # with pytest -> repo venvs). FAST_PY (a bare pytest binary) wins if set.
  if [ -n "${FAST_PY:-}" ]; then
    :  # caller-provided binary, used as-is
  elif [ -n "$PY" ]; then
    FAST_PY="$PY -m pytest"
  else
    FAST_PY="python -m pytest"
  fi

  fast_files=""
  if [ -n "${FAST_SET:-}" ]; then
    for stub in $FAST_SET; do
      for f in evals/${stub}*_test.py; do
        [ -f "$f" ] && fast_files="$fast_files $f"
      done
    done
  else
    for f in evals/*_test.py; do
      [ -f "$f" ] && fast_files="$fast_files $f"
    done
  fi
  if [ -z "$fast_files" ]; then
    echo "FAST_SET: no files matched - FAILING (this cannot be silent)" >&2
    exit 1
  fi
  echo
  echo "== FAST_SET sweep (evals/*_test.py) =="
  # shellcheck disable=SC2086 # word splitting here IS the test list
  fast_rc=0
  $FAST_PY $fast_files -q --tb=short -p no:cacheprovider || fast_rc=$?
  fast_total=$(printf '%s\n' $fast_files | wc -l)
  echo "FAST_SET: $fast_total file(s) swept, exit=$fast_rc"
  exit $fast_rc
fi
