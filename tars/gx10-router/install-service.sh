#!/usr/bin/env bash
# Install the systemd USER unit + enable (linger is already on for nick).
set -euo pipefail
DIR="/home/nick/tars-litellm-router"
if ! "$DIR/.venv/bin/pip" show litellm >/dev/null 2>&1; then
  echo "litellm not installed yet - run deploy.sh first and wait for pip."; exit 1
fi
mkdir -p /home/nick/.config/systemd/user
cp "$DIR/litellm-router.service" /home/nick/.config/systemd/user/litellm-router.service
systemctl --user daemon-reload
systemctl --user enable litellm-router.service
systemctl --user restart litellm-router.service
sleep 3
systemctl --user --no-pager --lines=0 status litellm-router.service || true
loginctl show-user "$USER" -p Linger
