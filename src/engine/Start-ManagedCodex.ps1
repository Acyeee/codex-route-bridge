param([switch]$Check, [switch]$Restart, [switch]$AllowForce)
$ErrorActionPreference = 'Stop'
$taskUnpatched = $false
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    . (Join-Path $PSScriptRoot 'Codex-Lifecycle.ps1')
    $taskPackages = @(Get-AppxPackage -Name OpenAI.Codex | Sort-Object Version -Descending)
    $taskPackage = $taskPackages | Select-Object -First 1
    if (-not $taskPackage) { throw 'Official Codex installation missing.' }
    $taskSource = Join-Path $taskPackage.InstallLocation 'app'
    $taskRuntime = $taskSource
    if ($env:CODEX_ROUTE_KIND -eq 'relay') {
        $taskRoot = Join-Path $env:CODEX_ROUTE_HOME 'compat'
        $taskReceiptFile = Join-Path $taskRoot (([string]$taskPackage.Version) + '/verification.json')
        if (Test-Path -LiteralPath $taskReceiptFile -PathType Leaf) {
            # A runtime built by an older revision of the initial-bundle patch is set aside and rebuilt.
            $taskStale = Get-Content -LiteralPath $taskReceiptFile -Raw | ConvertFrom-Json
            if ([string]$taskStale.asset -like 'app-initial-*' -and [int]$taskStale.patchRevision -lt 5) {
                $taskStaleApp = Join-Path $taskRoot (([string]$taskPackage.Version) + '/runtime/ChatGPT.exe')
                if (@(Get-ManagedDesktopProcesses -AllowedPaths @($taskStaleApp)).Count -gt 0) {
                    if (-not $Restart) { throw 'Confirm restart before replacing a running Codex.' }
                    Stop-ManagedDesktop -AllowedPaths @($taskStaleApp) -AllowForce:$AllowForce
                }
                Rename-Item -LiteralPath (Join-Path $taskRoot ([string]$taskPackage.Version)) -NewName ('.superseded-' + [string]$taskPackage.Version + '-' + (Get-Date -Format 'yyyyMMddHHmmss'))
            }
        }
        if (-not (Test-Path -LiteralPath $taskReceiptFile -PathType Leaf)) {
            $taskAdapter = Join-Path $PSScriptRoot 'compat\Update-CodexCompat.ps1'
            if (Test-Path -LiteralPath $taskAdapter -PathType Leaf) {
                # Stage and validate the current official version without launching it.
                & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $taskAdapter -Version ([string]$taskPackage.Version) -Source $taskSource -Root $taskRoot | Out-Null
            }
        }
        if (Test-Path -LiteralPath $taskReceiptFile -PathType Leaf) {
            $taskReceipt = Get-Content -LiteralPath $taskReceiptFile -Raw | ConvertFrom-Json
            if ($taskReceipt.source -ne $taskSource) { throw 'Compatibility version does not match installed Codex.' }
            $taskExpectedRuntime = Join-Path $taskRoot (([string]$taskPackage.Version) + '/runtime')
            if ($taskReceipt.integrityRetained -ne $true -or $taskReceipt.officialInstallationModified -ne $false -or
                [IO.Path]::GetFullPath($taskReceipt.runtime) -ne [IO.Path]::GetFullPath($taskExpectedRuntime)) {
                throw 'Compatibility verification is invalid. Existing instance retained.'
            }
            $taskRuntime = $taskReceipt.runtime
        } else {
            # No reviewed compatibility build for this Codex version: run the official app unpatched through the route bridge.
            # The composer may be locked while the Plus quota is exhausted.
            $taskUnpatched = $true
        }
    }
    $taskApp = Join-Path $taskRuntime 'ChatGPT.exe'
    $taskBridge = Join-Path $PSScriptRoot 'codex-route-bridge.exe'
    foreach ($taskFile in @($taskApp,$taskBridge,(Join-Path $taskRuntime 'resources/app.asar'))) {
        if (-not (Test-Path -LiteralPath $taskFile -PathType Leaf)) { throw 'Required desktop component missing.' }
    }
    if ($Check) {
        @{ready=$true;version=[string]$taskPackage.Version;managedRuntime=($taskRuntime -ne $taskSource);unpatched=$taskUnpatched} | ConvertTo-Json -Compress
        exit 0
    }
    $taskAllowed = @($taskApp, (Join-Path $taskSource 'ChatGPT.exe'))
    foreach ($taskInstalledPackage in $taskPackages) {
        $taskAllowed += Join-Path $taskInstalledPackage.InstallLocation 'app/ChatGPT.exe'
    }
    $taskCompatibilityRoot = Join-Path $env:CODEX_ROUTE_HOME 'compat'
    if (Test-Path -LiteralPath $taskCompatibilityRoot) {
        foreach ($taskRelease in Get-ChildItem -LiteralPath $taskCompatibilityRoot -Directory) {
            if ($taskRelease.Name -notmatch '^\d+(\.\d+){3}$') { continue }
            $taskVerifiedApp = Join-Path $taskRelease.FullName 'runtime/ChatGPT.exe'
            if (Test-Path -LiteralPath (Join-Path $taskRelease.FullName 'verification.json')) {
                $taskAllowed += $taskVerifiedApp
            }
        }
    }
    if (@(Get-ManagedDesktopProcesses -AllowedPaths $taskAllowed).Count -gt 0) {
        if (-not $Restart) { throw 'Confirm restart before replacing a running Codex.' }
        Stop-ManagedDesktop -AllowedPaths $taskAllowed -AllowForce:$AllowForce
    }
    $taskStart = New-Object Diagnostics.ProcessStartInfo
    $taskStart.FileName = $taskApp
    $taskStart.WorkingDirectory = $taskRuntime
    # Shell launch: the app must not inherit this script's stdout/stderr pipes, or the caller waits until Codex exits.
    $taskStart.UseShellExecute = $true
    # A shell launch inherits this process environment, so the route settings are set here.
    $env:CODEX_CLI_PATH = $taskBridge
    $env:CODEX_ELECTRON_RESOURCES_PATH = Join-Path $taskSource 'resources'
    $env:CODEX_ELECTRON_BUNDLED_PLUGINS_RESOURCES_PATH = Join-Path $taskSource 'resources'
    $taskProcess = [Diagnostics.Process]::Start($taskStart)
    Start-Sleep -Milliseconds 1000
    if ($taskProcess.HasExited) { throw 'Codex exited during startup. No launch confirmation recorded.' }
    @{pid=$taskProcess.Id;unpatched=$taskUnpatched} | ConvertTo-Json -Compress
} catch { [Console]::Error.WriteLine((([string]$_.Exception.Message).Trim()) + ' [line ' + $_.InvocationInfo.ScriptLineNumber + ']'); exit 1 }
