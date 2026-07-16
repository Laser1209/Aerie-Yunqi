# Brings up the backend briefly and smoke-tests /api/health,
# /api/chat/send with {text}, and /api/napcat/status.
param([int]$WaitStart = 6, [int]$WaitEnd = 2)

Set-Location $PSScriptRoot\..
$log = "$PSScriptRoot\..\logs\smoke_stdout.log"
Remove-Item $log -ErrorAction SilentlyContinue

Write-Host "[smoke] launching backend..." -ForegroundColor Cyan
Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" `
    -ArgumentList "-m","main" `
    -WorkingDirectory (Get-Location) `
    -RedirectStandardOutput $log `
    -WindowStyle Hidden

Start-Sleep -Seconds $WaitStart

function try_url($label, $url, $body = $null, $method = 'GET') {
    Write-Host "[smoke] $label ($method $url)" -ForegroundColor Yellow
    try {
        if ($method -eq 'POST') {
            $resp = Invoke-RestMethod -Uri $url -Method POST -Body ($body | ConvertTo-Json -Depth 4) -ContentType 'application/json' -TimeoutSec 5
        } else {
            $resp = Invoke-RestMethod -Uri $url -Method GET -TimeoutSec 5
        }
        Write-Host ("[OK ] " + ($resp | ConvertTo-Json -Depth 4 -Compress)) -ForegroundColor Green
        return $resp
    } catch {
        Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
        return $null
    }
}

try_url "health"   "http://127.0.0.1:7890/api/health"
try_url "chat"     "http://127.0.0.1:7890/api/chat/send" @{ user_id = 0; text = "ping" } 'POST'
try_url "napcat"   "http://127.0.0.1:7890/api/napcat/status"

Write-Host "[smoke] killing backend..." -ForegroundColor Cyan
Get-Process -Name pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.StartTime -gt (Get-Date).AddMinutes(-2)
} | ForEach-Object { $_ | Stop-Process -Force }

Start-Sleep -Seconds $WaitEnd
Write-Host "[smoke] done." -ForegroundColor Cyan
