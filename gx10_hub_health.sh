#!/usr/bin/env bash
# ============================================================================
# gx10_hub_health.sh - health check for the RedHands Hub on gx10
#
# Usage:
#   bash gx10_hub_health.sh              # check localhost
#   bash gx10_hub_health.sh tailnet      # check via tailnet name
#   bash gx10_hub_health.sh ip           # check via tailnet IP
# ============================================================================
set -euo pipefail

REMOTE="${GX10_HOST:-gx10}"
HUB_PORT=9001

MODE="${1:-local}"

case "$MODE" in
  local|localhost)
    URL="http://127.0.0.1:${HUB_PORT}/healthz"
    ssh "$REMOTE" "curl -s -m 10 $URL"
    ;;
  tailnet|name)
    URL="http://gx10.ayu-sidewinder.ts.net:${HUB_PORT}/healthz"
    curl -s -m 10 "$URL"
    ;;
  ip)
    URL="http://100.67.13.78:${HUB_PORT}/healthz"
    curl -s -m 10 "$URL"
    ;;
  service)
    ssh "$REMOTE" "sudo systemctl is-active redhands-hub.service && sudo systemctl is-enabled redhands-hub.service"
    ;;
  *)
    echo "usage: gx10_hub_health.sh [local|tailnet|ip|service]"
    exit 1
    ;;
esac