# open_control_room.ps1 - open the Model Constellation Control Room in the
# default browser, launching the hub first when it is not already listening.
#
# The hub launcher is idempotent: running it while the hub is healthy is a
# no-op, so this shortcut is safe to press any time. "Healthy" is the ONE
# shared definition (redhands_common.ps1 Test-HubHealth): HTTP 200 AND ok:true -
# the Control Room opens under the same guarantee the watchdog and launcher
# use, not a private "any 200 counts" copy. If the hub comes up degraded
# (ok:false), we still open the page after the wait - it renders per-pane.
$ErrorActionPreference = "SilentlyContinue"
$ROOT = $PSScriptRoot
$URL = "http://127.0.0.1:9000/admin/models"
$HEALTH_URL = "http://127.0.0.1:9000/healthz"

. (Join-Path $ROOT "redhands_common.ps1")

if (-not (Test-HubHealth 3 $HEALTH_URL)) {
    Start-Process -WindowStyle Hidden powershell.exe -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$ROOT\launch_redhands_hub.ps1`""
    ) | Out-Null
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline -and -not (Test-HubHealth 3 $HEALTH_URL)) {
        Start-Sleep -Milliseconds 500
    }
}

Start-Process $URL
