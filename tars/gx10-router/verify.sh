#!/usr/bin/env bash
# ============================================================================
# tars-hybrid-router verification v2 (auth-aware: master key = the ak_ key).
# Tests: liveness, model list, V2-large chat through the router, the vision
# bridge (image sent to the TEXT-ONLY model), and /v1/responses.
#
# 2026-10-21 hardened (behavior-preserving):
#   - set -euo pipefail (was: set -uo pipefail, which hid the first failure).
#     KEY_ENFORCE=0 keeps exploratory runs going without a key.
#   - KEY resolution is env-first (ABLITERATION_API_KEY env), file fallback
#     second (ROUTER_ENV_FILE or the original /home/nick/tars-litellm-router/
#     router.env path); the key value is never echoed.
#   - DRY_RUN=1 prints the exact requests and exits 0 - no network, no log or
#     Caddyfile reads; CI-safe.
#   - every remote probe failure is reported with a clear FAILED line and the
#     script exits non-zero if any failed; report-only steps (7-9) stay
#     non-fatal so real probe failures remain the only hard failures.
# ============================================================================
set -euo pipefail
DRY_RUN="${DRY_RUN:-0}"
KEY_ENFORCE="${KEY_ENFORCE:-1}"
R="${ROUTER_BASE:-http://127.0.0.1:4001}"
ROUTER_ENV_FILE="${ROUTER_ENV_FILE:-/home/nick/tars-litellm-router/router.env}"
NONFATAL=0

# notefail <label>: record a failed step without aborting (report-only steps).
notefail() { echo "  (non-fatal: $1 failed or matched nothing)"; NONFATAL=$((NONFATAL + 1)); return 0; }

# --- key resolution: env first, file fallback, loud failure (never echoed) ---
KEY="${ABLITERATION_API_KEY:-}"
KEY_SRC="env"
if [ -z "$KEY" ] && [ -r "$ROUTER_ENV_FILE" ]; then
  KEY_SRC="file:$ROUTER_ENV_FILE"
  KEY=$(grep -oP '^ABLITERATION_API_KEY=\K.*' "$ROUTER_ENV_FILE" | tr -d '\r\n[:space:]')
fi
if [ -n "$KEY" ]; then
  echo "--- key: loaded ($KEY_SRC) ---"
  AUTH="Authorization: Bearer $KEY"
elif [ "$KEY_ENFORCE" = "1" ]; then
  echo "ERROR: no router key found (looked at ABLITERATION_API_KEY, then" >&2
  echo "       ABLITERATION_API_KEY in $ROUTER_ENV_FILE). Set ABLITERATION_API_KEY=..." >&2
  echo "       or ROUTER_ENV_FILE=... and retry; KEY_ENFORCE=0 skips this check." >&2
  exit 1
else
  echo "--- key: NONE (KEY_ENFORCE=0; unauthenticated probes will 401) ---"
  AUTH=""
fi

# probe <label> [curl args...]
probe() {
  local label="$1"; shift
  echo "--- $label ---"
  if [ "$DRY_RUN" = "1" ]; then
    # Redact any Authorization header in the printed argv (never echo secrets).
    printf 'DRY-RUN [%s] curl' "$label"
    local a
    for a in -s -m 10 "$@"; do
      case "$a" in
        "Authorization: Bearer "*) printf ' %q' 'Authorization: Bearer ***REDACTED***' ;;
        *) printf ' %q' "$a" ;;
      esac
    done
    printf '\n'
    echo "$label: OK (dry-run, no network)"
    return 0
  fi
  local out rc
  out=$(curl -s -m 10 "$@" 2>&1) && rc=0 || rc=$?
  if [ $rc -ne 0 ]; then
    echo "$label: FAILED: curl exit $rc: $(printf '%s' "$out" | head -c 200)"
    return 1
  fi
  printf '%s\n' "$out" | head -c 500
  printf '\n%s: OK\n' "$label"
  return 0
}

# ============================================================================
# probe sequence (numbered as in v2; 6-9 are report-only)
# ============================================================================
FAILS=0
step() { step_rc=$?; [ "$step_rc" -eq 0 ] || FAILS=$((FAILS + 1)); return 0; }

if [ "$DRY_RUN" = "1" ]; then
  echo "=== DRY RUN: no network, no log/Caddyfile reads (router base $R) ==="
else
  echo "=== tars-hybrid-router verification (router base $R) ==="
fi

# --- 1-3: liveness / models / chat through the router ------------------------
probe "1. liveness" "$R/health/liveliness"; step
if [ -n "$KEY" ]; then
  probe "2. models" -H "$AUTH" "$R/v1/models"; step
  probe "3. chat: abliterated-model-large-v2 via router" -H "$AUTH" \
    -H "Content-Type: application/json" -m 120 "$R/v1/chat/completions" \
    -d '{"model":"abliterated-model-large-v2","messages":[{"role":"user","content":"Reply with exactly: V2-OK"}],"max_tokens":64}'; step
else
  echo "--- 2. models: SKIPPED (no key) ---"
  echo "--- 3. chat: SKIPPED (no key) ---"
fi


# --- 4. vision bridge (image to the text-only model) -------------------------
if [ "$DRY_RUN" != "1" ]; then
  echo "--- 4. vision bridge: IMAGE to text-only V2 large ---"
  cat > /tmp/tars-vision-test.json <<'EOF'
{"model":"abliterated-model-large-v2","messages":[{"role":"user","content":[{"type":"text","text":"A screenshot is attached; the router's vision sensor captioned it for you. Reply with exactly: BRIDGE-OK"},{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}}]}],"max_tokens":64}
EOF
  if [ -n "$KEY" ]; then
    out=$(curl -s -m 240 -H "$AUTH" -H "Content-Type: application/json" \
      "$R/v1/chat/completions" -d @/tmp/tars-vision-test.json 2>&1) \
      && { printf '%s\n' "$out" | head -c 600; printf '\n4. vision bridge: OK\n'; } \
      || { echo "4. vision bridge: FAILED: $(printf '%s' "$out" | head -c 200)"; FAILS=$((FAILS + 1)); }
  else
    echo "--- 4. vision bridge: SKIPPED (no key) ---"
  fi
  rm -f /tmp/tars-vision-test.json
else
  echo "--- 4. vision bridge: (dry-run: same payload as live mode) SKIPPED ---"
fi

# --- 5. responses API ---------------------------------------------------------
if [ -n "$KEY" ]; then
  probe "5. responses API via router" -H "$AUTH" -H "Content-Type: application/json" \
    -m 120 "$R/v1/responses" \
    -d '{"model":"abliterated-model-large-v2","input":"Reply with exactly: RESPONSES-OK","max_output_tokens":64}'; step
else
  echo "--- 5. responses API: SKIPPED (no key) ---"
fi

# --- 6-9: report-only checks (never fatal) ------------------------------------
echo "--- 6. caddy tars.local alias ---"
if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN: curl -s -m 8 -H 'Host: tars.local' http://127.0.0.1/health/liveliness"
  echo "6. caddy tars.local alias: OK (dry-run)"
else
  out=$(curl -s -m 8 -H "Host: tars.local" http://127.0.0.1/health/liveliness 2>&1) \
    && { printf '%s\n' "$out" | head -c 200; printf '\n6. caddy tars.local alias: OK\n'; } \
    || notefail "step 6 (caddy alias)"
fi

echo "--- 7. recent bridge logs ---"
if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN: journalctl --user -u litellm-router.service --no-pager -n 20 | grep -i vision-bridge | tail -6"
else
  journalctl --user -u litellm-router.service --no-pager -n 20 2>/dev/null \
    | grep -i "vision-bridge" | tail -6 || notefail "step 7 (journalctl/grep)"
fi

echo "--- 8. caddy config linkage ---"
if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN: grep -n 'import|abliterated-proxy' /etc/caddy/Caddyfile | head -5"
else
  grep -n "import\|abliterated-proxy" /etc/caddy/Caddyfile 2>/dev/null | head -5 \
    || echo "(no /etc/caddy/Caddyfile readable)"
fi

echo "--- 9. npm error detail ---"
if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN: tail -12 /home/nick/agent-tars/npm-install.log"
else
  tail -12 /home/nick/agent-tars/npm-install.log 2>/dev/null || notefail "step 9 (npm log)"
fi

echo
if [ "$FAILS" -eq 0 ]; then
  echo "=== VERIFY: all probed steps OK (non-fatal notes: $NONFATAL) ==="
  exit 0
fi
echo "=== VERIFY: $FAILS step(s) FAILED (see FAILED lines above) ==="
exit 1

