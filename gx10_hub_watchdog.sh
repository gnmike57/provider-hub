#!/usr/bin/env bash
# ============================================================================
# gx10_hub_watchdog.sh - watchdog for the RedHands Hub on gx10 (Linux)
#
# Probes /healthz and restarts the systemd service if unhealthy.
# Intended to be run via cron or systemd timer every minute.
#
# Usage:
#   bash gx10_hub_watchdog.sh              # single pass
#   bash gx10_hub_watchdog.sh -loop        # resident loop
# ============================================================================
set -euo pipefail

REMOTE="${GX10_HOST:-gx10}"
HUB_PORT=9001
HEALTH_URL="http://127.0.0.1:${HUB_PORT}/healthz"
FAIL_THRESHOLD=2
RECOVERY_COOLDOWN=120
STATE_FILE="/tmp/redhands_hub_watchdog_state.txt"
LOGFILE="/var/log/redhands_hub_watchdog.log"

MODE="${1:-once}"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $*" | tee -a "$LOGFILE" 2>/dev/null || echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $*"
}

probe_health() {
  ssh "$REMOTE" "curl -s -m 10 $HEALTH_URL" 2>/dev/null | grep -q '"ok": *true' && return 0 || return 1
}

restart_hub() {
  log "Restarting redhands-hub.service..."
  ssh "$REMOTE" "sudo systemctl restart redhands-hub.service"
  sleep 8
  if probe_health; then
    log "Hub healthy after restart."
    return 0
  else
    log "ERROR: Hub still unhealthy after restart."
    return 1
  fi
}

read_last_restart() {
  if [ -f "$STATE_FILE" ]; then
    cat "$STATE_FILE" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

write_last_restart() {
  echo "$(date +%s)" > "$STATE_FILE"
}

# --- main ------------------------------------------------------------------
if [ "$MODE" = "-loop" ]; then
  while true; do
    bash "$0" once
    sleep 15
  done
  exit 0
fi

# Single pass
fail_count=0
for ((i=1; i<=FAIL_THRESHOLD; i++)); do
  if probe_health; then
    log "Hub healthy on :${HUB_PORT}."
    exit 0
  fi
  if [ $i -lt $FAIL_THRESHOLD ]; then
    sleep 3
  fi
  fail_count=$i
done

log "Hub unhealthy (${fail_count} consecutive /healthz failures)."

# Cooldown check
last=$(read_last_restart)
now=$(date +%s)
age=$((now - last))
if [ "$age" -lt "$RECOVERY_COOLDOWN" ] && [ "$last" -gt 0 ]; then
  log "Holding off restart: last recovery ${age}s ago (< ${RECOVERY_COOLDOWN}s cooldown)."
  exit 1
fi

restart_hub
write_last_restart
exit 0