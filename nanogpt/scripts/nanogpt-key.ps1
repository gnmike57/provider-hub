#Requires -Version 5.1
<#
.SYNOPSIS
    Provision and maintain a normal NanoGPT inference API key in the Windows
    (HKCU) environment, driven by a NanoGPT Management API token.

.DESCRIPTION
    NanoGPT has two credential planes that must never be confused:

      * Management token  sk-nano-mgmt-<uuid>.<secret>   -> /api/management/v1
        Can list / read / create / update / revoke inference keys.
        CANNOT run models or spend balance.
      * Inference key     sk-nano-<uuid>                 -> api.nano-gpt.com
        Runs models and spends balance.
        CANNOT call the Management API.

    This script is the bridge. It reads the management token from the
    environment (NANOGPT_MGMT_API_KEY by default), makes sure a real inference
    key exists, and persists that inference key into the Windows user
    environment under NANOGPT_API_KEY (plus any extra names), so every NEW
    process -- the nanogpt MCP server, the provider-hub gateway, coding agents --
    picks it up with no manual copy/paste.

    Windows note: SetEnvironmentVariable(...,'User') writes HKCU and only
    reaches processes started AFTER the write. Restart terminals / IDE servers
    after a rotate. Already-running shells keep the stale value.

    Sources of truth:
      https://docs.nano-gpt.com/api-reference/management-api
      https://nano-gpt.com/management-openapi.json

.PARAMETER Action
    sync   (default) Ensure every target env var holds a valid inference key.
    status          Report management-plane + environment state. Changes nothing.
    rotate          Mint a brand-new inference key and persist it.
    revoke          Delete a managed inference key by -KeyId (requires -Yes).

.PARAMETER ManagementKey
    The sk-nano-mgmt-... token. If omitted it is read from -ManagementEnvVar
    (process -> user -> machine scope).

.PARAMETER ManagementEnvVar
    Env var holding the management token. Default: NANOGPT_MGMT_API_KEY.

.PARAMETER KeyName
    Name given to the inference key created by sync/rotate.
    Default: nanogpt-env.

.PARAMETER TargetEnvVars
    Env vars written with the inference key.
    Default: NANOGPT_API_KEY, NANOGPT_API_KEY_HUB.

.PARAMETER McpJson
    Path to the MCP client config whose NANOGPT_API_KEY value is aligned with
    the provisioned key. Default: <repo>\.mcp.json.

.PARAMETER ExportProviderHub
    Also set REASONER_API_KEY and SPECIALIST_API_KEY (provider-hub tier bindings).

.PARAMETER Force
    sync: mint a fresh key even when a valid one is already present.

.PARAMETER KeyId
    revoke: numeric id of the managed inference key to delete.

.PARAMETER Yes
    revoke/rotate: confirm the destructive DELETE.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 status

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 sync

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 rotate -RevokeOld

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\nanogpt-key.ps1 revoke -KeyId 245159 -Yes
#>
[CmdletBinding()]
param(
    [ValidateSet('sync', 'status', 'rotate', 'revoke')]
    [string]$Action = 'sync',

    [string]$ManagementKey = '',
    [string]$ManagementEnvVar = 'NANOGPT_MGMT_API_KEY',

    [string]$KeyName = 'nanogpt-env',

    [string[]]$TargetEnvVars = @('NANOGPT_API_KEY', 'NANOGPT_API_KEY_HUB'),

    [string]$McpJson = '',
    [switch]$SkipMcpJson,

    [switch]$ExportProviderHub,

    [switch]$Force,
    [switch]$RevokeOld,

    [string]$KeyId = '',
    [switch]$Yes,

    [int]$TimeoutSec = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# HTTPS only; PowerShell 5.1 still negotiates TLS 1.0 by default on some hosts.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$script:MgmtBase   = 'https://nano-gpt.com/api/management/v1'
$script:InferBase  = 'https://api.nano-gpt.com'
$script:MgmtKey    = ''
$script:Timeout    = $TimeoutSec
$script:ProviderHubVars = @('REASONER_API_KEY', 'SPECIALIST_API_KEY')

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ("== " + $Title) -ForegroundColor Cyan
}

function Write-Ok([string]$Message)   { Write-Host ("  [ok]   " + $Message) -ForegroundColor Green }
function Write-Info([string]$Message) { Write-Host ("  [info] " + $Message) }
function Write-Warn([string]$Message) { Write-Host ("  [warn] " + $Message) -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host ("  [fail] " + $Message) -ForegroundColor Red }

function Mask([string]$Value) {
    # Never print a full secret: show only enough to recognise the key
    # (prefix + last 4). The full inference secret is written to HKCU and
    # .mcp.json by design, but it must not appear in console output or logs.
    if ([string]::IsNullOrEmpty($Value)) { return '<empty>' }
    if ($Value.Length -le 18) { return ($Value.Substring(0, 4) + '...') }
    return ($Value.Substring(0, 14) + '...' + $Value.Substring($Value.Length - 4))
}

function Get-EffectiveEnv([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($Name, 'User')
    }
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($Name, 'Machine')
    }
    return $value
}

function Set-UserEnv([string]$Name, [string]$Value) {
    # Always refresh the current process so in-session checks are accurate.
    Set-Item -Path ('Env:' + $Name) -Value $Value
    $existing = [Environment]::GetEnvironmentVariable($Name, 'User')
    if ($existing -ceq $Value) {
        Write-Ok ($Name + ' already correct (' + (Mask $Value) + '); no HKCU write')
        return $false
    }
    # NB: SetEnvironmentVariable(User) broadcasts WM_SETTINGCHANGE and can take
    # seconds on a busy desktop, so it is only done when the value really changes.
    [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
    Write-Ok ($Name + ' <- ' + (Mask $Value) + ' (HKCU updated)')
    return $true
}

function Get-HttpErrorBody([System.Management.Automation.ErrorRecord]$Record) {
    # Invoke-RestMethod (PS 5.1) exposes the parsed body here for HTTP errors.
    if ($Record.ErrorDetails -ne $null -and -not [string]::IsNullOrWhiteSpace($Record.ErrorDetails.Message)) {
        return $Record.ErrorDetails.Message
    }
    # Non-HTTP failures (validation, network, parse) have no .Response --
    # guard with PSObject so we never throw while reporting an error.
    $response = $Record.Exception.PSObject.Properties['Response']
    if ($response -ne $null) {
        $stream = $response.Value
        if ($stream -ne $null) {
            try {
                $reader = New-Object System.IO.StreamReader($stream.GetResponseStream())
                return $reader.ReadToEnd()
            } catch { }
        }
    }
    return $Record.Exception.Message
}

function Assert-KeyFormat([string]$Value, [string]$What) {
    # Management tokens: sk-nano-mgmt-<uuid>.<secret>  (inference keys are sk-nano-<uuid>).
    # Validating shape up front fails fast on a mistyped token AND prevents the
    # two planes from ever being swapped: a plain inference key can never be
    # used where a management token is required (the API would 401 anyway, but
    # a clear local error beats an opaque remote one).
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw ($What + ' is empty.')
    }
    $value = $Value.Trim()
    if ($value -notmatch '^sk-nano-mgmt-[0-9a-fA-F-]{36}\.[A-Za-z0-9]+$') {
        throw ($What + ' is not a management token (expected "sk-nano-mgmt-<uuid>.<secret>"). ' +
               'Do NOT pass a normal inference key (sk-nano-<uuid>) here -- inference keys cannot call the Management API. ' +
               'Create a token at https://nano-gpt.com/settings#management-api-tokens')
    }
    return $value
}

function Resolve-ManagementKey {
    if (-not [string]::IsNullOrWhiteSpace($ManagementKey)) {
        return (Assert-KeyFormat -Value $ManagementKey -What 'management token')
    }
    $fromEnv = Get-EffectiveEnv $ManagementEnvVar
    if (-not [string]::IsNullOrWhiteSpace($fromEnv)) {
        return (Assert-KeyFormat -Value $fromEnv -What ($ManagementEnvVar + ' value'))
    }
    throw ("No management token. Set " + $ManagementEnvVar + " in the Windows environment, or pass -ManagementKey. Create one at https://nano-gpt.com/settings#management-api-tokens (scopes needed: api_keys:read, api_keys:write).")
}

# Inference key shape check: sk-nano-<uuid> (legacy plain-UUID keys also exist).
function Test-InferenceKeyFormat([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    $value = $Value.Trim()
    return ($value -match '^sk-nano-[0-9a-fA-F-]{36}$') -or ($value -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
}

function Invoke-Management([string]$Method, [string]$Path, $Body = $null, [hashtable]$ExtraHeaders = @{}) {
    # The management token is sent as a header only -- never in a URL -- per the
    # NanoGPT docs ("Send it in an authorization header, not a URL"). A hard
    # guard rejects any accidental http:// downgrade of the base URL.
    if (($script:MgmtBase + $Path) -notmatch '^https://') {
        throw 'refusing to send the management token over a non-HTTPS URL'
    }
    $headers = @{ Authorization = ('Bearer ' + $script:MgmtKey) }
    foreach ($key in $ExtraHeaders.Keys) { $headers[$key] = $ExtraHeaders[$key] }

    $params = @{
        Method      = $Method
        Uri         = ($script:MgmtBase + $Path)
        Headers     = $headers
        TimeoutSec  = $script:Timeout
        ErrorAction = 'Stop'
    }
    if ($Body -ne $null) {
        $params['ContentType'] = 'application/json'
        # -Compress keeps the body single-line; Depth is generous for the
        # ApiKeyWrite schema (name + limit fields + zdr_policy).
        $params['Body'] = (@{} + $Body | ConvertTo-Json -Depth 8 -Compress)
    }
    return Invoke-RestMethod @params
}

function Get-InferenceKeyInfo([string]$Key) {
    if (-not (Test-InferenceKeyFormat $Key)) { return $null }
    try {
        return Invoke-RestMethod `
            -Uri ($script:InferBase + '/api/v1/api-keys/current') `
            -Headers @{ Authorization = ('Bearer ' + $Key) } `
            -Method GET -TimeoutSec $script:Timeout -ErrorAction Stop
    } catch {
        return $null
    }
}

function Assert-ApiKeyWriteName([string]$Name) {
    # Mirrors the management-openapi.json ApiKeyWrite contract:
    #   name: string, minLength 1, maxLength 120, pattern ".*\S.*"
    if ([string]::IsNullOrWhiteSpace($Name)) {
        throw 'key name must not be empty'
    }
    $name = $Name.Trim()
    if ($name.Length -gt 120) {
        throw ('key name is longer than 120 characters (got ' + $name.Length + ')')
    }
    return $name
}

function Assert-IdempotencyKey([string]$Key) {
    # management-openapi.json: Idempotency-Key header, string, 8..200 chars.
    # Reuse with a DIFFERENT body returns 409 -- so sync deliberately derives a
    # STABLE value per key name; rotate uses a fresh GUID per run.
    if ([string]::IsNullOrWhiteSpace($Key) -or $Key.Length -lt 8 -or $Key.Length -gt 200) {
        throw ('Idempotency-Key must be 8..200 characters (got ' + $Key.Length + ')')
    }
    return $Key
}

function New-InferenceKey([string]$Name, [string]$IdempotencyKey) {
    # Minimal, least-privilege creation body: a name and explicit anonymized
    # routing (zdr_policy 'off'). No spending limits are set here on purpose --
    # a key with NO limit spends real balance. If you want caps, extend this
    # body with daily_usd_limit etc. from the ApiKeyWrite schema.
    $name = Assert-ApiKeyWriteName $Name
    $idem = Assert-IdempotencyKey $IdempotencyKey
    $body = @{ name = $name; zdr_policy = 'off' }
    return Invoke-Management -Method 'POST' -Path '/api-keys' -Body $body `
        -ExtraHeaders @{ 'Idempotency-Key' = $idem }
}

function Assert-KeyId([string]$Id) {
    # Managed key ids are numeric (observed: 244804, 245160, ...). Validating
    # blocks path traversal into the management URL ('/api-keys/../../x').
    if ($Id -notmatch '^[0-9]+$') {
        throw ('invalid key id "' + $Id + '" (expected a numeric id, e.g. 245160)')
    }
    return $Id
}

function Remove-InferenceKey([string]$Id) {
    $id = Assert-KeyId $Id
    return Invoke-Management -Method 'DELETE' -Path ('/api-keys/' + $id)
}

function Get-ManagedKeys {
    return (Invoke-Management -Method 'GET' -Path '/api-keys').data
}

function Assert-JsonPath([string]$Path) {
    # Guard the regex-rewrite: only ever touch files that parse as JSON, so a
    # wrong -McpJson path can never corrupt an arbitrary text file.
    $raw = [System.IO.File]::ReadAllText($Path)
    try {
        [void](ConvertFrom-Json -InputObject $raw -ErrorAction Stop)
    } catch {
        throw ($Path + ' is not valid JSON -- refusing to rewrite it. Pass a real MCP client config (e.g. .mcp.json) via -McpJson.')
    }
    return $raw
}

function Sync-McpJson([string]$Path, [string]$Key) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn ('.mcp.json not found at ' + $Path + ' (skipping)')
        return
    }
    # Never write a key that does not have the inference-key shape -- a botched
    # provisioning must not be able to push a management token into client configs.
    if (-not (Test-InferenceKeyFormat $Key)) {
        throw 'refusing to write .mcp.json: value is not a valid inference key shape'
    }
    $raw = Assert-JsonPath $Path
    $pattern = '("NANOGPT_API_KEY"\s*:\s*")[^"]*(")'
    $hits = [regex]::Matches($raw, $pattern)
    if ($hits.Count -eq 0) {
        Write-Warn ('no NANOGPT_API_KEY entry in ' + $Path + ' (skipping)')
        return
    }
    $captured = $Key
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator] {
        param($match)
        return $match.Groups[1].Value + $captured + $match.Groups[2].Value
    }
    $updated = [regex]::Replace($raw, $pattern, $evaluator)
    if ($updated -ceq $raw) {
        Write-Ok ('.mcp.json already points at the provisioned key')
        return
    }
    # Backup first, then write atomically: a crash between truncate and write
    # must never leave the user with a half-written MCP config.
    $backup = $Path + '.bak'
    [System.IO.File]::Copy($Path, $backup, $true)
    $tmp = $Path + '.tmp'
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tmp, $updated, $utf8NoBom)
    try {
        [System.IO.File]::Replace($tmp, $Path, $null)
    } catch {
        # Replace is unavailable on some filesystems; fall back to a direct move.
        Move-Item -LiteralPath $tmp -Destination $Path -Force
    }
    Write-Ok ('.mcp.json updated (' + $hits.Count + ' entr(y/ies); backup at ' + $backup + ')')
}

function Resolve-McpJsonPath {
    if (-not [string]::IsNullOrWhiteSpace($McpJson)) { return $McpJson }
    $repoRoot = Split-Path -Parent $PSScriptRoot
    return (Join-Path $repoRoot '.mcp.json')
}

function Show-Status {
    Write-Section 'Management plane'
    $keys = @(Get-ManagedKeys)
    Write-Ok ('management token works; ' + $keys.Count + ' managed inference key(s)')
    $keys | Sort-Object { [int]$_.id } |
        Select-Object id, name, status, created_at, zdr_policy |
        Format-Table -AutoSize | Out-String -Width 200 | Write-Host

    Write-Section 'Windows environment (process -> user -> machine)'
    foreach ($name in (Get-TargetEnvVarNames)) {
        $value = Get-EffectiveEnv $name
        if ([string]::IsNullOrWhiteSpace($value)) {
            Write-Warn ($name + ' : <not set>')
            continue
        }
        if (-not (Test-InferenceKeyFormat $value)) {
            Write-Fail ($name + ' : value is not an inference-key shape (' + (Mask $value) + ')')
            continue
        }
        $info = Get-InferenceKeyInfo $value
        if ($info -eq $null) {
            Write-Fail ($name + ' : ' + (Mask $value) + ' -> invalid or revoked')
        } else {
            Write-Ok ($name + ' : ' + (Mask $value) + ' -> id=' + $info.id + ' name=' + $info.name + ' status=' + $info.status)
        }
    }

    Write-Section 'MCP config'
    $path = Resolve-McpJsonPath
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Warn ($path + ' -> not found')
        return
    }
    $raw = [System.IO.File]::ReadAllText($path)
    $entry = [regex]::Match($raw, '"NANOGPT_API_KEY"\s*:\s*"([^"]*)"')
    if (-not $entry.Success) {
        Write-Warn ($path + ' -> no NANOGPT_API_KEY entry')
        return
    }
    $mcpKey = $entry.Groups[1].Value
    if (-not (Test-InferenceKeyFormat $mcpKey)) {
        Write-Fail ($path + ' -> value is not an inference-key shape (' + (Mask $mcpKey) + ')')
        return
    }
    $info = Get-InferenceKeyInfo $mcpKey
    if ($info -eq $null) {
        Write-Fail ($path + ' -> invalid or revoked key ' + (Mask $mcpKey))
    } else {
        Write-Ok ($path + ' -> id=' + $info.id + ' name=' + $info.name + ' status=' + $info.status)
    }
}

function Get-TargetEnvVarNames {
    $names = @($TargetEnvVars)
    if ($ExportProviderHub) { $names += $script:ProviderHubVars }
    # De-duplicate while preserving order (PowerShell 5.1 has no -Unique on arrays via Select-Object reliably here).
    $seen = @{}
    $result = @()
    foreach ($n in $names) {
        if (-not $seen.ContainsKey($n)) {
            $seen[$n] = $true
            $result += $n
        }
    }
    return $result
}

# Validate that every target env var NAME is a legal Windows env var name.
# Prevents weird values from being written into the registry.
function Assert-EnvVarName([string]$Name) {
    if ($Name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw ('invalid environment variable name "' + $Name + '"')
    }
    return $Name
}

function Invoke-Sync {
    Write-Section 'Resolve inference key'
    $current = ''
    foreach ($name in $TargetEnvVars) {
        $value = Get-EffectiveEnv $name
        if (Test-InferenceKeyFormat $value) {
            if ((Get-InferenceKeyInfo $value) -ne $null) {
                $current = $value
                Write-Ok ('reusing valid key from ' + $name + ' (' + (Mask $value) + ')')
                break
            }
            Write-Warn ($name + ' holds a key that is no longer valid (' + (Mask $value) + ')')
        }
    }

    if ($Force -or [string]::IsNullOrWhiteSpace($current)) {
        if ($Force) { Write-Info '-Force set: minting a fresh inference key' }
        else { Write-Info 'no valid inference key in the environment: minting one' }
        # STABLE idempotency key per key name: safe retries replay the SAME
        # creation (returning the same secret) instead of minting duplicates.
        $idem = 'nanogpt-key-sync:' + $KeyName
        $created = New-InferenceKey -Name $KeyName -IdempotencyKey $idem
        if ([string]::IsNullOrWhiteSpace($created.key)) {
            throw 'management API returned a key object with no secret -- aborting before persisting anything'
        }
        $current = $created.key
        Write-Ok ('created inference key id=' + $created.id + ' name=' + $created.name)
    }

    Write-Section 'Persist to Windows environment (User scope / HKCU)'
    foreach ($name in (Get-TargetEnvVarNames)) {
        [void](Set-UserEnv -Name (Assert-EnvVarName $name) -Value $current)
    }

    if (-not $SkipMcpJson) {
        Write-Section 'Align MCP config'
        Sync-McpJson -Path (Resolve-McpJsonPath) -Key $current
    }

    Write-Section 'Done'
    Write-Info 'New processes read the key from NANOGPT_API_KEY.'
    Write-Warn 'Restart terminals / IDE MCP servers; already-running processes keep the old value.'
    return 0
}

function Invoke-Rotate {
    Write-Section 'Capture current key'
    $old = ''
    $oldId = ''
    foreach ($name in $TargetEnvVars) {
        $value = Get-EffectiveEnv $name
        if (-not (Test-InferenceKeyFormat $value)) { continue }
        $old = $value
        $info = Get-InferenceKeyInfo $value
        if ($info -ne $null) { $oldId = [string]$info.id }
        break
    }
    if ([string]::IsNullOrWhiteSpace($old)) {
        Write-Info 'no existing inference key found in the environment'
    } elseif ($oldId -ne '') {
        Write-Info ('replacing id=' + $oldId + ' (' + (Mask $old) + ')')
    } else {
        Write-Warn 'existing environment key is already invalid; nothing usable to replace'
    }

    Write-Section 'Mint replacement'
    # FRESH idempotency key per rotate run: rotate must NEVER replay the sync
    # idempotency key, or it would silently return the OLD key instead of a new one.
    $idem = 'nanogpt-key-rotate:' + [guid]::NewGuid().ToString()
    $created = New-InferenceKey -Name $KeyName -IdempotencyKey $idem
    if ([string]::IsNullOrWhiteSpace($created.key)) {
        throw 'management API returned a key object with no secret -- aborting before persisting anything'
    }
    Write-Ok ('created inference key id=' + $created.id + ' name=' + $created.name)

    # Persist BEFORE revoking the old key: if the HKCU write fails, the old key
    # is still active and the environment is not left pointing at a dead key.
    Write-Section 'Persist to Windows environment (User scope / HKCU)'
    foreach ($name in (Get-TargetEnvVarNames)) {
        [void](Set-UserEnv -Name (Assert-EnvVarName $name) -Value $created.key)
    }

    if (-not $SkipMcpJson) {
        Write-Section 'Align MCP config'
        Sync-McpJson -Path (Resolve-McpJsonPath) -Key $created.key
    }

    if ($oldId -ne '') {
        if ($RevokeOld) {
            if (-not $Yes) {
                Write-Warn '-RevokeOld needs -Yes; old key id=' + $oldId + ' left active'
            } else {
                Write-Section 'Revoke replaced key'
                Remove-InferenceKey $oldId | Out-Null
                Write-Ok ('revoked old key id=' + $oldId)
            }
        } else {
            Write-Info ('old key id=' + $oldId + ' left active')
            Write-Info ('revoke it later with: -Action revoke -KeyId ' + $oldId + ' -Yes')
        }
    }

    Write-Section 'Done'
    Write-Warn 'Restart terminals / IDE MCP servers to pick up the rotated key.'
    return 0
}

function Invoke-Revoke {
    if ([string]::IsNullOrWhiteSpace($KeyId)) {
        throw 'revoke needs -KeyId <id>. List ids with: nanogpt-key.ps1 status'
    }
    $id = Assert-KeyId $KeyId
    if (-not $Yes) {
        Write-Warn ('refusing to DELETE id=' + $id + ' without -Yes; the secret cannot be recovered')
        Write-Info ('re-run: -Action revoke -KeyId ' + $id + ' -Yes')
        return 2
    }
    # Guard: refuse to revoke the key the environment currently depends on,
    # unless the operator explicitly says so with -Force. Deleting the live key
    # would 401 every running consumer.
    foreach ($name in $TargetEnvVars) {
        $value = Get-EffectiveEnv $name
        if (-not (Test-InferenceKeyFormat $value)) { continue }
        $info = Get-InferenceKeyInfo $value
        if ($info -ne $null -and ([string]$info.id) -eq $id) {
            if (-not $Force) {
                Write-Fail ('id=' + $id + ' is the key currently used by ' + $name)
                Write-Info ('run "-Action sync" first to move the environment to a fresh key, or pass -Force to revoke it anyway')
                return 3
            }
            Write-Warn ('-Force given: revoking the key currently used by ' + $name)
        }
    }
    Write-Section 'Revoke managed inference key'
    Remove-InferenceKey $id | Out-Null
    Write-Ok ('deleted inference key id=' + $id)
    Write-Warn 'any process still using that key will start receiving 401'
    return 0
}

function Clear-Secrets {
    # Best-effort scrub of in-memory secrets so they do not linger in the
    # session after the script exits. Not a security boundary (the token also
    # lives in HKCU by design), but it keeps the secret out of any later
    # accidental variable dump in the same process.
    $script:MgmtKey = ''
}

try {
    Write-Section 'NanoGPT key system'
    $script:MgmtKey = Resolve-ManagementKey
    Write-Ok ('management token: ' + (Mask $script:MgmtKey))
    Write-Info ('action: ' + $Action)

    $exitCode = 0
    switch ($Action) {
        'status' { Show-Status }
        'sync'   { $exitCode = Invoke-Sync }
        'rotate' { $exitCode = Invoke-Rotate }
        'revoke' { $exitCode = Invoke-Revoke }
    }
    exit $exitCode
} catch {
    Write-Host ''
    Write-Fail $_.Exception.Message
    $body = Get-HttpErrorBody $_
    if ($body -ne $_.Exception.Message) {
        # Truncate: the API can echo long request bodies back on 4xx.
        Write-Host ('         ' + $body.Substring(0, [Math]::Min(600, $body.Length))) -ForegroundColor DarkGray
    }
    if ($body -match 'insufficient_scope') {
        Write-Info 'The management token is missing a scope. Needed: api_keys:read (list) and api_keys:write (create/revoke).'
        Write-Info 'Create a token at https://nano-gpt.com/settings#management-api-tokens and store it as NANOGPT_MGMT_API_KEY.'
    }
    exit 1
} finally {
    Clear-Secrets
}
