# install_redhands_autostart.ps1 - auto-launch + auto-recover, always-on wiring.
#
# Registers (or repairs) TWO Task Scheduler entries so the RedHands hub is running
# from boot and is put back if it ever dies:
#
#   1. "RedHands Hub"          - launches launch_redhands_hub.ps1 at boot AND at logon.
#                                Start-on-batteries is ALLOWED and going on battery
#                                does NOT stop it (the previous task had both set the
#                                wrong way, so a laptop never started it on battery
#                                and killed it the moment the charger came out).
#                                RestartOnFailure retries the action if it exits 1.
#
#   2. "RedHands Hub Watchdog" - runs watchdog_redhands_hub.ps1 -Once every minute
#                                (plus at boot/logon). Task Scheduler itself is the
#                                supervisor, so recovery survives PowerShell dying.
#
#   3. Desktop shortcut     - "RedHands Hub" shortcut on user's Desktop so the hub
#                             can be launched manually with a double-click.
#
# Both run as SYSTEM / HighestAvailable / unlimited runtime / IgnoreNew, so they
# work with no user logged in and never stack up duplicates.
#
# Usage (self-elevates; UAC prompt appears if not already admin):
#   powershell -ExecutionPolicy Bypass -File install_redhands_autostart.ps1            # install/repair
#   powershell -ExecutionPolicy Bypass -File install_redhands_autostart.ps1 -Status    # show state
#   powershell -ExecutionPolicy Bypass -File install_redhands_autostart.ps1 -Uninstall # remove both
#   powershell -ExecutionPolicy Bypass -File install_redhands_autostart.ps1 -Install -WatchdogIntervalMinutes 1
#   powershell -ExecutionPolicy Bypass -File install_redhands_autostart.ps1 -Shortcut   # desktop shortcut only
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$Shortcut,
    [int]$WatchdogIntervalMinutes = 1,
    # Skip the UAC self-elevation attempt (for nested/automated calls).
    [switch]$NoElevate
)

$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\lnxzf\Desktop\projects\provider-hub"
$LAUNCHER = "$ROOT\launch_redhands_hub.ps1"
$WATCHDOG = "$ROOT\watchdog_redhands_hub.ps1"
$SHORTCUT_NAME = "RedHands Hub.lnk"
$CONTROL_ROOM_NAME = "RedHands Control Room.lnk"
$CONTROL_ROOM_OPENER = "$ROOT\open_control_room.ps1"
$HUB_TASK = "RedHands Hub"
$WD_TASK = "RedHands Hub Watchdog"
$HEALTH_URL = "http://127.0.0.1:9000/healthz"

# Shared helpers (ONE health definition: 200 AND ok:true; listener pids; log
# rotation) - dot-sourced so this script can never drift from the watchdog and
# launcher copies again.
. (Join-Path $ROOT "redhands_common.ps1")

# Default to Install when no verb is supplied.
if (-not ($Install -or $Uninstall -or $Status)) { $Install = $true }

function Test-Admin {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Re-launch the whole script elevated when needed (registration targets SYSTEM,
# which requires admin). Preserves the verb the caller asked for.
function Invoke-SelfElevate {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-NoElevate')
    if ($Uninstall) { $argList += '-Uninstall' }
    elseif ($Status) { $argList += '-Status' }
    else { $argList += '-Install'; $argList += @('-WatchdogIntervalMinutes', $WatchdogIntervalMinutes) }
    Write-Host "Elevating (UAC) to register SYSTEM scheduled tasks..."
    $p = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $p.ExitCode
}

if (-not (Test-Admin) -and -not $NoElevate) { Invoke-SelfElevate }

# --- desktop shortcut --------------------------------------------------------
function Create-DesktopShortcut {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop $SHORTCUT_NAME
    $ws = New-Object -ComObject WScript.Shell
    $shortcut = $ws.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LAUNCHER`""
    $shortcut.WorkingDirectory = $ROOT
    $shortcut.WindowStyle = 7  # minimized: no console flash on manual double-click
    $shortcut.Description = "Launch the RedHands interception hub (uvicorn :9000)"
    $shortcut.IconLocation = "$PSHOME\powershell.exe,0"
    $shortcut.Save()
    Write-Host ("  [ok] desktop shortcut -> '{0}'" -f $shortcutPath)
}

function Create-ControlRoomShortcut {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop $CONTROL_ROOM_NAME
    $ws = New-Object -ComObject WScript.Shell
    $shortcut = $ws.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$CONTROL_ROOM_OPENER`""
    $shortcut.WorkingDirectory = $ROOT
    $shortcut.WindowStyle = 7  # minimized: only visible while the hub boots
    $shortcut.Description = "Open the Model Constellation Control Room (launches the hub if needed)"
    $shortcut.IconLocation = "$PSHOME\powershell.exe,0"
    $shortcut.Save()
    Write-Host ("  [ok] control room shortcut -> '{0}'" -f $shortcutPath)
}

function Remove-DesktopShortcut {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop $SHORTCUT_NAME
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
        Write-Host ("  [ok] removed desktop shortcut '{0}'" -f $shortcutPath)
    } else {
        Write-Host ("  [--] desktop shortcut '{0}' not present" -f $shortcutPath)
    }
    $crPath = Join-Path $desktop $CONTROL_ROOM_NAME
    if (Test-Path -LiteralPath $crPath) {
        Remove-Item -LiteralPath $crPath -Force -ErrorAction SilentlyContinue
        Write-Host ("  [ok] removed control room shortcut '{0}'" -f $crPath)
    }
}

# --- shared task shape -------------------------------------------------------
# RunLevel Highest + SYSTEM: starts with no user logged in and is not throttled.
# ExecutionTimeLimit Zero == unlimited, so a long-running hub is never guillotined.
# RestartOnFailure retries the action when it exits non-zero.
function New-FrostPrincipal {
    New-ScheduledTaskPrincipal -UserId "S-1-5-18" -LogonType ServiceAccount -RunLevel Highest
}

function New-FrostSettings([switch]$RetryOnFailure) {
    $params = @{
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        StartWhenAvailable         = $true
        DontStopOnIdleEnd          = $true
        MultipleInstances          = 'IgnoreNew'
        ExecutionTimeLimit         = [TimeSpan]::Zero
    }
    # RetryOnFailure is for the HUB task (a failed launch should be retried).
    # The WATCHDOG task must NOT get it: its own 1-minute repetition is the
    # retry, and a second, action-level retry would just double the load.
    # RestartCount is BOUNDED at 10: the old 99999 overflowed Task Scheduler's
    # 32-bit restart-count field and wrapped to an unpredictable value (some
    # builds clamp, some wrap) - 10 fast retries + the watchdog's own
    # every-minute-forever repetition is the real supervisor anyway.
    if ($RetryOnFailure) {
        $params.RestartCount = 10
        $params.RestartInterval = (New-TimeSpan -Minutes 1)
    }
    New-ScheduledTaskSettingsSet @params
}

function New-FrostAction([string]$script, [string[]]$extraArgs) {
    # -WindowStyle Hidden keeps the boot/logon launch invisible (no console
    # flash). The uvicorn child is already launched hidden inside
    # launch_redhands_hub.ps1; this hides the parent powershell.exe too.
    $argv = @('-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', "`"$script`"") + $extraArgs
    # -WorkingDirectory takes a BARE path: NO embedded quotes. Task Scheduler
    # stores the string verbatim, so the previous "`"$ROOT`"" made every task
    # start die with 0x8007010B ERROR_DIRECTORY (LastTaskResult 2147942667 -
    # "directory does not exist"; it did exist, the quotes did not). The -File
    # argument KEEPS its quotes because it is a command-line token, which
    # quoting rules apply to - a path property is not a command line.
    New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ($argv -join ' ') -WorkingDirectory $ROOT
}

# --- verbs -------------------------------------------------------------------
function Invoke-Install {
    foreach ($required in @($LAUNCHER, $WATCHDOG)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "missing required script: $required" }
    }

    Write-Host "Registering auto-launch + auto-recovery tasks (SYSTEM, on-battery allowed)..."

    # 1) Hub: boot + logon.
    $hubTriggers = @(
        (New-ScheduledTaskTrigger -AtStartup),
        (New-ScheduledTaskTrigger -AtLogOn)
    )
    $hubAction = New-FrostAction $LAUNCHER @()
    Register-ScheduledTask -TaskName $HUB_TASK -Action $hubAction `
        -Trigger $hubTriggers -Settings (New-FrostSettings -RetryOnFailure) -Principal (New-FrostPrincipal) `
        -Description "Auto-launch the RedHands interception hub (uvicorn :9000) at boot/logon." `
        -Force | Out-Null
    Write-Host ("  [ok] '{0}' -> launch_redhands_hub.ps1 (boot + logon)" -f $HUB_TASK)

    # 2) Watchdog: boot + logon + every N minutes indefinitely.
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $WatchdogIntervalMinutes) `
        -RepetitionDuration ([TimeSpan]::FromDays(3650))
    $wdTriggers = @(
        (New-ScheduledTaskTrigger -AtStartup),
        (New-ScheduledTaskTrigger -AtLogOn),
        $repeat
    )
    $wdAction = New-FrostAction $WATCHDOG @('-Once')
    Register-ScheduledTask -TaskName $WD_TASK -Action $wdAction `
        -Trigger $wdTriggers -Settings (New-FrostSettings) -Principal (New-FrostPrincipal) `
        -Description "Auto-recover the RedHands hub: health-probe every $WatchdogIntervalMinutes min and relaunch on failure." `
        -Force | Out-Null
    Write-Host ("  [ok] '{0}' -> watchdog_redhands_hub.ps1 -Once (boot + logon + every {1} min)" -f $WD_TASK, $WatchdogIntervalMinutes)

    # Start both now so we do not wait for the next boot to be protected.
    # Guarded: a Start-ScheduledTask hiccup (task engine busy, transient
    # COM failure) must not abort the install - the triggers fire soon anyway.
    foreach ($name in @($HUB_TASK, $WD_TASK)) {
        try {
            Start-ScheduledTask -TaskName $name -ErrorAction Stop
            Write-Host ("  [ok] started '{0}' now" -f $name)
        } catch {
            Write-Warning ("could not start '{0}' now ({1}); its boot/logon/repeat triggers still fire" -f $name, $_.Exception.Message)
        }
    }

    # 3) Desktop shortcuts for manual launch + the Control Room UI.
    Create-DesktopShortcut
    Create-ControlRoomShortcut

    Write-Host "  [ok] both tasks started; hub will be up within the next watchdog pass."
    Invoke-Status
}

function Invoke-Uninstall {
    Remove-DesktopShortcut
    foreach ($name in @($HUB_TASK, $WD_TASK)) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
            Write-Host ("  [ok] removed '{0}'" -f $name)
        } catch {
            Write-Host ("  [--] '{0}' not present" -f $name)
        }
    }
    Write-Host "Auto-launch/auto-recovery removed. The hub keeps running until it next stops."
}

function Invoke-Status {
    Write-Host "`n== RedHands autostart status =="
    foreach ($name in @($HUB_TASK, $WD_TASK)) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { Write-Host ("  {0,-20} MISSING" -f $name); continue }
        $info = Get-ScheduledTaskInfo -TaskName $name
        $battery = "{0}/{1}" -f (-not $task.Settings.DisallowStartIfOnBatteries), (-not $task.Settings.StopIfGoingOnBatteries)
        Write-Host ("  {0,-20} State={1,-8} Last={2} Result={3} Next={4} StartOnBat/KeepOnBat={5}" -f `
            $name, $task.State, $info.LastRunTime, $info.LastTaskResult, $info.NextRunTime, $battery)
    }
    $pids = Get-HubListenerPids
    $healthy = Test-HubHealth 6 $HEALTH_URL
    Write-Host ("  hub :9000            healthy={0} pid=[{1}]" -f $healthy, ($pids -join ','))
    Write-Host ""
}

if ($Uninstall) { Invoke-Uninstall; exit 0 }
if ($Status) { Invoke-Status; exit 0 }
if ($Shortcut) { Create-DesktopShortcut; Create-ControlRoomShortcut; exit 0 }
Invoke-Install
exit 0
