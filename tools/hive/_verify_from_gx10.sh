#!/usr/bin/env bash
# Verify the provider-hub endpoint is reachable from the gx10 (tailnet).
U="http://100.113.176.84:9200/v1/chat/completions"
echo "--- reachability ---"
curl -s -o /dev/null -m 8 -w "connect=%{http_code} time=%{time_total}s\n" "$U" || echo "unreachable"
echo "--- model: deepseek-ai/deepseek-v4.1-flash ---"
curl -s -m 90 -X POST "$U" -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-ai/deepseek-v4.1-flash","messages":[{"role":"user","content":"Reply with exactly: GX10-EP-OK"}],"stream":false,"max_tokens":96}' \
  | head -c 500
echo
echo "--- model: zai-org/glm-5.3-flash ---"
curl -s -m 90 -X POST "$U" -H 'Content-Type: application/json' \
  -d '{"model":"zai-org/glm-5.3-flash","messages":[{"role":"user","content":"Reply with exactly: GX10-GLM-OK"}],"stream":false,"max_tokens":96}' \
  | head -c 500
echo
