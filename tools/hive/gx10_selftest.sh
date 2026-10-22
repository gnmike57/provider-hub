#!/usr/bin/env bash
# ============================================================================
# Final gx10 check: plain call (no --resolve DNS workaround), streaming check,
# second model (GLM 5.3 Flash). 2026-10-21 hardened:
#   - KEY resolution is env-first (HIVE_API_KEY), file fallback second
#     (HIVE_KEY_FILE or the original $HOME/ufo-galaxy/hive_cleanpass/ufo.env
#     path), with a clear (never secret-echoing) error when neither yields one.
#   - DRY_RUN=1 prints the exact requests and exits 0 - no network, CI-safe.
#   - set -u; exit code 0 only when every check succeeded.
# Nothing here mutates state; every probe is a chat HTTP call.
# ============================================================================
set -u
DRY_RUN="${DRY_RUN:-0}"
URL="${HIVE_URL:-https://api-cdn.thehive.ai/api/v3/chat/completions}"
GLM_MODEL="${GLM_MODEL:-zai-org/glm-5.3-flash}"
DS_MODEL="${DS_MODEL:-deepseek-ai/deepseek-v4.1-flash-1017}"
KEY_FILE="${HIVE_KEY_FILE:-$HOME/ufo-galaxy/hive_cleanpass/ufo.env}"

# --- key resolution: env first, file fallback, loud failure (never echoed) ---
KEY="${HIVE_API_KEY:-}"
KEY_SRC="env"
if [ -z "$KEY" ]; then
  KEY_SRC="file:$KEY_FILE"
  if [ -r "$KEY_FILE" ]; then
    KEY=$(grep '^HIVE_SECRET_KEY=' "$KEY_FILE" | head -1 | cut -d= -f2-)
  fi
fi
if [ -z "$KEY" ]; then
  echo "ERROR: no API key found (looked at HIVE_API_KEY, then HIVE_SECRET_KEY in $KEY_FILE)." >&2
  echo "       Set HIVE_API_KEY=... (or HIVE_KEY_FILE=...) and retry." >&2
  exit 1
fi
echo "--- key: loaded ($KEY_SRC) ---"
AUTH_H="Authorization: Bearer $KEY"

# probe_chat <label> <stream: true|false> <model> <marker> [extra curl args...]
#   POSTs a chat completion; in live mode the reply head is printed (for the
#   streaming check pass -N -m 25 and pipe through tail at the call site).
probe_chat() {
  local label="$1" stream="$2" model="$3" marker="$4"
  shift 4
  local body
  body=$(printf '{"model":"%s","messages":[{"role":"user","content":"Reply with exactly: %s"}],"max_completion_tokens":48,"stream":%s}' \
    "$model" "$marker" "$stream")
  echo "--- $label ---"
  if [ "$DRY_RUN" = "1" ]; then
    # Redact the Authorization header in the printed argv (never echo secrets).
    printf 'DRY-RUN [%s] curl' "$label"
    printf ' %q' -s "$@" "$URL" -H 'Authorization: Bearer ***REDACTED***' \
      -H 'Content-Type: application/json' -d "$body"
    printf '\n'
    echo "$label: OK (dry-run, no network)"
    return 0
  fi
  local out rc
  out=$(curl -s "$@" "$URL" -H "$AUTH_H" -H 'Content-Type: application/json' -d "$body" 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "$label: FAILED: curl exit $rc: $(printf '%s' "$out" | head -c 200)"
    return 1
  fi
  printf '%s\n' "$out" | head -c 300
  printf '\n%s: OK\n' "$label"
  return 0
}

# print_tail <file-ish string>: show only the last 300 bytes (stream checks).
print_tail() { printf '%s' "$1" | tail -c 300; }

RC=0
step() { step_rc=$?; [ "$step_rc" -eq 0 ] || RC=$step_rc; return 0; }

# Original check 1: plain (non-streaming) call, 20s curl timeout.
probe_chat "plain curl, no --resolve [GLM]" false "$GLM_MODEL" "GLM-OK-FROM-GX10" -m 20; step

# Original check 2: streaming call; live mode shows the TAIL (302 bytes) so the
# final data:/[DONE] frames are visible; dry-run shows the argv only.
if [ "$DRY_RUN" = "1" ]; then
  probe_chat "streaming check [deepseek-v4.1-flash-1017, tail]" true "$DS_MODEL" \
    "STREAM-OK" -N -m 25; step
else
  echo "--- streaming check [deepseek-v4.1-flash-1017, tail] ---"
  body=$(printf '{"model":"%s","messages":[{"role":"user","content":"Reply with exactly: STREAM-OK"}],"max_completion_tokens":48,"stream":true}' "$DS_MODEL")
  out=$(curl -s -N -m 25 "$URL" -H "$AUTH_H" -H 'Content-Type: application/json' -d "$body" 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "streaming check: FAILED: curl exit $rc: $(printf '%s' "$out" | head -c 200)"
    RC=1
  else
    print_tail "$out"
    printf '\nstreaming check: OK\n'
  fi
fi

if [ "$RC" -eq 0 ]; then
  echo "=== SELFTEST: all checks OK ==="
else
  echo "=== SELFTEST: FAILURES PRESENT (see FAILED lines above) ==="
fi
exit "$RC"
