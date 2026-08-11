# boot_trace.ps1 - One-click Aerie import time profiler
# Usage: powershell -ExecutionPolicy Bypass -File scripts\boot_trace.ps1
# Output: importtime.log + boot_trace_data.md (via parser)

$ErrorActionPreference = "Stop"
$projectRoot = "e:\Agent_reply"
$python = "C:\Python314\python.exe"
$probe = Join-Path $projectRoot "scripts\boot_trace_probe.py"
$parser = Join-Path $projectRoot "scripts\boot_trace_parser.py"
$importtimeLog = Join-Path $projectRoot "importtime.log"
$stdoutFile = Join-Path $projectRoot "boot_stdout.tmp"
$durationFile = Join-Path $projectRoot "boot_probe_duration.tmp"
$exitcodeFile = Join-Path $projectRoot "boot_probe_exitcode.tmp"

# Clean previous logs
Remove-Item -Path $importtimeLog, $stdoutFile, $durationFile, $exitcodeFile -Force -ErrorAction SilentlyContinue

Write-Host "==== Aerie Import Time Trace ====" -ForegroundColor Cyan
Write-Host "[1/3] Probe  : $probe"
Write-Host "      Python: $python"
Write-Host "      Log   : $importtimeLog"
Write-Host ""

$bootStart = Get-Date

# Run probe with -X importtime; stderr -> importtime.log, stdout -> tmp
$proc = Start-Process -FilePath $python `
    -ArgumentList "-X", "importtime", $probe `
    -RedirectStandardError $importtimeLog `
    -RedirectStandardOutput $stdoutFile `
    -NoNewWindow `
    -PassThru `
    -WorkingDirectory $projectRoot

# Wait up to 180 seconds (import of chromadb/onnxruntime may be slow on first run)
if (-not $proc.WaitForExit(180000)) {
    Write-Host "[TIMEOUT] Probe did not finish in 180s, killing..." -ForegroundColor Yellow
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $proc.Id } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

$importDuration = ((Get-Date) - $bootStart).TotalSeconds
$exitCode = if ($proc.HasExited) { $proc.ExitCode } else { -1 }

# Save duration and exit code for parser
Set-Content -Path $durationFile -Value ([math]::Round($importDuration, 3)) -Encoding UTF8
Set-Content -Path $exitcodeFile -Value $exitCode -Encoding UTF8

Write-Host "[2/3] Probe finished in $([math]::Round($importDuration, 2))s (exit=$exitCode)" -ForegroundColor Cyan

# Show stdout (probe confirmation)
if (Test-Path $stdoutFile) {
    $stdoutContent = Get-Content $stdoutFile -Raw -ErrorAction SilentlyContinue
    if ($stdoutContent) {
        Write-Host "      stdout: $($stdoutContent.Trim())" -ForegroundColor Gray
    }
}

Write-Host "[3/3] Running parser..." -ForegroundColor Cyan
& $python $parser

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Parser failed with exit $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "==== Done ====" -ForegroundColor Green
