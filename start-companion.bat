@echo off
REM ========================================
REM   OpenCloud Companion Launcher
REM   Pure-ASCII / ANSI encoding
REM ========================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "WORKSPACE=%cd%"
set "NAPCAT_DIR=%WORKSPACE%\NapCat\NapCat.Shell"
set "LAUNCHER_USER=%NAPCAT_DIR%\launcher-user.bat"
set "COMPANION_DIR=%WORKSPACE%\OpenCloud_Companion"
set "COMPANION_SCRIPT=%COMPANION_DIR%\main.py"
set "WS_PORT=3001"

echo ========================================
echo   OpenCloud Companion Launcher
echo ========================================
echo.

REM ===== 1. Sanity check =====
echo [1/3] Checking files ...
if not exist "%LAUNCHER_USER%" (
    echo [ERROR] launcher-user.bat not found: %LAUNCHER_USER%
    pause
    exit /b 1
)
if not exist "%COMPANION_SCRIPT%" (
    echo [ERROR] Companion main.py not found: %COMPANION_SCRIPT%
    pause
    exit /b 1
)
echo   Files OK
echo.

REM ===== 2. Kill old processes =====
echo [2/3] Cleaning up old processes ...
taskkill /F /IM QQ.exe 2>nul
taskkill /F /IM QQEX.exe 2>nul
taskkill /F /IM NapCatWinBootMain.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq OpenCloud-Companion*" 2>nul
timeout /t 2 /nobreak >nul
echo   Cleanup done
echo.

REM ===== 3. Launch NapCat via launcher-user.bat (NOT direct exe) =====
echo [3/3] Launching NapCat + QQ injection ...
echo   Using: launcher-user.bat -q 3998874040
echo   This handles env vars, patch package, and hook DLL correctly.
start "NapCat-Ita" /MIN cmd /c "cd /d "%NAPCAT_DIR%" && call "%LAUNCHER_USER%" -q 3998874040"
echo   NapCat launched.
echo.

REM ===== 4. Wait for WebSocket port 3001 =====
echo   Waiting for ws://localhost:%WS_PORT% ...
set /a RETRIES=0
:wait_loop
set /a RETRIES+=1
timeout /t 3 /nobreak >nul
netstat -ano 2^>nul | findstr ":%WS_PORT% .*LISTENING" >nul
if %ERRORLEVEL% equ 0 (
    echo   WebSocket port %WS_PORT% is UP
    goto :port_ready
)
if !RETRIES! geq 15 (
    echo [ERROR] WebSocket port %WS_PORT% not up after 45s
    echo   Please check NapCat logs at: %NAPCAT_DIR%\logs
    pause
    exit /b 1
)
echo   ... waiting [!RETRIES!/15]
goto :wait_loop

:port_ready
echo.

REM ===== 5. Launch AI Companion =====
echo   Launching AI Companion (background) ...
start "OpenCloud-Companion" /MIN python "%COMPANION_SCRIPT%"
echo   Companion launched.
echo.

echo ========================================
echo   ALL DONE
echo   - NapCat + QQ: 3998874040 (Ita)
echo   - AI Companion: running in background
echo   - WebSocket: ws://localhost:%WS_PORT%
echo ========================================
echo.
echo This window will close in 8 seconds ...
timeout /t 8 /nobreak >nul
exit
