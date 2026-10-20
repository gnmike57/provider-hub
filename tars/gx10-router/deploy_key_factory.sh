#!/usr/bin/env bash
# ============================================================================
# deploy_key_factory.sh - run ON THE GX10 (as flak3dd or nick, 2026-10-21).
# Fully enables the Abliteration API key factory + 2-key pool for flak3dd:
#
#   1. installs abliteration_keys.py into /srv/apps/abliteration-keys
#      (the shared neutral area, matching the /srv/apps convention)
#   2. mints/verifies the 2-key throughput pool (needs ABLITERATION_ADMIN_KEY)
#   3. wires the pool keys into BOTH consumers:
#        /home/nick/tars-litellm-router/router.env    (constellation router)
#        /home/flak3dd/.config/llm-hub.env            (the :4000 front door)
#   4. prints the exact restart commands (run the ones you own)
#
# Usage (on the gx10, from a checkout of this repo):
#   export ABLITERATION_ADMIN_KEY="sk_..."    # the org admin key
#   bash tars/gx10-router/deploy_key_factory.sh
# ============================================================================
set -euo pipefail

DEST=/srv/apps/abliteration-keys
ROUTER_ENV=/home/nick/tars-litellm-router/router.env
HUB_ENV=/home/flak3dd/.config/llm-hub.env

: "${ABLITERATION_ADMIN_KEY:?export ABLITERATION_ADMIN_KEY (sk_...) first}"

# --- 1. install the factory (shared, neutral area) ---------------------------
sudo mkdir -p "$DEST"
sudo cp "$(dirname "$0")/../../abliteration_keys.py" "$DEST/"
sudo chmod 644 "$DEST/abliteration_keys.py"
echo "[1/4] factory installed at $DEST/abliteration_keys.py"

# --- 2. mint / verify the 2-key pool ------------------------------------------
cd "$DEST"
POOL_JSON="$DEST/abliteration_pool.json" python3 abliteration_keys.py ensure-pool 2
echo "[2/4] pool ensured (2 keys, round-robin)"

# --- 3. wire the pool keys into the consumers --------------------------------
KEY_A=$(python3 -c "import json;print([k['value'] for k in json.load(open('$DEST/abliteration_pool.json'))['keys'] if k['name']=='hub-pool-1'][0])")
KEY_B=$(python3 -c "import json;print([k['value'] for k in json.load(open('$DEST/abliteration_pool.json'))['keys'] if k['name']=='hub-pool-2'][0])")

wire_env () {
    local envfile="$1"
    if [ ! -f "$envfile" ]; then echo "  (skip: $envfile not present)"; return; fi
    if grep -q '^ABLIT_POOL_KEY_A=' "$envfile"; then
        sudo sed -i "s|^ABLIT_POOL_KEY_A=.*|ABLIT_POOL_KEY_A=$KEY_A|" "$envfile"
        sudo sed -i "s|^ABLIT_POOL_KEY_B=.*|ABLIT_POOL_KEY_B=$KEY_B|" "$envfile"
    else
        printf '\n# 2-key Abliteration pool (deployed by deploy_key_factory.sh)\nABLIT_POOL_KEY_A=%s\nABLIT_POOL_KEY_B=%s\n' \
            "$KEY_A" "$KEY_B" | sudo tee -a "$envfile" >/dev/null
    fi
    echo "  wired: $envfile"
}

echo "[3/4] wiring pool keys:"
wire_env "$ROUTER_ENV"
wire_env "$HUB_ENV"

# --- 4. restart commands (run the ones for services you own) -----------------
cat <<'EOF'
[4/4] restart the consumers:
  systemctl --user restart litellm-router       # as nick   (router :4001)
  systemctl --user restart llm-hub               # as flak3dd (hub :4000)
  # gx10-local factory usage (flak3dd):
  cd /srv/apps/abliteration-keys && python3 abliteration_keys.py status
EOF
echo "DONE: the key factory is fully enabled for flak3dd (and the router)."
