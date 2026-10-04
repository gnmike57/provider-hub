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
