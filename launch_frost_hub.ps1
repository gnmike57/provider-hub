# launch_frost_hub.ps1 - boots the Frost interception hub (uvicorn) detached.
#
# Idempotent by design: the "Frost Hub" scheduled task fires this at boot AND the
# watchdog (watchdog_frost_hub.ps1) fires it on a health failure. Running it when
# the hub is ALREADY healthy is a no-op that exits 0, so a healthy hub is never
# churned by a redundant launch.
#
# Exit codes (Task Scheduler RestartOnFailure keys off these):
#   0  hub is healthy on :9000 (either it already was, or we launched it and it
#      passed /healthz within the wait window)
#   1  launch attempted and the hub did NOT become healthy -> caller should retry
#
# Env is pinned explicitly here so the task is self-contained and does not rely
# on the interactive user's environment. Secrets mirror gateway_registry.json /
# ufo.env (never committed to a public remote).
[CmdletBinding()]
param(
    # Restart even when :9000 already answers /healthz.
    [switch]$Force,
    # Seconds to wait for /healthz to report ok=true after launching.
    [int]$WaitSeconds = 60,
    # Suppress the informational success line (the watchdog logs on its own).
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\lnxzf\Desktop\projects\provider-hub"
$LOG_DIR = "$ROOT\evals\results"
$PORT = 9000
$HEALTH_URL = "http://127.0.0.1:$PORT/healthz"
$PID_FILE = "$LOG_DIR\frost_hub.pid"
$MAX_LOG_BYTES = 10MB
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

$out = "$LOG_DIR\frost_hub_boot.out.log"
$err = "$LOG_DIR\frost_hub_boot.err.log"
$LAUNCH_LOG = "$LOG_DIR\frost_hub_launch.log"

# Shared helpers - ONE health definition (HTTP 200 AND ok:true), listener
# pids, log rotation - dot-sourced so watchdog/launcher/installer can never
# drift apart again.
. (Join-Path $ROOT "frost_common.ps1")
# Keep the launcher's own audit log bounded (boot evidence, one line per note).
Rotate-Log -Path $LAUNCH_LOG -MaxBytes 2MB

# --- discover python executable --------------------------------------------
# Prefer the project venv, then the Python 3.12 install that carries the
# hub's dependencies (httpx/fastapi/uvicorn). Never hardcode a version-specific
# path as the *only* choice: the launcher survives Python upgrades by falling
# back to PATH, but it tries 3.12 first because that is where the deps live.
function Find-Python {
    # Candidate 1: project venv
    $venvPy = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPy) { return $venvPy }

    # Candidate 2: explicit Python 3.12 install path (carries httpx/fastapi)
    $py312 = "C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $py312) { return $py312 }

    # Candidate 3: any python.exe on PATH
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    throw "No python.exe found. Activate .venv or add Python to PATH."
}

# Sanity-check that the chosen python can actually run the hub (import httpx
# and fastapi). If not, try each candidate in turn rather than dying later
# inside Start-Process with a cryptic ModuleNotFoundError.
function Test-PythonRunsHub([string]$p) {
    try {
        $r = & $p -c "import httpx, fastapi; print('ok')" 2>$null
        return $r -eq "ok"
    } catch { return $false }
}

$py = Find-Python
if (-not (Test-PythonRunsHub $py)) {
    foreach ($c in @("C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe",
                     (Get-Command python.exe -ErrorAction SilentlyContinue))) {
        if ($c -and (Test-PythonRunsHub $c)) { $py = $c; break }
    }
}
if (-not (Test-PythonRunsHub $py)) {
    throw "No python.exe found that can import httpx and fastapi. Install them, or point SCOUT_PYTHON at a working interpreter."
}

# --- helpers ----------------------------------------------------------------
function Write-Note([string]$m) {
    # Launcher log file FIRST (guarded), console SECOND (guarded): the file is
    # the persistent evidence trail for boot failures - what the old console-only
    # notes lost whenever the scheduled task ran the launcher hidden; the
    # console is a convenience for interactive runs. Neither may break the launch.
    try { Add-Content -LiteralPath $LAUNCH_LOG -Value ("{0} {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $m) -Encoding utf8 } catch { }
    # [Console]::Out (not Write-Output): helper functions must return clean values
    # to their callers, and this is called from inside Stop-HubProcesses.
    try { if (-not $Quiet) { [Console]::Out.WriteLine($m) } } catch { }
}

# Test-HubHealth / Get-HubListenerPids / Get-ProcIdentity / Rotate-Log live in
# frost_common.ps1 (dot-sourced above): ONE health definition for every script
# - HTTP 200 AND body ok:true.

function Stop-HubProcesses() {
    foreach ($procId in (Get-HubListenerPids -Port $PORT)) {
        $cmd = Get-ProcIdentity $procId
        # Only kill processes that are actually the Frost hub (uvicorn running proxy_gateway).
        if ($cmd -and ($cmd -like "*uvicorn*" -or $cmd -like "*proxy_gateway*")) {
            Write-Note ("  replacing hub listener pid={0} cmd={1}" -f $procId, $cmd)
            try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch { }
        } else {
            Write-Note ("  skipping non-hub listener pid={0} cmd={1}" -f $procId, $cmd)
        }
    }
    # Give the OS time to release the socket before rebinding.
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-HubListenerPids -Port $PORT).Count -gt 0 -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
}

# --- single-instance guard ---------------------------------------------------
# The boot task, a logon task and the watchdog can race. A named mutex makes
# exactly one of them do the work; the others return immediately.
$mutex = New-Object System.Threading.Mutex($false, "Global\FrostHubLaunch")
$haveLock = $false
try {
    $haveLock = $mutex.WaitOne([TimeSpan]::FromSeconds(120))
} catch [System.Threading.AbandonedMutexException] {
    $haveLock = $true
}
if (-not $haveLock) { Write-Note "another launch is in progress; nothing to do"; exit 0 }

try {
    # --- fast path: already healthy and not forced --------------------------
    if (-not $Force) {
        if (Test-HubHealth 4 $HEALTH_URL) {
            $live = Get-HubListenerPids -Port $PORT
            # Rotation must ALSO run on the healthy fast path: the rotate calls
            # used to sit below this early exit, so a hub that stayed healthy
            # for weeks never rotated frost_hub_boot.*.log and they grew
            # unbounded - rotation was unreachable exactly when the hub was at
            # its busiest. (With uvicorn holding the files open the move may be
            # refused; Rotate-Log is best-effort, the next boot rotates them.)
            Rotate-Log -Path $out -MaxBytes $MAX_LOG_BYTES
            Rotate-Log -Path $err -MaxBytes $MAX_LOG_BYTES
            Write-Note ("Frost hub already healthy on :{0} (pid={1}); no action" -f $PORT, ($live -join ","))
            exit 0
        }
    }

    # --- Frost system environment (single source for the boot task) ---------
    $env:PRIMARY_API_URL   = "https://api-cdn.thehive.ai/api/v3/chat/completions"
    $env:HIVE_SECRET_KEY   = "REDACTED_HIVE_KEY"        # Hive self-hosted LLMs primary
    $env:PRIMARY_MODEL     = "zai-org/glm-5.3-flash"                # default primary id
    $env:FALLBACK_API_URL  = "http://100.67.13.78:4000/v1/chat/completions"  # gx10 hub (worker/cyberfrost)
    $env:FALLBACK_API_KEY  = "none"
    $env:FALLBACK_MODEL    = "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"
    $env:FROST_WORKER_API_URL = "http://100.67.13.78:4000/v1/chat/completions"  # gx10 hub for the cyberfrost names (NOT the specialist override)
    $env:FROST_WORKER_API_KEY = "none"
    $env:SPECIALIST_API_URL = "https://nano-gpt.com/api/v1/chat/completions"
    $env:SPECIALIST_API_KEY = "sk-nano-5c33cd2e-dfb3-46cd-a068-46bcaee19ef2" # == NANOGPT_API_KEY
    $env:SPECIALIST_MODEL   = "abliteration-ai/abliterated-model-large-v2"
    $env:NANOGPT_API_KEY    = "sk-nano-5c33cd2e-dfb3-46cd-a068-46bcaee19ef2"
    $env:ABLITERATION_API_KEY = "REDACTED_ABLIT_KEY"  # Abliteration.ai (hub matrix ablit.ai provider; SIPHON brain chat key)
    $env:ABLITERATION_ADMIN_KEY = "REDACTED_ADMIN_KEY"  # Abliteration.ai admin (org balance + SIPHON card charging)
    $env:AUDIT_LOG          = "$LOG_DIR\boot_audit.jsonl"
    $env:KEEPALIVE_URL      = "http://100.67.13.78:4000/v1/models"
    $env:MAX_THINK_MIN_TOKENS = "32768"
    $env:NO_GO_ENABLED        = "1"
    $env:HEDGE_MAX_TOKENS     = "4000"
    $env:SPECIALIST_MAX_TOKENS = "4096"   # divert budget: NanoGPT reserved 64k tokens otherwise
    $env:MAX_CONCURRENT_STREAMS = "64"    # DoS guard on open streams (0 = unlimited)
    $env:COMMIT_TOKENS        = "10"
    $env:PYTHONUNBUFFERED     = "1"
    $env:PYTHONIOENCODING     = "utf-8"

    # --- clear anything stale on :9000 (idempotent boot re-run) -------------
    if ((Get-HubListenerPids).Count -gt 0) { Stop-HubProcesses }

    Rotate-Log -Path $out -MaxBytes $MAX_LOG_BYTES
    Rotate-Log -Path $err -MaxBytes $MAX_LOG_BYTES

    Set-Location $ROOT

    # Bind loopback by default; set $env:HOST=0.0.0.0 to expose on LAN/WAN.
    $bindHost = $env:HOST
    if (-not $bindHost) { $bindHost = "127.0.0.1" }

    # Launch uvicorn detached (hidden window, survives the caller exiting).
    if (-not (Test-Path -LiteralPath $py)) {
        Write-Note "FATAL: python executable not found at $py"
        exit 1
    }
    $proc = Start-Process -FilePath $py `
        -ArgumentList "-m","uvicorn","proxy_gateway:app","--host",$bindHost,"--port","$PORT","--log-level","info" `
        -WorkingDirectory $ROOT `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -PassThru

    Set-Content -LiteralPath $PID_FILE -Value $proc.Id -Encoding ascii -ErrorAction SilentlyContinue
    Write-Note ("Frost hub launched pid={0} on http://{1}:{2}; out={3} err={4}" -f $proc.Id, $bindHost, $PORT, $out, $err)

    # --- verify: health must come from THE pid we just launched -------------
    # Two conditions, not one: /healthz must answer ok:true AND the listener
    # on :$PORT must be the process we spawned. Verifying only the URL once
    # blessed a stray survivor answering for a launch that had already died.
    $ownershipWarned = $false
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            Write-Note ("Frost hub pid={0} exited early (code {1}); see {2}" -f $proc.Id, $proc.ExitCode, $err)
            exit 1
        }
        if (Test-HubHealth 3 $HEALTH_URL) {
            $live = Get-HubListenerPids -Port $PORT
            if (@($live) -contains $proc.Id) {
                Write-Note ("Frost hub healthy on :{0} (pid={1})" -f $PORT, $proc.Id)
                exit 0
            }
            if (-not $ownershipWarned) {
                Write-Note ("health answered on :{0} but listener pids=[{1}] do not include launched pid={2}; waiting for handover" -f $PORT, ($live -join ","), $proc.Id)
                $ownershipWarned = $true
            }
        }
        Start-Sleep -Seconds 1
    }

    Write-Note ("Frost hub pid={0} did NOT pass /healthz within {1}s (listener pids=[{2}])" -f $proc.Id, $WaitSeconds, ((Get-HubListenerPids -Port $PORT) -join ","))
    exit 1
} finally {
    if ($haveLock) { try { $mutex.ReleaseMutex() } catch { } }
    $mutex.Dispose()
}
