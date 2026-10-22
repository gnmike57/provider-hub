#!/usr/bin/env bash
# ============================================================================
# Verify the provider-hub endpoints are reachable from the gx10 (tailnet).
#
# Default surface (2026-10-21): the current per-model port family, including
# the team surface - all on 100.113.176.84 (PROBE_HOST, overridable):
#
#   :9310  /v1/chat/completions   general port (any model id; hedge worker)
#   :9316  /v1/chat/completions   team surface (always-on, V2 Large terminal)
#
# LEGACY :9200 probe (the old monolithic hub port, retired when the per-model
# serve_endpoints family took over): still reachable behind an explicit
#
#     LEGACY_PROBE=1 ./tools/hive/_verify_from_gx10.sh
#
# Nothing here mutates state; every probe is a read-or-chat HTTP call.
#
# DRY RUN (no network at all - CI / syntax safe):
#     DRY_RUN=1 ./tools/hive/_verify_from_gx10.sh
#     DRY_RUN=1 LEGACY_PROBE=1 ./tools/hive/_verify_from_gx10.sh
# In DRY_RUN each probe prints the exact curl argv it would run and exits 0.
#
# Exit code: 0 when nothing failed, 1 on any hard probe failure (network
# errors fail; a reachable port whose reply we cannot parse is a soft skip).
# ============================================================================
set -u
DRY_RUN="${DRY_RUN:-0}"
LEGACY_PROBE="${LEGACY_PROBE:-0}"
PROBE_HOST="${PROBE_HOST:-100.113.176.84}"
GENERAL_PORT="${GENERAL_PORT:-9310}"
TEAM_PORT="${TEAM_PORT:-9316}"
LEGACY_PORT="${LEGACY_PORT:-9200}"

if [ "$DRY_RUN" = "1" ]; then
  # In dry-run "curl" is a no-op printer; see run_probe() below.
  curl() {
    local desc="${1:-}"; shift
    printf 'DRY-RUN [%s] curl' "$desc"
    printf ' %q' "$@"
    printf '\n'
  }
fi

# run_probe <description> <curl args...>
#   - live mode: prints the reply head, then "<desc>: OK|FAILED: <reason>"
#   - dry mode : prints the argv instead (curl is the stub above); always OK
run_probe() {
  local desc="$1"; shift
  echo "--- $desc ---"
  local out rc
  if [ "$DRY_RUN" = "1" ]; then
    curl "$desc" "$@"
    echo "$desc: OK (dry-run, no network)"
    return 0
  fi
  out=$(curl "$@" 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$desc: FAILED: curl exit $rc: $(printf '%s' "$out" | head -c 200)"
    return 1
  fi
  printf '%s\n' "$out" | head -c 500
  printf '\n%s: OK\n' "$desc"
  return 0
}

# probe_chat <label> <host> <port> <model-id> <marker>
#   POSTs a tiny non-streaming completion; OK when curl succeeds (the reply
#   body is printed for the human; content correctness is not asserted here).
probe_chat() {
  local label="$1" host="$2" port="$3" model="$4" marker="$5"
  local url="http://${host}:${port}/v1/chat/completions"
  local body
  body=$(printf '{"model":"%s","messages":[{"role":"user","content":"Reply with exactly: %s"}],"stream":false,"max_tokens":96}' \
    "$model" "$marker")
  run_probe "$label" -s -m 90 -X POST "$url" \
    -H 'Content-Type: application/json' -d "$body"
}

# probe_reach <label> <host> <port> [path]
#   Connection-only liveness check (-o /dev/null, prints code + timing).
probe_reach() {
  local label="$1" host="$2" port="$3" path="${4:-/v1/models}"
  local url="http://${host}:${port}${path}"
  if [ "$DRY_RUN" = "1" ]; then
    run_probe "$label" -s -o /dev/null -m 8 -w 'connect=%{http_code} time=%{time_total}s' "$url"
    return $?
  fi
  echo "--- $label ---"
  local out
  if out=$(curl -s -o /dev/null -m 8 -w 'connect=%{http_code} time=%{time_total}s' "$url"); then
    echo "$out"
    echo "$label: OK"
    return 0
  fi
  echo "$label: FAILED: $(printf '%s' "$out" | head -c 200)"
  return 1
}

PROBE_RC=0
step() { step_rc=$?; [ "$step_rc" -eq 0 ] || PROBE_RC=$step_rc; return 0; }

echo "=== provider-hub reachability from gx10 (host=$PROBE_HOST, dry_run=$DRY_RUN) ==="

# --- current surface: general + team ports ---------------------------------
probe_reach "reach :$GENERAL_PORT (general)" "$PROBE_HOST" "$GENERAL_PORT"; step
probe_reach "reach :$TEAM_PORT (team)" "$PROBE_HOST" "$TEAM_PORT"; step
probe_chat "model: deepseek-ai/deepseek-v4.1-flash-1017 [:${GENERAL_PORT}]" \
  "$PROBE_HOST" "$GENERAL_PORT" \
  "deepseek-ai/deepseek-v4.1-flash-1017" "GX10-EP-OK"; step
probe_chat "model: zai-org/glm-5.3-flash [:${GENERAL_PORT}]" \
  "$PROBE_HOST" "$GENERAL_PORT" \
  "zai-org/glm-5.3-flash" "GX10-GLM-OK"; step
probe_chat "team surface [:${TEAM_PORT} model=team]" \
  "$PROBE_HOST" "$TEAM_PORT" \
  "team" "GX10-TEAM-OK"; step

# --- legacy surface: opt-in only --------------------------------------------
if [ "$LEGACY_PROBE" = "1" ]; then
  echo "(LEGACY_PROBE=1: including the retired :${LEGACY_PORT} hub probe)"
  probe_reach "LEGACY reach :${LEGACY_PORT}" "$PROBE_HOST" "$LEGACY_PORT"; step
  probe_chat "LEGACY chat [:${LEGACY_PORT} deepseek-v4.1-flash-1017]" \
    "$PROBE_HOST" "$LEGACY_PORT" \
    "deepseek-ai/deepseek-v4.1-flash-1017" "GX10-EP-OK"; step
  probe_chat "LEGACY chat [:${LEGACY_PORT} glm-5.3-flash]" \
    "$PROBE_HOST" "$LEGACY_PORT" \
    "zai-org/glm-5.3-flash" "GX10-GLM-OK"; step
else
  echo "(legacy :${LEGACY_PORT} probe skipped - set LEGACY_PROBE=1 to include it)"
fi

if [ "$PROBE_RC" -eq 0 ]; then
  echo "=== VERIFY: all probes OK ==="
else
  echo "=== VERIFY: FAILURES PRESENT (see FAILED lines above) ==="
fi
exit "$PROBE_RC"
