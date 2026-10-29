param([switch]$Restart, [switch]$AllowForce)
# Launch Codex on the currently selected route without a UI.
$ErrorActionPreference = 'Stop'
$taskPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $taskPython) { $taskPython = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $taskPython) { throw 'Python 3 is required.' }
$taskHome = if ($env:CODEX_ROUTE_HOME) { $env:CODEX_ROUTE_HOME } else { Join-Path $env:USERPROFILE '.codex/route-switch' }
$taskActive = Join-Path $taskHome 'active-profile.json'
$taskId = if (Test-Path -LiteralPath $taskActive) { (Get-Content -LiteralPath $taskActive -Raw | ConvertFrom-Json).profileId } else { 'official' }
$taskRequest = @{operation='launch';args=@{id=$taskId;restart=[bool]$Restart;allowForce=[bool]$AllowForce}} | ConvertTo-Json -Compress
$taskRequest | & $taskPython -I (Join-Path $PSScriptRoot 'desktop-helper.py')
if ($LASTEXITCODE -ne 0) { exit 1 }
