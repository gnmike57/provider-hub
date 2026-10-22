#!/usr/bin/env bash
# ============================================================================
# tars-hybrid-router deployment (gx10, user nick). Idempotent; safe to
# re-run. Files (litellm_config.yaml, vision_bridge.py, router.env,
# litellm-router.service, verify.sh, README.md) must already be in
# /home/nick/tars-litellm-router (scp'd by the lead).
# ============================================================================
set -euo pipefail
DIR="/home/nick/tars-litellm-router"
mkdir -p "$DIR"
cd "$DIR"

# 1. venv --------------------------------------------------------------------
if [ ! -d .venv ]; then
  echo "== creating python venv =="
  python3 -m venv .venv
fi

# 2. litellm[proxy] (background: pip is slow; tool timeouts are 30s) ---------
if ! .venv/bin/pip show litellm >/dev/null 2>&1; then
  echo "== installing litellm[proxy] into .venv (background) =="
  nohup .venv/bin/pip install --upgrade pip 'litellm[proxy]' \
    > "$DIR/pip-install.log" 2>&1 &
  echo "   pip running as pid $!  (log: $DIR/pip-install.log)"
  echo "   poll with: tail -5 $DIR/pip-install.log ; .venv/bin/pip show litellm"
else
  echo "== litellm already installed =="
  # SIGPIPE fix (2026-10-22): `pip show | head -2` made pip die of SIGPIPE and
  # `set -o pipefail` aborted deploy.sh BEFORE the config-sanity step (live
  # defect during the v2 deploy: "ERROR: Pipe to stdout was broken"). Capture
  # first, print after - echo never SIGPIPEs pip.
  _pip_show="$(.venv/bin/pip show litellm 2>/dev/null || true)"
  echo "$_pip_show" | head -2
fi

# 3. config sanity ------------------------------------------------------------
.venv/bin/python - <<'PY'
import py_compile, sys
py_compile.compile("vision_bridge.py", doraise=True)
try:
    import yaml
except ImportError:
    sys.exit(0)  # yaml not yet available; litellm brings it
with open("litellm_config.yaml") as fh:
    yaml.safe_load(fh)
print("vision_bridge.py compiles; litellm_config.yaml parses")
PY

# 4. secrets perms -------------------------------------------------------------
chmod 600 router.env

echo "== done. next: install-service.sh (after pip finishes) then verify.sh =="
