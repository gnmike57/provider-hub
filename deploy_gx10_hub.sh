#!/usr/bin/env bash
# ============================================================================
# deploy_gx10_hub.sh - deploy the full RedHands Hub on gx10 (Linux)
#
# Runs from the provider-hub project root (this machine). Pushes code to
# /srv/apps/redhands-hub (neutral base folder), builds a venv, writes the env
# file, installs a systemd SYSTEM service bound to 0.0.0.0:9001 (port 9000 is
# taken by Docker's bronvault_clickhouse) so every user on the tailnet/LAN can
# reach it, and starts it.
#
# Usage:
#   bash deploy_gx10_hub.sh                 # run from this machine via SSH
#   GX10_HOST=gx10 bash deploy_gx10_hub.sh  # explicit host alias
#
# Prereqs:
#   - ssh alias "gx10" works (verified)
#   - User has sudo on gx10
# ============================================================================
set -euo pipefail

REMOTE="${GX10_HOST:-gx10}"
REMOTE_ROOT="/srv/apps/redhands-hub"
HUB_PORT=9001                       # 9000 is held by Docker bronvault_clickhouse
LOCAL_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "== deploy_gx10_hub.sh =="
echo "remote:     $REMOTE"
echo "remote root: $REMOTE_ROOT"
echo "hub port:    $HUB_PORT (0.0.0.0 - all users)"
echo "local root:  $LOCAL_ROOT"
echo

# --- 1. create neutral base folder on gx10 --------------------------------
echo "[1/6] ensuring neutral base folder $REMOTE_ROOT on gx10..."
ssh "$REMOTE" "sudo mkdir -p $REMOTE_ROOT && sudo chown \$USER:\$USER $REMOTE_ROOT && sudo chmod 755 $REMOTE_ROOT"

# --- 2. push hub code (exclude caches, secrets, results) ------------------
echo "[2/6] pushing hub code to gx10 via tar+ssh..."
EXCLUDES=(
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc'
  --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache'
  --exclude='.loki' --exclude='.staging' --exclude='.tars-setup'
  --exclude='.tars' --exclude='.idea' --exclude='node_modules'
  --exclude='evals/results' --exclude='mock.log' --exclude='mock.err'
  --exclude='soak' --exclude='model_health.jsonl' --exclude='siphon_memory.jsonl'
  --exclude='usage_events.jsonl' --exclude='users.jsonl' --exclude='skills_memory.jsonl'
  --exclude='gateway_registry.json' --exclude='account_pool.json'
  --exclude='abliteration_pool.json' --exclude='siphon_state.json'
  --exclude='*.lock' --exclude='deploy_gx10_hub.sh' --exclude='gx10_hub_*.sh'
)
# Build an exclude string for tar.
TAR_EXCLUDE=""
for e in "${EXCLUDES[@]}"; do
  val="${e#--exclude=}"
  TAR_EXCLUDE="$TAR_EXCLUDE --exclude=$val"
done
# Create tar on the fly, pipe over ssh, extract on gx10.
eval "tar cf - $TAR_EXCLUDE -C \"$LOCAL_ROOT\" ." | \
  ssh "$REMOTE" "cd $REMOTE_ROOT && tar xf -"
# Remove excluded files that may already exist on the box from a previous push.
for e in "${EXCLUDES[@]}"; do
  val="${e#--exclude=}"
  ssh "$REMOTE" "rm -rf $REMOTE_ROOT/$val" 2>/dev/null || true
done

# --- 3. build venv + install deps ------------------------------------------
echo "[3/6] building Python venv and installing dependencies on gx10..."
ssh "$REMOTE" "
  cd $REMOTE_ROOT
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
"

# --- 4. write hub.env with known values from gx10 ---------------------------
echo "[4/6] writing hub.env on gx10..."
# Known values already on gx10:
#   ABLITERATION_API_KEY=ak_hl42Y28ZU6fvxbhzpTi8-SqDbi1sEgpbO2CpqF4NCtI  (router.env)
#   PRIMARY_API_KEY=XSkXRMM6CmBA2lThA0xIWw==                            (provider-secrets.env)
#   FALLBACK_API_KEY=ak_QcXw__JFcPYS_zZfShQde85lb_tGfJo6GCO5aYU6b-Y        (provider-secrets.env)
# Generate a Fernet ENCRYPTION_KEY locally.
ENC_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
  || python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

ENV_CONTENT=$(cat <<ENVFILE
# ============================================================================
# hub.env - RedHands Hub environment (gx10, /srv/apps/redhands-hub)
# Real values for keys already on gx10 are pre-filled. Fill in placeholders.
# Never commit this file with real secrets.
# ============================================================================

# --- Required secrets (preflight gates the hub without these) ---------------
ENCRYPTION_KEY=${ENC_KEY}
ADMIN_API_KEY=<admin-key-for-x-admin-key>

# --- Abliteration (constellation terminal / specialist) ---------------------
ABLITERATION_API_KEY=ak_hl42Y28ZU6fvxbhzpTi8-SqDbi1sEgpbO2CpqF4NCtI
ABLITERATION_ADMIN_KEY=<sk_-admin-key>

# --- Hive / provider keys (from /etc/llm-gateway/provider-secrets.env) ------
PRIMARY_API_KEY=XSkXRMM6CmBA2lThA0xIWw==
FALLBACK_API_KEY=ak_QcXw__JFcPYS_zZfShQde85lb_tGfJo6GCO5aYU6b-Y
HIVE_SECRET_KEY=<hive-secret-key-or-leave-blank>

# --- Hub binding (0.0.0.0 = all users on tailnet/LAN) -----------------------
HOST=0.0.0.0
PORT=${HUB_PORT}

# --- Constellation (operator directive: constellation-only) -----------------
CONSTELLATION_ONLY=1
PRIMARY_API_URL=https://api.abliteration.ai/v1/chat/completions
PRIMARY_MODEL=abliterated-model-large-v2
FALLBACK_API_URL=https://api.abliteration.ai/v1/chat/completions
FALLBACK_MODEL=abliterated-model-large-v2
SPECIALIST_API_URL=https://api.abliteration.ai/v1/chat/completions
SPECIALIST_MODEL=abliterated-model-large-v2

# --- Abliteration pool keys (from abliteration_pool.json on gx10) -----------
ABLIT_POOL_KEY_A=ak_oOxe39e9q1Y5tnIyd3wUlZW-nd8J5BBPbZ1vT4A_wg0
ABLIT_POOL_KEY_B=ak_KFkBtfopFj3qFGE3BgDy6YH5Hs5rQX6iUcsF_DSzPhM

# --- Money safety -----------------------------------------------------------
NO_GO_ENABLED=1
MAX_THINK_MIN_TOKENS=32768

# --- Hedge / race -----------------------------------------------------------
HEDGE_MAX_TOKENS=16384
HEDGE_RACE_MODE=1
SPECIALIST_MAX_TOKENS=32768
COMMIT_TOKENS=10
MAX_CONCURRENT_STREAMS=64

# --- Misc -------------------------------------------------------------------
MOCK_ABLITERATION=0
HIDE_ABLIT_MODELS=0
SKILL_MEMORY=1
PYTHONUNBUFFERED=1
PYTHONIOENCODING=utf-8
ENVFILE
)

ssh "$REMOTE" "cat > $REMOTE_ROOT/hub.env <<'ENVEOF'
${ENV_CONTENT}
ENVEOF"
echo "  hub.env written."
echo "  REMAINING PLACEHOLDERS to fill in $REMOTE_ROOT/hub.env:"
echo "    - ADMIN_API_KEY          (X-Admin-Key for /v1/admin, /v1/user, /v1/siphon)"
echo "    - ABLITERATION_ADMIN_KEY (sk_- Abliteration org admin key)"
echo "    - HIVE_SECRET_KEY        (optional; leave blank if not using Hive rollback)"

# --- 5. install systemd system service -------------------------------------
echo "[5/6] installing systemd system service redhands-hub.service..."
SERVICE_UNIT=$(cat <<UNITEOF
[Unit]
Description=RedHands Hub - interception gateway (uvicorn :${HUB_PORT})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$REMOTE_ROOT
EnvironmentFile=$REMOTE_ROOT/hub.env
ExecStart=$REMOTE_ROOT/.venv/bin/python -m uvicorn proxy_gateway:app --host 0.0.0.0 --port ${HUB_PORT} --log-level info
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Sandboxing (root service, no new privileges)
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$REMOTE_ROOT

[Install]
WantedBy=multi-user.target
UNITEOF
)
ssh "$REMOTE" "echo '$SERVICE_UNIT' | sudo tee /etc/systemd/system/redhands-hub.service > /dev/null"
ssh "$REMOTE" "sudo chmod 644 /etc/systemd/system/redhands-hub.service"
ssh "$REMOTE" "sudo systemctl daemon-reload"
ssh "$REMOTE" "sudo systemctl enable redhands-hub.service"

# --- 6. start + verify -----------------------------------------------------
echo "[6/6] starting redhands-hub.service and verifying..."
ssh "$REMOTE" "sudo systemctl restart redhands-hub.service"
sleep 8
ssh "$REMOTE" "sudo systemctl is-active redhands-hub.service"
ssh "$REMOTE" "curl -s -m 10 http://127.0.0.1:${HUB_PORT}/healthz"

echo
echo "  health check (tailnet):"
curl -s -m 10 "http://gx10.ayu-sidewinder.ts.net:${HUB_PORT}/healthz" 2>&1 || echo "  (tailnet DNS may need a moment; try again)"

echo
echo "=== DEPLOY COMPLETE ==="
echo "Service:   redhands-hub.service (systemd system service, enabled at boot)"
echo "Hub URL:   http://0.0.0.0:${HUB_PORT}/healthz  (box, all interfaces)"
echo "           http://127.0.0.1:${HUB_PORT}/healthz  (box-local)"
echo "           http://100.67.13.78:${HUB_PORT}/healthz  (tailnet IP)"
echo "           http://gx10.ayu-sidewinder.ts.net:${HUB_PORT}/healthz  (tailnet name)"
echo "Env file:  $REMOTE_ROOT/hub.env  (fill in remaining placeholders above)"
echo "Logs:      sudo journalctl -u redhands-hub -f"
echo "Note:      Port 9000 is held by Docker bronvault_clickhouse; hub uses $HUB_PORT instead."