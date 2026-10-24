# deploy_soak.ps1 - deploys the RedHands Hub soak rig to the gx10.
# PC-side ONLY: rerun when the code changes; the rig itself never depends
# on this PC (systemd + linger keep it alive through reboots of BOTH boxes).
#
#   powershell -File soak/deploy_soak.ps1            # deploy + restart
#   powershell -File soak/deploy_soak.ps1 -Fresh     # also reset corpus
param([switch]$Fresh)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent

# --- 1. the Hive key (User scope -> Machine scope -> placeholder) ---------
$hive = [Environment]::GetEnvironmentVariable("HIVE_SECRET_KEY", "User")
if (-not $hive) { $hive = [Environment]::GetEnvironmentVariable("HIVE_SECRET_KEY", "Machine") }
if (-not $hive) { Write-Host "HIVE_SECRET_KEY not found in User/Machine scope - account_pool.json remains the credential source" }

# --- 2. ship the repo (code + evals + account pool; no git/cache) -------
Write-Host "packing the repo..."
$excl = "--exclude=.git", "--exclude=__pycache__", "--exclude=evals/results",
        "--exclude=node_modules", "--exclude=*.log"
$tar = "tar czf - -C `"$ROOT`" " + ($excl -join " ") + " ."
ssh gx10 "mkdir -p ~/soak/repo"
Invoke-Expression "$tar | ssh gx10 `"tar xzf - -C ~/soak/repo`""

# --- 3. the rig files ------------------------------------------------------
ssh gx10 "mkdir -p ~/soak/defects"
scp -q "$PSScriptRoot/ablit_mock.py" "$PSScriptRoot/soak_loop.py" gx10:~/soak/
scp -q "$PSScriptRoot/soak-ablit-mock.service" "$PSScriptRoot/soak-hub.service" "$PSScriptRoot/soak-loop.service" gx10:~/.config/systemd/user/

# --- 4. hub.env: real Hive DEEP/GLM + the mock for abliteration ----------
$envBody = @"
HUB_NAME=RedHands Hub
PRIMARY_API_URL=https://api-cdn.thehive.ai/api/v3/chat/completions
PRIMARY_API_KEY=$hive
PRIMARY_MODEL=zai-org/glm-5.3-flash
FALLBACK_API_URL=http://127.0.0.1:4100/v1/chat/completions
FALLBACK_API_KEY=soak-mock
FALLBACK_MODEL=abliterated-model-large-v2
SPECIALIST_API_URL=http://127.0.0.1:4100/v1/chat/completions
SPECIALIST_API_KEY=soak-mock
SPECIALIST_MODEL=abliterated-model-large-v2
MOCK_ABLITERATION=1
WORKER_API_URL=https://api-cdn.thehive.ai/api/v3/chat/completions
WORKER_API_KEY=$hive
WORKER_MODEL=deepseek-ai/deepseek-v4.1-flash-1017
HIDE_ABLIT_MODELS=0
HEDGE_RACE_MODE=1
REDSHANDS_AUTO_TAKEOVER=1
RACE_GRACE_MS=2000
RACE_PEER_MIN_CHARS=120
RACE_PEER_MAX_WAIT_MS=2500
CHAIN_HOP_STATUS=1
"@
# preserve any tinker-adjusted knobs across deploys
$envBody | ssh gx10 "if [ ! -f ~/soak/hub.env ]; then cat > ~/soak/hub.env; else echo keeping existing hub.env; fi"
if ($Fresh) { $envBody | ssh gx10 "cat > ~/soak/hub.env"; ssh gx10 "rm -f ~/soak/corpus.json ~/soak/state.json ~/soak/FLAWLESS.txt" }

# --- 5. deps + services + linger ------------------------------------------
ssh gx10 "python3 -c 'import fastapi, uvicorn, httpx' 2>/dev/null || pip3 install --user fastapi uvicorn httpx"
ssh gx10 "loginctl enable-linger nick 2>/dev/null; mkdir -p ~/.config/systemd/user; systemctl --user daemon-reload"
ssh gx10 "systemctl --user enable --now soak-ablit-mock.service; systemctl --user restart soak-ablit-mock.service"
ssh gx10 "systemctl --user enable --now soak-hub.service; systemctl --user restart soak-hub.service; sleep 6"
ssh gx10 "curl -s -m 8 http://127.0.0.1:4100/v1/models >/dev/null && echo mock:4100 up; curl -s -m 8 http://127.0.0.1:9100/healthz | head -c 220; echo"
ssh gx10 "systemctl --user enable --now soak-loop.service; systemctl --user restart soak-loop.service"
ssh gx10 "systemctl --user status soak-ablit-mock.service soak-hub.service soak-loop.service --no-pager | head -24"
Write-Host ""
Write-Host "SOAK RIG DEPLOYED. Observe:  ssh gx10 'tail -f ~/soak/report.txt'"
