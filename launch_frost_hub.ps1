# launch_frost_hub.ps1 - boots the Frost interception hub (uvicorn) detached.
# Intended for: manual run AND as the action of a "Frost Hub" scheduled task
# triggered at system startup so the system auto-launches on boot.
#
# Env is pinned explicitly here so the task is self-contained and does not rely
# on the interactive user's environment. Secrets mirror gateway_registry.json /
# ufo.env (never committed to a public remote).
$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\lnxzf\Desktop\projects\provider-hub"
$LOG_DIR = "$ROOT\evals\results"
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# --- Frost system environment (single source for the boot task) -------------
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
$env:ABLITERATION_API_KEY = "REDACTED_ABLIT_KEY_OLD"  # Abliteration.ai (hub matrix ablit.ai provider)
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

Set-Location $ROOT

# Stop any previously launched hub on :9000 so a boot re-run is idempotent.
$old = Get-NetTCPConnection -State Listen -LocalPort 9000 -ErrorAction SilentlyContinue
if ($old) {
    try { Stop-Process -Id $old.OwningProcess -Force -ErrorAction Stop } catch {}
    Start-Sleep -Seconds 2
}

# Launch uvicorn detached (hidden window, survives the caller exiting).
$out = "$LOG_DIR\frost_hub_boot.out.log"
$err = "$LOG_DIR\frost_hub_boot.err.log"
$py  = "C:\Users\lnxzf\AppData\Local\Programs\Python\Python312\python.exe"

$proc = Start-Process -FilePath $py `
    -ArgumentList "-m","uvicorn","proxy_gateway:app","--host","0.0.0.0","--port","9000","--log-level","info" `
    -WorkingDirectory $ROOT `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru

Write-Output ("Frost hub pid={0} listening on http://0.0.0.0:9000" -f $proc.Id)
Write-Output ("  out: $out")
Write-Output ("  err: $err")
