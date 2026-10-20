#!/usr/bin/env bash
# ============================================================================
# launch_frost_hub.sh - macOS/Linux launcher for the Frost hub
# (mirrors launch_frost_hub.ps1 on Windows; operator directive 2026-10-21:
# the whole system must be runnable by Mac users, locally or via the gx10).
#
# Keys: export ABLITERATION_API_KEY / ABLITERATION_ADMIN_KEY in your shell
# profile (~/.zshrc), or source a keys file before running. On first run:
#
#   export ABLITERATION_ADMIN_KEY="sk_..."   # org admin key
#   export ABLITERATION_API_KEY="ak_..."     # inference key
#   python3 abliteration_keys.py ensure-pool 2   # mint the 2-key pool
#
# Usage:  bash launch_frost_hub.sh [port]
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-9000}"

: "${ABLITERATION_API_KEY:?export ABLITERATION_API_KEY (ak_... inference key) first}"
: "${ABLITERATION_ADMIN_KEY:?export ABLITERATION_ADMIN_KEY (sk_... admin key) first}"

# --- Frost system environment (single source for this boot) -------------------
export PRIMARY_API_URL="https://api.abliteration.ai/v1/chat/completions"
export PRIMARY_API_KEY="$ABLITERATION_API_KEY"
export PRIMARY_MODEL="abliterated-model-large-v2"
export FALLBACK_API_URL="http://100.67.13.78:4000/v1/chat/completions"   # gx10 hub (CYBER-FROST)
export FALLBACK_API_KEY="none"
export FALLBACK_MODEL="CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"
export SPECIALIST_API_URL="https://api.abliteration.ai/v1/chat/completions"
export SPECIALIST_API_KEY="$ABLITERATION_API_KEY"
export SPECIALIST_MODEL="abliterated-model-large-v2"
export ABLITERATION_ADMIN_KEY="$ABLITERATION_ADMIN_KEY"
# The hub offers ONLY the three constellation chains
export CONSTELLATION_ONLY="1"
export MAX_THINK_MIN_TOKENS="32768"
export NO_GO_ENABLED="1"
export HEDGE_MAX_TOKENS="8192"
export SPECIALIST_MAX_TOKENS="16384"
export MAX_CONCURRENT_STREAMS="64"
export PYTHONUNBUFFERED="1"

echo "Frost hub starting on :$PORT (catalog: the 3 constellation chains)"
exec python3 -m uvicorn proxy_gateway:app --host 0.0.0.0 --port "$PORT"
