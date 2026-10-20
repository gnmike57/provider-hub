#!/usr/bin/env bash
# ============================================================================
# tars-hybrid-router verification v2 (auth-aware: master key = the ak_ key).
# Tests: liveness, model list, V2-large chat through the router, the vision
# bridge (image sent to the TEXT-ONLY model), and /v1/responses.
# ============================================================================
set -uo pipefail
R=http://127.0.0.1:4001
KEY=$(grep -oP '^ABLITERATION_API_KEY=\K.*' /home/nick/tars-litellm-router/router.env | tr -d '\r\n[:space:]')
AUTH="Authorization: Bearer $KEY"

echo "--- 1. liveness ---"
curl -s -m 10 "$R/health/liveliness"; echo

echo "--- 2. models ---"
curl -s -m 10 -H "$AUTH" "$R/v1/models" | head -c 400; echo

echo "--- 3. chat: abliterated-model-large-v2 via router ---"
curl -s -m 120 -H "$AUTH" -H "Content-Type: application/json" \
  "$R/v1/chat/completions" \
  -d '{"model":"abliterated-model-large-v2","messages":[{"role":"user","content":"Reply with exactly: V2-OK"}],"max_tokens":64}' \
  | head -c 500; echo

echo "--- 4. vision bridge: IMAGE to text-only V2 large ---"
cat > /tmp/tars-vision-test.json <<'EOF'
{"model":"abliterated-model-large-v2","messages":[{"role":"user","content":[{"type":"text","text":"A screenshot is attached; the router's vision sensor captioned it for you. Reply with exactly: BRIDGE-OK"},{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}}]}],"max_tokens":64}
EOF
curl -s -m 240 -H "$AUTH" -H "Content-Type: application/json" \
  "$R/v1/chat/completions" -d @/tmp/tars-vision-test.json | head -c 600; echo
rm -f /tmp/tars-vision-test.json

echo "--- 5. responses API via router ---"
curl -s -m 120 -H "$AUTH" -H "Content-Type: application/json" \
  "$R/v1/responses" \
  -d '{"model":"abliterated-model-large-v2","input":"Reply with exactly: RESPONSES-OK","max_output_tokens":64}' \
  | head -c 500; echo

echo "--- 6. caddy tars.local alias ---"
curl -s -m 8 -H "Host: tars.local" http://127.0.0.1/health/liveliness; echo
echo "--- 7. recent bridge logs ---"
journalctl --user -u litellm-router.service --no-pager -n 20 2>/dev/null | grep -i "vision-bridge" | tail -6

echo "--- 8. caddy config linkage ---"
grep -n "import\|abliterated-proxy" /etc/caddy/Caddyfile 2>/dev/null | head -5 || echo "(no /etc/caddy/Caddyfile readable)"

echo "--- 9. npm error detail ---"
tail -12 /home/nick/agent-tars/npm-install.log 2>/dev/null

