@echo off
setlocal EnableExtensions
title Aerie 24H Monitor - close to stop
cd /d "%~dp0" || exit /b 1
echo ============================================
echo   Aerie 24H Monitor - one-click start
echo   Close this window to stop monitoring
echo ============================================
echo.
echo Log: D:\Aerie\24H-LOG
echo.
echo Starting monitor (watchdog mode)...
echo.
python scripts\24h_monitor_watchdog.py --loop-hours 24 --backoff 5
echo.
echo Monitor exited with code %ERRORLEVEL%.
echo.
if /i not "%1"=="--nopause" (
    pause
)
endlocal
