# activate_v2_primary.ps1 - Phase 1 ACTIVATION: flip the live hub onto abliterated-model-large-v2.
#
# STAGED 2026-10-20: the Abliteration org was still payment_required (402
# insufficient_credits), so the V2 slot snapshot lives in
# slot_bindings.staged-v2.json and the LIVE hub keeps boot-restoring
# Hive/redhands from slot_bindings.json. Run THIS script once credits are
# live; it refuses to flip while the org still 402s.
#
# What it does:
#   1. GATE: POST one tiny completion to Abliteration - must return HTTP 200
#      (402 insufficient_credits => abort, nothing is touched).
#   2. Append the staged V2 snapshot to slot_bindings.json with a FRESH ts
#      (BindingHistory drops entries older than 7 days, so ts=0 in the staged
#      file is a placeholder; a live ts is mandatory).
#   3. Restart the hub (launch_redhands_hub.ps1 -Force) - its boot-restore then
#      binds helm+specialist to V2-direct, scout stays on local redhands.
#   4. Verify /healthz shows ablit/abliterated-model-large-v2 on primary+worker.
#
# Rollback:  POST /v1/switch {"target":"primary","rollback":true} (or delete the
# last line of slot_bindings.json and rerun launch_redhands_hub.ps1 -Force).
#
# Race note: a runtime switch on the LIVE hub rewrites slot_bindings.json from its
# in-memory history, so this script appends the line immediately before restarting.
[CmdletBinding()]
param(
    # Skip the credits gate (you already verified the org is payable).
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot
# Abliteration chat key: Windows user-scope env var (installed 2026-10-21); no secret in source.
$KEY  = $env:ABLITERATION_API_KEY
if (-not $KEY) { $KEY = [Environment]::GetEnvironmentVariable('ABLITERATION_API_KEY', 'User') }
if (-not $KEY) { Write-Output "ABLITERATION_API_KEY not set - install the Abliteration keys first"; exit 1 }
$HEALTH = "http://127.0.0.1:9000/healthz"

# --- 1. credits gate --------------------------------------------------------
$gateBody = '{"model":"abliterated-model-large-v2","messages":[{"role":"user","content":"Reply with exactly: V2-OK"}],"max_tokens":16}'
try {
    $r = Invoke-RestMethod -Uri "https://api.abliteration.ai/v1/chat/completions" -Method Post `
        -Headers @{ Authorization = "Bearer $KEY" } -ContentType "application/json" -Body $gateBody -TimeoutSec 60
    Write-Output ("GATE: HTTP 200 OK, model said: " + $r.choices[0].message.content)
} catch {
    $code = 0
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    Write-Output "GATE: FAILED (HTTP $code) - Abliteration is not payable yet; NOT activating."
    if (-not $Force) { exit 1 }
    Write-Output "(-Force given: continuing anyway)"
}

# --- 2. append the staged snapshot with a fresh ts ---------------------------
$stagedFile = Join-Path $ROOT "slot_bindings.staged-v2.json"
$slotFile   = Join-Path $ROOT "slot_bindings.json"
$entry = Get-Content -LiteralPath $stagedFile -Raw | ConvertFrom-Json
$entry.ts = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
$entry.request_id = "v2-activate-" + (Get-Date -Format 'yyyyMMdd-HHmmss')
$line = $entry | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath $slotFile -Value $line -Encoding utf8
Write-Output "APPENDED V2 snapshot to slot_bindings.json (newest line wins boot-restore)."

# --- 3. restart the hub ------------------------------------------------------
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ROOT "launch_redhands_hub.ps1") -Force
if ($LASTEXITCODE -ne 0) { Write-Output "launch_redhands_hub.ps1 exited $LASTEXITCODE - check evals\redhands_hub_boot.err.log"; exit 1 }

# --- 4. verify --------------------------------------------------------------
$h = Invoke-RestMethod -Uri $HEALTH -TimeoutSec 15
$primary = $h.config.switch.primary
$worker  = $h.config.switch.worker
Write-Output ("VERIFY: healthz ok={0} primary={1}/{2} worker={3}/{4}" -f $h.ok, $primary.provider_id, $primary.model, $worker.provider_id, $worker.model)
if ($primary.provider_id -eq "ablit" -and $worker.provider_id -eq "ablit") {
    Write-Output "ACTIVATION COMPLETE: hub is live on abliterated-model-large-v2 (helm+specialist)."
} else {
    Write-Output "WARNING: slots do not show ablit yet - inspect slot_bindings.json and the boot log."
    exit 1
}
