# gx10_sync.ps1 - instant local <-> GX10 (DGX Spark) mirror for provider-hub (2026-10-21).
#
# OPERATOR RULE: every change lands on the local copy AND the Spark copy
# together. This script is that rule, mechanised:
#   - pass file names  -> push exactly those files now;
#   - pass -All        -> push every tracked code/ops file in the project;
#   - pass -Watch      -> stay resident and mirror each save within ~1s
#                         (run this during edit sessions);
#   - -Verify          -> on-box compile check of every .py mirror
#                         (import-safe: py_compile, no app boot);
#   - -Restart         -> bounce the hub via systemd (hub/deep/glm units).
#
# Prereqs (one-time): ssh/scp reach the box (Tailscale alias "gx10"; the box
# is DGX OS / Linux with plain bash - NO PowerShell), and the remote path
# below matches the on-box checkout (audited 2026-10-21):
#   /srv/apps/ufo-galaxy/provider-hub   (== /home/flak3dd/ufo-galaxy/... via
#   symlink; served by systemd units hub/deep/glm on ports 9310/9311/9312)
#   ssh-keygen + ssh-copy-id equivalent, or an ssh config alias "gx10".
#   .\gx10_sync.ps1 -Host_ gx10 -All -Verify
#
# Examples:
#   .\gx10_sync.ps1 proxy_gateway.py providers.py          # mirror 2 files
#   .\gx10_sync.ps1 -Watch                                  # edit-session mode
#   .\gx10_sync.ps1 -All -Verify -Restart                   # full push + bounce
[CmdletBinding()]
param(
    # Files/dirs relative to the project root (positional).
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Files,
    # ssh destination or config alias.
    [string]$Host_ = "gx10",
    # The GX10 checkout root.
    [string]$Remote = "/srv/apps/ufo-galaxy/provider-hub",
    # Mirror every tracked code/ops file in the project.
    [switch]$All,
    # On-box compile check of every mirrored .py after the push.
    [switch]$Verify,
    # Bounce the hub on the box afterwards (systemd: hub/deep/glm units).
    [switch]$Restart,
    # Stay resident and mirror saves within ~1 second.
    [switch]$Watch
)

$ErrorActionPreference = "Stop"
$ROOT = "C:\Users\lnxzf\Desktop\projects\provider-hub"
$SSH  = $Host_

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Error "ssh not found on PATH - install OpenSSH client or wire an alias for $Host_"
}

function Write-Note([string]$m) { Write-Host "[gx10-sync] $m" }

function Convert-Rel([string]$p) {
    $full = if ([System.IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $ROOT $p }
    $rel = [System.IO.Path]::GetFullPath($full).Substring($ROOT.Length).TrimStart('\', '/')
    return ($rel -replace '\\', '/')
}

$PUSH_PATTERNS = @("*.py", "*.ps1", "*.sh", "*.md", "*.json", "*.yaml", "*.yml")
$EXCL_DIRS = @("\.git\", "\__pycache__\", "\.loki\", "\.mypy_cache\",
               "\.pytest_cache\", "\.ruff_cache\", "\.staging\",
               "\.tars-setup\", "\.tars\", "\node_modules\",
               "\.idea\", "\evals\results\", "\nanogpt\", "\tars\")
# never push live-secret state files (the box serves from its own registry;
# the credential pools are local vaults and must not leave this machine)
$EXCL_FILES = @("gateway_registry.json", "account_pool.json",
                "abliteration_pool.json", "siphon_state.json",
                "gateway_registry.json.tmp", "account_pool.json.tmp",
                "abliteration_pool.json.tmp", "siphon_state.json.tmp")

function Get-DefaultSet {
    Get-ChildItem -Path $ROOT -Recurse -File -Include $PUSH_PATTERNS |
        Where-Object {
            $f = $_.FullName
            # "*$_*" - the element already ends in "\", so the trailing *
            # covers the file part (a bare "*$_" never matched anything
            # INSIDE the excluded dirs - every tree was being pushed).
            -not ($EXCL_DIRS | Where-Object { $f -like "*$_*" }) -and
            -not ($EXCL_FILES -contains $_.Name)
        } | ForEach-Object { Convert-Rel $_.FullName }
}

function Push-Files([string[]]$rels) {
    if (-not $rels) { Write-Note "nothing to push"; return }
    # batch transfer: local tar -> scp -> on-box untar. (No tar streams through
    # the PowerShell pipe: PS re-encodes native stdout and corrupts binaries;
    # per-file scp is too slow for -All's ~50 files.)
    $existing = @($rels | Where-Object {
        Test-Path -LiteralPath (Join-Path $ROOT ($_ -replace '/', '\'))
    })
    foreach ($m in @($rels | Where-Object { $existing -notcontains $_ })) {
        Write-Warning "missing locally, skipped: $m"
    }
    if ($existing.Count -eq 0) { Write-Note "nothing to push (all missing)"; return }
    $tmp = Join-Path $env:TEMP "gx10-push.tar"
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
    tar -cf $tmp -C $ROOT $existing
    if ($LASTEXITCODE -ne 0) { Write-Error "local tar failed (exit $LASTEXITCODE)"; return }
    scp -q $tmp "${SSH}:/tmp/gx10-push.tar"
    if ($LASTEXITCODE -ne 0) { Write-Error "scp of batch failed (exit $LASTEXITCODE)"; return }
    ssh $SSH "tar -xf /tmp/gx10-push.tar -C '$Remote' && rm /tmp/gx10-push.tar"
    if ($LASTEXITCODE -ne 0) { Write-Error "on-box untar failed (exit $LASTEXITCODE)"; return }
    Remove-Item $tmp -Force
    Write-Note ("pushed {0} file(s) -> {1}:{2} (tar batch)" -f $existing.Count, $SSH, $Remote)
}

function Invoke-Verify {
    Write-Note "on-box compile check..."
    $script = ("cd '{0}' && find . -name '*.py' -not -path '*__pycache__*' " +
               "-print0 | xargs -0 -n 32 python3 -m py_compile " +
               "&& echo 'GX10 COMPILE OK' || echo 'GX10 COMPILE FAIL'") -f $Remote
    ssh $SSH "bash -lc `"$script`""
}

function Invoke-Restart {
    # The box runs the checkout under systemd: hub.service (9310),
    # deep.service (9311), glm.service (9312) - all WorkingDirectory'd at
    # $Remote (== /home/flak3dd/ufo-galaxy/provider-hub, same dir via symlink).
    # NEVER pkill the uvicorns; systemd owns them and will resurrect/dupe.
    Write-Note "restarting systemd units: hub deep glm..."
    ssh $SSH "sudo -n systemctl restart hub.service deep.service glm.service && sleep 3 && systemctl is-active hub.service deep.service glm.service"
}

# --- main ---------------------------------------------------------------------
if ($All) {
    Push-Files (Get-DefaultSet)
}
elseif ($Files) {
    Push-Files ($Files | ForEach-Object { Convert-Rel $_ })
}
elseif (-not ($Watch -or $Verify -or $Restart)) {
    Write-Host "usage: gx10_sync.ps1 <files...> | -All | -Watch  [-Verify] [-Restart]"
    exit 1
}

if ($Verify)  { Invoke-Verify }
if ($Restart) { Invoke-Restart }

if ($Watch) {
    Write-Note ("watching {0} -> {1}:{2} (Ctrl+C to stop)" -f $ROOT, $SSH, $Remote)
    $watcher = New-Object System.IO.FileSystemWatcher $ROOT, "*.*" -Property @{
        IncludeSubdirectories = $true; EnableRaisingEvents = $true
    }
    $pending = [System.Collections.Generic.HashSet[string]]::new()
    $timer = New-Object System.Timers.Timer 800
    $timer.AutoReset = $false
    $onFlush = {
        $timer.Stop()
        foreach ($rel in @($pending)) {
            [void]$pending.Remove($rel)
            Push-Files @($rel)
        }
        $timer.Start()
    }
    Register-ObjectEvent $timer Elapsed -Action $onFlush | Out-Null
    $onEvent = {
        $e = $Event.SourceEventArgs
        $full = $e.FullPath
        if (($full -notmatch '__pycache__|\.git\\|\.loki|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.staging|\.tars|\.idea|evals\\results|nanogpt\\|node_modules') -and
            ($EXCL_FILES -notcontains (Split-Path $full -Leaf))) {
            if ($full -match '\.(py|ps1|sh|md|json|ya?ml)$') {
                $rel = $full.Substring($ROOT.Length).TrimStart('\', '/') -replace '\\', '/'
                [void]$pending.Add($rel)
                $timer.Stop(); $timer.Start()
            }
        }
    }
    foreach ($evt in @("Changed", "Created", "Renamed")) {
        Register-ObjectEvent $watcher $evt -Action $onEvent | Out-Null
    }
    while ($true) { Start-Sleep -Milliseconds 250 }
}
Write-Note "done."
