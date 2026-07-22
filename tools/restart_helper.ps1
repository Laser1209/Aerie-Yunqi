# R6.6: one-click restart helper (PowerShell) — callable from Electron IPC.
# Kills the running main.py, waits for the port to free, then spawns a
# fresh one in a detached process. Returns 0 on success, 1 on failure.
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 7890
)

$ErrorActionPreference = 'Stop'
$ROOT = (Resolve-Path $ProjectRoot).Path
Write-Host "[restart] project root: $ROOT"
Write-Host "[restart] killing existing main.py ..."

# Kill any python.exe whose command line contains "main.py"
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    if ($p.CommandLine -and $p.CommandLine -like "*main.py*") {
        Write-Host "[restart] killing pid $($p.ProcessId) ($($p.CommandLine.Substring(0, [Math]::Min(80, $p.CommandLine.Length)))...)"
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
    }
}
# Also free the port directly
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    Write-Host "[restart] freeing port $Port (pid $($c.OwningProcess))"
    try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop } catch {}
}

Write-Host "[restart] waiting for port $Port to free ..."
$attempts = 0
while ($attempts -lt 20) {
    $still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $still) { break }
    $attempts++
    Start-Sleep -Seconds 1
}
if ($attempts -ge 20) {
    Write-Host "[restart] WARN: port still in use after 20s."
}

Write-Host "[restart] spawning new main.py ..."
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
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
