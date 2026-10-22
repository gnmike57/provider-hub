# install_goal_watchdog.ps1 - registers the "Goal Watchdog" scheduled task:
# the survive-anything layer of the /goal skill (operator directive
# 2026-10-23). The task fires at logon AND every minute; each fire runs
# `goal_engine.py watchdog-auto`, which starts the 30s survivor loop for the
# ACTIVE goal only when it is not already running (single-instance mutex) -
# so the poller survives session death, IDE restarts, and reboots, and
# never double-runs. Idempotent; safe to re-run.
[CmdletBinding()]
param(
    [switch]$Remove  # uninstall the task instead
)

$ROOT = "C:\Users\lnxzf\Desktop\projects\provider-hub"
$PY = "C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe"

if ($Remove) {
    Unregister-ScheduledTask -TaskName "Goal Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Goal Watchdog task removed."
    return
}

if (-not (Test-Path $PY)) { throw "python not found at $PY" }

$execute = "powershell.exe"
$arguments = ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass " +
             "-Command `"Set-Location '$ROOT'; & '$PY' goal_engine.py watchdog-auto`"")

$action = New-ScheduledTaskAction -Execute $execute -Argument $arguments
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerEveryMinute = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
    -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "Goal Watchdog" -Action $action `
    -Trigger $triggerLogon, $triggerEveryMinute -Settings $settings `
    -Principal $principal -Force | Out-Null

Write-Host "Goal Watchdog task registered (logon + every-minute triggers)."
Write-Host "It keeps the 30s poller alive for the ACTIVE goal; no-op when none."
Write-Host "Remove with: powershell -File install_goal_watchdog.ps1 -Remove"
