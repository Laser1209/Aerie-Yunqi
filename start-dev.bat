@echo off
echo ============================================
echo  Aerie (Yunqi) v13.9.8 — Dev Startup
echo ============================================
echo.

cd /d "%~dp0"

:: Check Python dependencies
echo [1/3] Checking Python dependencies...
.venv\Scripts\python.exe -c "import fastapi, uvicorn, aiohttp, websockets, psutil, yaml, dotenv, loguru" 2>nul
if %errorlevel% neq 0 (
    echo Installing missing dependencies...
    .venv\Scripts\pip.exe install -r requirements.txt --quiet
)

:: Kill any leftover Python processes
echo [2/3] Cleaning up old processes...
taskkill /f /im python.exe 2>nul >nul
taskkill /f /im pythonw.exe 2>nul >nul
timeout /t 1 /nobreak >nul

:: Start Electron (which auto-starts Python backend)
echo [3/3] Starting Electron...
cd electron
call npm start

pause
