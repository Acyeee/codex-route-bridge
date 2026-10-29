function Get-ManagedDesktopProcesses {
    param([string[]]$AllowedPaths)
    $taskSession = [Diagnostics.Process]::GetCurrentProcess().SessionId
    @(Get-Process -Name ChatGPT,Codex -ErrorAction SilentlyContinue | Where-Object {
        $_.SessionId -eq $taskSession -and $_.Path -and $AllowedPaths -contains $_.Path
    })
}

function Stop-ManagedDesktop {
    param([string[]]$AllowedPaths, [switch]$AllowForce)
    $taskProcesses = @(Get-ManagedDesktopProcesses -AllowedPaths $AllowedPaths)
    if ($taskProcesses.Count -eq 0) { return }
    # Snapshot descendants before closing a parent so orphaned CLI/tool workers remain identifiable.
    $taskRows = @(Get-CimInstance -Query 'SELECT ProcessId, ParentProcessId FROM Win32_Process')
    $taskIds = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($taskProcess in $taskProcesses) { [void]$taskIds.Add($taskProcess.Id) }
    do {
        $taskAdded = $false
        foreach ($taskRow in $taskRows) {
            if ($taskIds.Contains([int]$taskRow.ParentProcessId) -and $taskIds.Add([int]$taskRow.ProcessId)) { $taskAdded = $true }
        }
    } while ($taskAdded)
    $taskTracked = @()
    foreach ($taskId in $taskIds) {
        $taskProcess = Get-Process -Id $taskId -ErrorAction SilentlyContinue
        if ($taskProcess) { $taskTracked += @{Id=$taskProcess.Id; Started=$taskProcess.StartTime; Path=$taskProcess.Path} }
    }
    # Process.CloseMainWindow misses owned windows. Leave hidden IPC/tray windows alone.
    if (-not ('CodexRoute.DesktopClose' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace CodexRoute {
    public static class DesktopClose {
        delegate bool WindowCallback(IntPtr window, IntPtr state);
        [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback callback, IntPtr state);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out int pid);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
        public static void Request(int[] pids) {
            EnumWindows((window, state) => {
                int pid; GetWindowThreadProcessId(window, out pid);
                if (Array.IndexOf(pids, pid) >= 0 && IsWindowVisible(window)) PostMessage(window, 0x0010, IntPtr.Zero, IntPtr.Zero);
                return true;
            }, IntPtr.Zero);
        }
    }
}
'@
    }
    foreach ($taskProcess in $taskProcesses) {
        try { [void]$taskProcess.CloseMainWindow() } catch { }
    }
    [CodexRoute.DesktopClose]::Request([int[]]@($taskProcesses | ForEach-Object { $_.Id }))
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $taskRemaining = @(Get-TrackedDesktopProcesses -Tracked $taskTracked)
        if ($taskRemaining.Count -eq 0) { return }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $taskDeadline)
    if (-not $AllowForce) { throw 'Codex did not exit. Existing instance retained; confirm the restart and try again.' }
    # Re-resolve each PID and its executable before terminating only the approved instance tree.
    foreach ($taskProcess in $taskRemaining) {
        $taskCurrent = Get-Process -Id $taskProcess.Id -ErrorAction SilentlyContinue
        if ($taskCurrent -and $taskCurrent.StartTime -eq $taskProcess.StartTime -and $taskCurrent.Path -eq $taskProcess.Path) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $taskProcess.Id /T /F 2>&1 | Out-Null
        }
    }
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        if (@(Get-TrackedDesktopProcesses -Tracked $taskTracked).Count -eq 0) { return }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $taskDeadline)
    throw 'Codex processes did not exit. No second instance was launched.'
}

function Get-TrackedDesktopProcesses {
    param([object[]]$Tracked)
    foreach ($taskIdentity in $Tracked) {
        $taskProcess = Get-Process -Id $taskIdentity.Id -ErrorAction SilentlyContinue
        if ($taskProcess -and $taskProcess.StartTime -eq $taskIdentity.Started -and $taskProcess.Path -eq $taskIdentity.Path) { $taskProcess }
    }
}
