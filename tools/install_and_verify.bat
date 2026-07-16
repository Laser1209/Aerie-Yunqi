@echo off
REM === Yunqi / Aerie - dep installer + backend import check ===
REM Runs against the venv in repo root.

setlocal
cd /d "%~dp0\.."

if exist ".venv\Scripts\pythonw.exe" (
    set "PY=.venv\Scripts\pythonw.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    echo [FATAL] no venv found, please create e:\Agent_reply\.venv first
    pause
    exit /b 1
)
set "LOG=%~dp0\..\logs\install.log"

echo === Installing Python deps (output to %LOG%) ===
"%PY%" -m pip install ^
  fastapi "uvicorn[standard]" ^
  aiohttp websockets ^
  psutil pyyaml python-dotenv ^
  apscheduler loguru openai ^
  requests httpx pywin32 pyautogui ^
  > "%LOG%" 2>&1
if errorlevel 1 (
    echo [FAIL] pip install failed.  Last 30 lines:
    powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 30"
    pause
    exit /b 1
)
echo [OK] pip install finished.  Tail of log:
powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 5"

echo.
echo === Importing core modules ===
"%PY%" -c "import core.api_server, core.companion; print('CORE_OK')" 2>&1
if errorlevel 1 (
    echo [FAIL] core import failed.
    pause
    exit /b 1
)
echo [OK] core modules import cleanly.
echo.
echo === All checks passed.
pause
exit /b 0
