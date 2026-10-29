# Compile the route bridge into engine\ with the C# compiler that ships with Windows (.NET Framework 4.x).
$ErrorActionPreference = 'Stop'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw ".NET Framework 4 compiler not found: $csc" }
$out = Join-Path $PSScriptRoot 'engine\codex-route-bridge.exe'
& $csc -nologo -optimize "-out:$out" -r:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'bridge\ManagedRoute.cs')
if ($LASTEXITCODE -ne 0) { throw 'Bridge build failed.' }
"Built $out"
