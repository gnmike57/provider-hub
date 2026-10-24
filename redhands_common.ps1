# redhands_common.ps1 - shared helpers for the hub ops scripts.
#
# ONE health definition, ONE listener-pid lookup, ONE log rotator (plus the
# process-identity helper they share). Before this file existed,
# install_redhands_autostart.ps1, watchdog_redhands_hub.ps1, launch_redhands_hub.ps1
# and open_control_room.ps1 each carried their own drifting copy: one required
# ok:true, two only required HTTP 200, three different rotation caps - exactly
# the split-brain that lets a wedged-but-listening hub look healthy to one
# script and dead to another.
#
# Dot-source it (no side effects of its own):
#   . (Join-Path $ROOT "redhands_common.ps1")

# THE health definition for the whole Frost toolchain: the hub answers
# /healthz with HTTP 200 AND body ok:true. HTTP 200 alone only proves a
# process is listening; ok:true additionally proves the hub itself considers
# its wiring sound. Every script and the dashboard must agree on this single
# definition - never fork it again.
function Test-HubHealth {
    [CmdletBinding()]
    param(
        [int]$TimeoutSec = 8,
        [string]$Url = "http://127.0.0.1:9000/healthz"
    )
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec
        if ($r.StatusCode -ne 200) { return $false }
        $body = $null
        try { $body = $r.Content | ConvertFrom-Json } catch { return $false }
        return ($body.ok -eq $true)
    } catch {
        return $false
    }
}

# Listener PIDs on the hub port, so a stale/hung instance can be found,
# attributed or replaced by any script without re-deriving it.
function Get-HubListenerPids {
    [CmdletBinding()]
    param([int]$Port = 9000)
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    return @($conns | Where-Object { $_.OwningProcess -and $_.OwningProcess -ne 0 } |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

# Command line of a process, used to make sure scripts only ever kill
# processes that really are the RedHands hub - never an innocent neighbour
# that happens to hold the port.
function Get-ProcIdentity {
    [CmdletBinding()]
    param([int]$ProcId)
    try {
        return (Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue).CommandLine
    } catch { return $null }
}

# Unbounded logs eventually fill the disk, which is itself an outage. Keep the
# previous generation as .1 so post-mortem evidence survives one rotation.
# Never throws: rotation is best-effort hygiene, never a launch gate (a log
# held open by a live process may refuse the move; that is fine, next pass
# rotates it once the holder is gone).
function Rotate-Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [long]$MaxBytes = 10MB
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        if ((Get-Item -LiteralPath $Path).Length -ge $MaxBytes) {
            $prev = "$Path.1"
            if (Test-Path -LiteralPath $prev) { Remove-Item -LiteralPath $prev -Force -ErrorAction SilentlyContinue }
            Move-Item -LiteralPath $Path -Destination $prev -Force
        }
    } catch { }
}
