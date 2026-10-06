#!/usr/bin/env bash
# Final gx10 check: plain call, no DNS workaround, second model (GLM 5.3 Flash).
KEY=$(grep '^HIVE_SECRET_KEY=' "$HOME/ufo-galaxy/hive_cleanpass/ufo.env" | cut -d= -f2-)
echo "--- plain curl, no --resolve ---"
curl -s -m 20 https://api-cdn.thehive.ai/api/v3/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"zai-org/glm-5.3-flash","messages":[{"role":"user","content":"Reply with exactly: GLM-OK-FROM-GX10"}],"stream":false,"max_completion_tokens":48}' \
  | head -c 300
echo
echo "--- streaming check ---"
curl -s -N -m 25 https://api-cdn.thehive.ai/api/v3/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-ai/deepseek-v4.1-flash","messages":[{"role":"user","content":"Reply with exactly: STREAM-OK"}],"stream":true,"max_completion_tokens":48}' \
  | tail -c 300
echo
