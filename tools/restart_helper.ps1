# R6.6: one-click restart helper (PowerShell) — callable from Electron IPC.
# Kills the running main.py, waits for the port to free, then spawns a
# fresh one in a detached process. Returns 0 on success, 1 on failure.
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 7890,
    [int]$TargetPid = 0,
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = 'Stop'
$ROOT = (Resolve-Path $ProjectRoot).Path
Write-Host "[restart] project root: $ROOT"
Write-Host "[restart] killing existing main.py ..."

Start-Sleep -Seconds 2
if ($TargetPid -gt 0) {
    Write-Host "[restart] killing target pid $TargetPid"
    try {
        Stop-Process -Id $TargetPid -Force -ErrorAction Stop
    }
    catch {
        Write-Host "[restart] FAILED to stop target pid ${TargetPid}: $_"
        exit 1
    }
}
else {
    # Compatibility fallback for direct manual invocation.
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine -like "*main.py*") {
            Write-Host "[restart] killing pid $($p.ProcessId)"
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
        }
    }
}

function Test-LoopbackPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(250) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

Write-Host "[restart] waiting for port $Port to free ..."
$attempts = 0
while ($attempts -lt 20) {
    if (-not (Test-LoopbackPort)) { break }
    $attempts++
    Start-Sleep -Seconds 1
}
if ($attempts -ge 20) {
    Write-Host "[restart] FAILED: port still in use after 20s."
    exit 1
}

Write-Host "[restart] spawning new main.py ..."
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PythonExecutable
$psi.Arguments = "-X dev `"$ROOT\main.py`""
$psi.WorkingDirectory = $ROOT
$psi.UseShellExecute = $true
$psi.WindowStyle = 'Hidden'
$psi.CreateNoWindow = $true
try {
    [System.Diagnostics.Process]::Start($psi) | Out-Null
    Write-Host "[restart] main.py launched."
}
catch {
    Write-Host "[restart] FAILED to launch main.py: $_"
    exit 1
}
Write-Host "[restart] done. The Electron window will reconnect automatically."
exit 0
