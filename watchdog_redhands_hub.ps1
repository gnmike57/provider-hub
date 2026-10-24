# watchdog_redhands_hub.ps1 - keeps the RedHands hub alive (auto-recovery supervisor).
#
# THE POINT: "RedHands Hub" only fires launch_redhands_hub.ps1 once, at boot.
# If uvicorn ever dies (crash, wedged event loop, OOM, socket reset - all seen in
# redhands_hub_boot.err.log) nothing brings it back. This watchdog is that missing
# layer: it probes /healthz and, on failure, replaces the process.
#
# Modes:
#   -Once   single health check + remediation, then exit. This is what the
#           "RedHands Hub Watchdog" scheduled task runs every minute; TASK
#           SCHEDULER is the supervisor, so recovery does not depend on a
#           PowerShell process staying alive.
#   -Loop   resident loop (use when running it by hand or under a service
#           manager); sleeps -IntervalSeconds between passes.
#
# Bulletproofing details:
#   * Health is judged by GET /healthz -> 200 {"ok": true}, not by "is a PID
#     alive" - a hung process must be replaced too.
#   * -FailThreshold consecutive misses are required before acting, so a burst
#     of load-time timeouts does not cause an unnecessary restart.
#   * Restart budget (-MaxRestartsPerHour): a genuinely broken hub (bad key,
#     bad config) would otherwise crash-loop forever and burn CPU. Past budget
#     the watchdog backs off and only records the outage.
#   * Single-instance mutex: overlapping task runs never double-launch.
#   * Log rotation keeps the watchdog log from filling the disk.
#
# Exit codes:
#   0  hub healthy (no action needed) or no action permitted under cooldown
#   1  hub was unhealthy AND a recovery launch was attempted
[CmdletBinding()]
param(
    # Single pass (default behaviour when neither -Once nor -Loop is given).
    [switch]$Once,
    # Resident loop.
    [switch]$Loop,
    [int]$IntervalSeconds = 15,
    [int]$Port = 9000,
    # Consecutive failed probes before remediating.
    [int]$FailThreshold = 2,
    # Ceiling on restarts inside a rolling hour (crash-loop guard).
    [int]$MaxRestartsPerHour = 20,
    # Passed through to the launcher's post-launch health wait.
    [int]$LaunchWaitSeconds = 60,
    # HARD ceiling on how long a recovery launch may run before the watchdog
    # kills it. Without a bound, a launcher wedged on its mutex or health loop
    # held Global\FrostHubWatchdog forever and every later pass skipped with
    # "another watchdog pass is running" - the supervisor itself dead.
    [int]$LauncherTimeoutSec = 300,
    # Anti-thrash: after a recovery, hold off further restarts for this long so a
    # freshly-launched hub can finish coming up and two overlapping passes cannot
    # kill each other's healthy child.
    [int]$RecoveryCooldownSeconds = 120,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\lnxzf\Desktop\projects\provider-hub"
$LOG_DIR = "$ROOT\evals\results"
$LAUNCHER = "$ROOT\launch_redhands_hub.ps1"
$LOG_FILE = "$LOG_DIR\redhands_watchdog.log"
$STATE_FILE = "$LOG_DIR\redhands_watchdog_state.json"
$HEALTH_URL = "http://127.0.0.1:$Port/healthz"
$MAX_LOG_BYTES = 5MB
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# Shared helpers - ONE health definition (HTTP 200 AND ok:true), listener
# pids, log rotation - dot-sourced so watchdog/launcher/installer can never
# drift apart again.
. (Join-Path $ROOT "redhands_common.ps1")

$script:IsLoop = [bool]$Loop

function Write-Log([string]$level, [string]$message) {
    $line = ("{0} [{1}] {2}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $level, $message)
    # File FIRST, console SECOND, each independently guarded: a broken console
    # (hidden window, closed stream) must never cost us the audit line, and an
    # unwritable log dir must never take the console echo down with it.
    try { Add-Content -LiteralPath $LOG_FILE -Value $line -Encoding utf8 } catch { }
    # [Console]::Out (not Write-Output): keeps command output OUT of the pipeline
    # so helper functions still return clean values to their callers.
    try { if (-not $Quiet) { [Console]::Out.WriteLine($line) } } catch { }
}

# Test-HubHealth / Get-HubListenerPids / Get-ProcIdentity / Rotate-Log live
# in redhands_common.ps1 (dot-sourced above): ONE health definition for every
# script - HTTP 200 AND body ok:true.

# --- restart-budget state ----------------------------------------------------
# A rolling one-hour window of restart timestamps. Past the budget the hub is
# treated as unfixable-by-restart and left alone (an operator must look), which
# prevents an infinite crash loop from pegging the CPU.
function Read-Restarts() {
    if (-not (Test-Path -LiteralPath $STATE_FILE)) { return @() }
    try {
        $doc = Get-Content -LiteralPath $STATE_FILE -Raw | ConvertFrom-Json
        if ($null -eq $doc.restarts) { return @() }
        $cut = (Get-Date).AddHours(-1)
        $valid = @()
        foreach ($entry in @($doc.restarts)) {
            $when = New-Object datetime
            if (-not [datetime]::TryParse([string]$entry, [ref]$when)) {
                Write-Log "WARN" "restart state: dropping unparsable timestamp entry '$entry'"
                continue
            }
            if ($when -gt $cut) { $valid += $when.ToString("o") }
        }
        return $valid
    } catch {
        # NEVER silently swallow corruption: the old catch returned @(), which
        # quietly zeroed the crash budget and let a crash-looping hub burn CPU
        # forever with the state file unreadable the whole time. Quarantine the
        # bad file (evidence survives), log LOUDLY, re-arm from zero.
        Write-Log "ERROR" "restart state file is corrupt ($($_.Exception.Message)); quarantining it and re-arming the crash budget from zero"
        try {
            Move-Item -LiteralPath $STATE_FILE `
                -Destination ($STATE_FILE + ".bad." + (Get-Date).ToString("yyyyMMddHHmmss")) -Force
        } catch {
            Write-Log "ERROR" "could not quarantine corrupt restart state: $($_.Exception.Message)"
        }
        return @()
    }
}

function Write-Restarts($list) {
    try {
        (@{ restarts = @($list) } | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $STATE_FILE -Encoding utf8
    } catch { }
}

function Invoke-Recovery([string]$why) {
    $restarts = Read-Restarts
    Write-Log "WARN" "$why; listener pids=[$((Get-HubListenerPids -Port $Port) -join ',')]"

    if ($restarts.Count -ge $MaxRestartsPerHour) {
        Write-Log "ERROR" "restart budget exhausted ($($restarts.Count)/$MaxRestartsPerHour in the last hour); backing off, NOT restarting. Operator attention required."
        return $false
    }

    # -Force: the port may still be held by a wedged process that fails health.
    Write-Log "INFO" "recovering: launch_redhands_hub.ps1 -Force -Quiet -WaitSeconds $LaunchWaitSeconds (hard cap ${LauncherTimeoutSec}s)"
    # NO Start-Process -Wait: it has no timeout, so a launcher wedged on its
    # mutex or health loop would hold Global\FrostHubWatchdog forever. Run it
    # detached and bound the wait; kill it on expiry so the watchdog ALWAYS
    # returns and the next pass can act.
    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $LAUNCHER, "-Force", "-Quiet", "-WaitSeconds", $LaunchWaitSeconds) `
        -WindowStyle Hidden -PassThru
    $code = $null
    if ($proc.WaitForExit($LauncherTimeoutSec * 1000)) {
        $code = $proc.ExitCode
    } else {
        Write-Log "ERROR" "launcher pid=$($proc.Id) still running after ${LauncherTimeoutSec}s (wedged); killing it so the watchdog mutex is released"
        try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { }
        $code = "killed (timeout)"
    }

    $restarts = @(Read-Restarts) + (Get-Date).ToString("o")
    Write-Restarts $restarts

    # The launcher already waited, but under load the HTTP stack can still be
    # warming; poll briefly rather than declaring failure on one probe.
    $healthy = $false
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        if (Test-HubHealth 5 $HEALTH_URL) { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if ($healthy) {
        Write-Log "INFO" "recovered: hub healthy again (launcher exit=$code, restarts last hour=$($restarts.Count))"
        return $true
    }
    Write-Log "ERROR" "recovery launch did NOT restore health (launcher exit=$code); will retry after cooldown"
    return $false
}

# --- one supervisor pass -----------------------------------------------------
function Invoke-Pass {
    if (Test-HubHealth 8 $HEALTH_URL) {
        $pids = Get-HubListenerPids -Port $Port
        Write-Log "OK" "hub healthy on :$Port (pid=$($pids -join ','))"
        return 0
    }
    # Tolerate transient misses (GC pause, load spike) before touching anything.
    for ($i = 1; $i -lt $FailThreshold; $i++) {
        Start-Sleep -Seconds 3
        if (Test-HubHealth 8 $HEALTH_URL) {
            Write-Log "OK" "hub healthy on :$Port after a transient miss (attempt $($i + 1))"
            return 0
        }
    }

    # Anti-thrash: if we recovered very recently, give the fresh process time to
    # finish starting instead of killing it. This is what stops overlapping
    # watchdog passes from fighting over :9000.
    $recent = Read-Restarts
    if ($recent.Count -gt 0) {
        $last = $recent | ForEach-Object { [datetime]$_ } | Sort-Object -Descending | Select-Object -First 1
        $age = [int]((Get-Date) - $last).TotalSeconds
        if ($age -lt $RecoveryCooldownSeconds) {
            Write-Log "WARN" "hub unhealthy but last recovery was ${age}s ago (< ${RecoveryCooldownSeconds}s cooldown); holding off"
            return 1
        }
    }

    if (Invoke-Recovery "$FailThreshold consecutive /healthz failures") { return 1 }
    return 1
}

# --- single-instance guard ---------------------------------------------------
$mutex = New-Object System.Threading.Mutex($false, "Global\RedHandsHubWatchdog")
$haveLock = $false
try {
    $haveLock = $mutex.WaitOne([TimeSpan]::FromSeconds(5))
} catch [System.Threading.AbandonedMutexException] {
    $haveLock = $true
}
if (-not $haveLock) { Write-Log "INFO" "another watchdog pass is running; skipping"; exit 0 }

$exit = 0
try {
    Rotate-Log -Path $LOG_FILE -MaxBytes $MAX_LOG_BYTES
    Write-Log "INFO" "watchdog start (mode=$(if ($script:IsLoop) { 'loop' } else { 'once' }), port=$Port, budget=$MaxRestartsPerHour/h)"

    if ($script:IsLoop) {
        while ($true) {
            $exit = Invoke-Pass
            Start-Sleep -Seconds ([Math]::Max($IntervalSeconds, 5))
        }
    } else {
        $exit = Invoke-Pass
    }
} catch {
    Write-Log "ERROR" "watchdog pass raised: $($_.Exception.Message)"
    $exit = 1
} finally {
    if ($haveLock) { try { $mutex.ReleaseMutex() } catch { } }
    $mutex.Dispose()
}
exit $exit
