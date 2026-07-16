$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..

Write-Host "[live] launch backend (no sandbox via outer shell)..." -ForegroundColor Cyan
$proc = Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" `
    -ArgumentList "-m","main" `
    -WorkingDirectory (Get-Location) `
    -RedirectStandardOutput ".\logs\live_stdout.log" `
    -RedirectStandardError  ".\logs\live_stderr.log" `
    -PassThru -NoNewWindow

try {
    Write-Host "[live] pid=$($proc.Id) - waiting 10s for boot..."
    Start-Sleep -Seconds 10

    function TryUrl($label, $url, $method = 'GET', $body = $null) {
        Write-Host "[$label] $method $url" -NoNewline
        try {
            $args = @{ Uri = $url; Method = $method; TimeoutSec = 8 }
            if ($body) { $args['Body'] = ($body | ConvertTo-Json -Depth 4 -Compress); $args['ContentType'] = 'application/json' }
            $r = Invoke-RestMethod @args
            Write-Host (" -> OK   " + ($r | ConvertTo-Json -Depth 5 -Compress)) -ForegroundColor Green
        } catch {
            Write-Host (" -> FAIL " + $_.Exception.Message) -ForegroundColor Red
        }
    }

    TryUrl "health"    "http://127.0.0.1:7890/api/health"
    TryUrl "napcat"    "http://127.0.0.1:7890/api/napcat/status"
    TryUrl "emotion"   "http://127.0.0.1:7890/api/emotion/current"
    TryUrl "tools"     "http://127.0.0.1:7890/api/tools"
    TryUrl "history"   "http://127.0.0.1:7890/api/chat/history?limit=3"
    TryUrl "send-text" "http://127.0.0.1:7890/api/chat/send" "POST" @{ user_id = 0; text = "你好, 伊塔" }
} finally {
    Write-Host "[live] shutting down backend..." -ForegroundColor Cyan
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    Get-Process -Name pythonw -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt (Get-Date).AddSeconds(-30) } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[live] done"
}
