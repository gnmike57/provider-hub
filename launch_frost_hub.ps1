# launch_frost_hub.ps1 - boots the constellation interception hub (uvicorn)
# detached. The filename is the legacy entrypoint name and is kept so the
# scheduled task and watchdog keep working; the system it boots is the
# constellation (TheHive + Abliteration), CyberFrost retired 2026-10-21.
#
# Idempotent by design: the "Hub" scheduled task fires this at boot AND the
# watchdog (watchdog_hub.ps1) fires it on a health failure. Running it when
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
    [switch]$Quiet,
    # 2026-10-21 (hundred-push W0): print the launch plan (secret VALUES never
    # printed), run the secret preflight, and exit 0 without touching the hub.
    # Safe probe for scheduled-task / watchdog debugging.
    [switch]$DryRun
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

function Write-Note([string]$m) {
    # Launcher log file FIRST (guarded), console SECOND (guarded): the file is
    # the persistent evidence trail for boot failures - what the old console-only
    # notes lost whenever the scheduled task ran the launcher hidden; the
    # console is a convenience for interactive runs. Neither may break the launch.
    # 2026-10-22 FIX: moved ABOVE Resolve-Secret / the preflight. It used to sit
    # below Find-Python, so a missing REQUIRED secret under the SYSTEM scheduled
    # task called Write-Note before it was defined -> CommandNotFoundException ->
    # exit 1 with zero notes (the watchdog then retried forever; the intended
    # "PREFLIGHT FAIL ... exit 3" never surfaced).
    try { Add-Content -LiteralPath $LAUNCH_LOG -Value ("{0} {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $m) -Encoding utf8 } catch { }
    # [Console]::Out (not Write-Output): helper functions must return clean values
    # to their callers, and this is called from inside Stop-HubProcesses.
    try { if (-not $Quiet) { [Console]::Out.WriteLine($m) } } catch { }
}

# --- secret resolution: NO secrets in source ---------------------------------
# 2026-10-21 (hundred-push W0): the literals that used to live in this file
# were committed (therefore burned) and now resolve from the environment only
# - process env first, then the persistent User scope (setx; seeded 2026-10-21
# with the same values so boot behavior is unchanged). A missing REQUIRED
# secret is a hard preflight failure (exit 3) so Task Scheduler / the watchdog
# surface it instead of booting a money-unsafe hub. Rotation later only
# touches User scope - this file never changes again.
# 2026-10-22 FIX: Machine scope added as the last fallback. The "Frost Hub" /
# watchdog scheduled tasks run as SYSTEM, whose User scope is NOT the
# operator's - without this, every task-context launch died in preflight.
function Resolve-Secret([string]$Name, [switch]$Required) {
    $v = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not $v) { $v = [Environment]::GetEnvironmentVariable($Name, 'User') }
    if (-not $v) { $v = [Environment]::GetEnvironmentVariable($Name, 'Machine') }
    if (-not $v -and $Required) {
        Write-Note ("PREFLIGHT FAIL: required secret {0} is not set (process, User or Machine scope). Seed once with: setx {0} '<value>' / [Environment]::SetEnvironmentVariable('{0}','<value>','Machine')" -f $Name)
        exit 3
    }
    return $v
}

# Preflight runs ALWAYS - including under -DryRun and before any hub touch.
$null = Resolve-Secret 'ENCRYPTION_KEY' -Required   # Fernet: user_keys.jsonl at rest (money safety)
$null = Resolve-Secret 'ADMIN_API_KEY'  -Required   # X-Admin-Key: /v1/admin|user|siphon surface

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
# (Write-Note now lives ABOVE Resolve-Secret - see the 2026-10-22 FIX note
# there; it must be defined before the preflight can call it.)

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

if ($DryRun) {
    # -DryRun (2026-10-21, W0): plan only. Secret preflight already ran above;
    # here we print WHAT would happen, never any secret value, and exit 0
    # before the fast-path health check so a healthy hub is not even probed.
    Write-Note ("DryRun: would resolve python (venv -> Python312 -> PATH), pin the Constellation env (PRIMARY/FALLBACK/SPECIALIST -> abliterated-model-large-v2, CONSTELLATION_ONLY=1, ESCALATION_MIDDLE=1, HACKING_MODE bundle, billing knobs), clear stale :{0} listeners, and launch uvicorn proxy_gateway:app on port {0}" -f $PORT)
    Write-Note "DryRun: secrets resolved from env/User/Machine scope (ABLITERATION_API_KEY, ABLITERATION_ADMIN_KEY, HIVE_SECRET_KEY, ENCRYPTION_KEY, ADMIN_API_KEY) - values are never printed"
    Write-Note "DryRun: no process started, no hub touched"
    exit 0
}

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

    # --- Constellation environment (single source for the boot task) --------
    # CYBER-FROST is RETIRED (2026-10-21): the hub is the constellation - the
    # GLM/DeepSeek Hive brains up front, the uncensored Abliteration LARGE V2
    # brain as the terminal/divert slot. The old Frost worker pins are gone;
    # FALLBACK_* (the divert slot) now points at the V2 terminal like
    # SPECIALIST_* so a legacy FALLBACK_* reader still lands on the terminal.
    # Abliteration keys come from Windows user-scope env (installed 2026-10-21):
    # process env wins, then persistent User scope. No secrets in source.
    #   ABLITERATION_API_KEY   = ak_... chat/inference key
    #   ABLITERATION_ADMIN_KEY  = sk_... admin key (the ONLY admin key alive)
    $ablAk = $env:ABLITERATION_API_KEY
    if (-not $ablAk) { $ablAk = [Environment]::GetEnvironmentVariable('ABLITERATION_API_KEY', 'User') }
    if (-not $ablAk) { $ablAk = [Environment]::GetEnvironmentVariable('ABLITERATION_API_KEY', 'Machine') }
    $ablSk = $env:ABLITERATION_ADMIN_KEY
    if (-not $ablSk) { $ablSk = [Environment]::GetEnvironmentVariable('ABLITERATION_ADMIN_KEY', 'User') }
    if (-not $ablSk) { $ablSk = [Environment]::GetEnvironmentVariable('ABLITERATION_ADMIN_KEY', 'Machine') }
    if (-not $ablAk) { Write-Warning "ABLITERATION_API_KEY not set (process or User scope) - Abliteration calls will fail" }
    if (-not $ablSk) { Write-Warning "ABLITERATION_ADMIN_KEY not set (process or User scope) - SIPHON card charging will fail" }
    $env:PRIMARY_API_URL   = "https://api.abliteration.ai/v1/chat/completions"
    $env:PRIMARY_API_KEY    = $ablAk  # Abliteration chat key (explicit; wins over HIVE_SECRET_KEY)
    $env:PRIMARY_MODEL     = "abliterated-model-large-v2"                # default primary id
    $hiveKey = Resolve-Secret 'HIVE_SECRET_KEY'  # optional legacy rollback; live rotation is account_pool.json
    if ($hiveKey) { $env:HIVE_SECRET_KEY = $hiveKey } else { Write-Note "HIVE_SECRET_KEY not set in env - legacy Hive rollback path stays disabled (account_pool is the live mechanism)" }
    $env:FALLBACK_API_URL  = "https://api.abliteration.ai/v1/chat/completions"  # constellation TERMINAL (CyberFrost retired)
    $env:FALLBACK_API_KEY  = $ablAk
    $env:FALLBACK_MODEL    = "abliterated-model-large-v2"
    $env:SPECIALIST_API_URL = "https://api.abliteration.ai/v1/chat/completions"
    $env:SPECIALIST_API_KEY = $ablAk # Abliteration direct (NanoGPT hop dropped 2026-10-20)
    $env:SPECIALIST_MODEL   = "abliterated-model-large-v2"
    $env:ABLITERATION_API_KEY = $ablAk  # Abliteration.ai (hub matrix ablit.ai provider; SIPHON brain chat key)
    $env:ABLITERATION_ADMIN_KEY = $ablSk  # Abliteration.ai admin (org balance + SIPHON card charging)
    # Operator directive 2026-10-21: the hub offers ONLY the constellation
    # chains (see providers.CONSTELLATION_CHAINS - four as of T5.6).
    $env:CONSTELLATION_ONLY = "1"
    # ESCALATION LADDER (2026-10-21): the chain names are the contract
    # (DEEPMAX>GLM>ABLITV2L = DeepSeek-max helm -> GLM no-reasoning middle ->
    # Abliterated V2 Large terminal) - chains ALWAYS climb it. This knob puts
    # NON-chain routes on the same cheap-first ladder: a confirmed refusal
    # diverts to the OTHER Hive flash before the uncensored terminal.
    $env:ESCALATION_MIDDLE  = "1"
    # Money safety (W2): billing refuses plaintext API-key writes without a
    # Fernet ENCRYPTION_KEY, and the money/card endpoints (/v1/user/*,
    # /v1/siphon/*, /v1/admin/*) require the admin key below via X-Admin-Key.
    # REQUIRED secrets (preflight above guarantees presence): Fernet key for
    # user_keys.jsonl at rest; X-Admin-Key for the money/card endpoints.
    $env:ENCRYPTION_KEY     = Resolve-Secret 'ENCRYPTION_KEY' -Required
    $env:ADMIN_API_KEY      = Resolve-Secret 'ADMIN_API_KEY' -Required
    $env:AUDIT_LOG          = "$LOG_DIR\boot_audit.jsonl"
    $env:KEEPALIVE_URL      = "https://api.abliteration.ai/v1/models"  # keep the constellation TERMINAL warm (CyberFrost retired)
    $env:MAX_THINK_MIN_TOKENS = "32768"
    $env:NO_GO_ENABLED        = "1"
    $env:HEDGE_MAX_TOKENS     = "8192"    # raised for V2-large hedge capacity (was 4000)
    $env:SPECIALIST_MAX_TOKENS = "16384"  # V2-large divert budget (was 4096 NanoGPT reserve)
    $env:MAX_CONCURRENT_STREAMS = "64"    # DoS guard on open streams (0 = unlimited)
    $env:COMMIT_TOKENS        = "10"
$env:SKILL_MEMORY="1"
    # Phase 3: /v1/computer (Agent TARS runner, admin-authed).
    $env:COMPUTER_USE_ENABLED="1"
    $env:COMPUTER_TASK_TIMEOUT="120"
    # T5.4 HACKING_MODE bundle (closes #101): one switch arms the full
    # authorized-red-team posture - frame + uncensored middle + escalation
    # ladder + skill memory + the completion contract.
    if ($env:HACKING_MODE -eq "1") {
        $env:AUTHORIZED_FRAME="1"
        $env:UNCENSORED_MIDDLE="1"
        $env:ESCALATION_MIDDLE="1"
        $env:SKILL_MEMORY="1"
        $env:COMPLETION_CONTRACT="1"
    }
    # The /v1/computer runner needs node; the watchdog/task context does
    # NOT inherit the interactive user PATH, so the node dir is pinned.
    $env:Path = "$env:Path;C:\Users\lnxzf\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.19.0-win-x64"
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
