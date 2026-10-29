[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Source,
    [string]$Root = (Join-Path $(if ($env:CODEX_ROUTE_HOME) { $env:CODEX_ROUTE_HOME } else { Join-Path $env:USERPROFILE '.codex\route-switch' }) 'compat')
)

$ErrorActionPreference = 'Stop'
$builder = Join-Path $PSScriptRoot 'build_compat.py'
$adapter = Join-Path $PSScriptRoot 'auto_adapt.py'
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $python) { throw 'Python is required for the isolated compatibility adapter.' }
if (-not $node) { throw 'Node.js is required for the compatibility syntax and fixture checks.' }
if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) { throw "Missing adapter builder: $builder" }
if (-not (Test-Path -LiteralPath $adapter -PathType Leaf)) { throw "Missing adapter runner: $adapter" }
$result = & $python $adapter --version $Version --source $Source --root $Root --builder $builder --node $node
if ($LASTEXITCODE -ne 0) { throw "Codex compatibility adaptation failed: $result" }
$result
