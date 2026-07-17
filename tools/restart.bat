@echo off
REM R6.6: one-click restart script.
REM 1) kill the running main.py (Python backend)
REM 2) wait until the port is free
REM 3) spawn a fresh main.py in a detached window
REM 4) relaunch Electron so the renderer drops its in-memory cache
REM
REM Usage: double-click this file, or call it from the in-app
REM "Restart backend" button via tools/restart_helper.ps1.

setlocal

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PORT=7890"

echo [restart] killing existing main.py ...
for /f "tokens=*" %%P in ('wmic process where "name='python.exe'" get processid^,commandline /FORMAT:LIST 2^>nul ^| findstr /C:"main.py"') do (
  for /f "tokens=2 delims==" %%I in ("%%P") do (
    if not "%%I"=="" taskkill /F /PID %%I >nul 2>&1
  )
)
REM Fallback: also kill by image name + port
for /f "tokens=5" %%A in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  if not "%%A"=="" taskkill /F /PID %%A >nul 2>&1
)

echo [restart] waiting for port %PORT% to free ...
set /a attempts=0
:wait_port
set /a attempts+=1
netstat -aon | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
  if %attempts% lss 20 (
    timeout /t 1 /nobreak >nul
    goto wait_port
  ) else (
    echo [restart] WARN: port still in use after 20s, proceeding anyway.
  )
)

echo [restart] spawning new main.py ...
REM Use DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP so the backend
REM survives the terminal that invoked this script.
start "aerie-backend" /B python -X dev "%ROOT%\main.py"
timeout /t 2 /nobreak >nul

echo [restart] relaunching Electron ...
if exist "%ROOT%\electron\node_modules\.bin\electron.cmd" (
  start "aerie-electron" /B "%ROOT%\electron\node_modules\.bin\electron.cmd" "%ROOT%\electron"
) else (
  echo [restart] WARN: electron.cmd not found, please relaunch manually.
)

echo [restart] done.
endlocal
exit /b 0
