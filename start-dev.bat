@echo off
REM ============================================================
REM Aerie / Yunqi - dev launcher (pure cmd.exe, no packaging)
REM Double-click to start, or run: start-dev.bat
REM ============================================================

cd /d "%~dp0"

set "ROOT=%cd%"
set "ELECTRON_DIR=%ROOT%\electron"
set "ELECTRON_BIN=%ELECTRON_DIR%\node_modules\.bin\electron.cmd"

echo.
echo === Aerie dev launcher ===
echo ROOT: %ROOT%
echo.

REM 1. Check electron dependency
if not exist "%ELECTRON_BIN%" (
    echo [ERROR] electron dependency missing.
    echo Please run once in cmd:
    echo     cd /d "%ELECTRON_DIR%"
    echo     npm install
    echo.
    pause
    exit /b 1
)

REM 2. Print Python info (Electron will spawn Python itself; this is just a hint)
if exist "%ROOT%\.venv\Scripts\pythonw.exe" (
    echo [INFO] Python: %ROOT%\.venv\Scripts\pythonw.exe
) else (
    echo [INFO] Python: system pythonw / python from PATH
)

REM 3. Launch Electron in dev mode
echo.
echo [INFO] Starting Electron (dev mode)...
echo [INFO] Press Ctrl+C to quit.
echo.

cd /d "%ELECTRON_DIR%"
call npm start

echo.
echo [WARN] Electron exited (code=%ERRORLEVEL%)
pause
