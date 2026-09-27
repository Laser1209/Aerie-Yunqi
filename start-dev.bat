@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"

REM ==============================================================
REM Runtime environment selection (explicit, never silent)
REM
REM F: is the recommended install location (keeps C: from filling up);
REM when absent, fall back to the project .venv.
REM
REM When both venvs exist, which one wins depends on whether the F:
REM directory is present. That implicit fallback, combined with a
REM too-narrow dependency check, previously produced a silent-degrade
REM failure: deps were missing yet the check passed, so the app booted
REM with broken capabilities (QR login errored, news briefs skipped).
REM
REM So: print the resolved environment and record it to a log file.
REM
REM NOTE: keep this file ASCII-only. cmd.exe reads .bat in the system
REM ANSI codepage (GBK here); non-ASCII comments get byte-misaligned
REM and cmd then tries to run fragments of them as commands.
REM Write any human-readable (Chinese) notes into the log from Python.
REM ==============================================================
set "VENV_DIR=%ROOT_DIR%.venv"
set "VENV_SOURCE=project .venv (F: not found, fallback)"
if exist "F:\Roaming\Aerie-Yunqi\.venv\Scripts\python.exe" (
    set "VENV_DIR=F:\Roaming\Aerie-Yunqi\.venv"
    set "VENV_SOURCE=F: recommended install (preferred)"
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%ROOT_DIR%requirements.txt"
set "DEP_CHECK=%ROOT_DIR%tools\check_venv_deps.py"
set "ELECTRON_DIR=%ROOT_DIR%electron"
set "ELECTRON_BIN=%ELECTRON_DIR%\node_modules\.bin\electron.cmd"
if not defined AERIE_USER_DATA_DIR set "AERIE_USER_DATA_DIR=F:\Roaming\Aerie-Yunqi\electron-user-data"
set "ENV_LOG_DIR=%ROOT_DIR%logs"
set "ENV_LOG=%ENV_LOG_DIR%\startup-env.log"
if not exist "%ENV_LOG_DIR%" mkdir "%ENV_LOG_DIR%" >nul 2>&1

cd /d "%ROOT_DIR%" || goto :fail_cd

echo ============================================
echo        d8888                  d8b          
echo       d88888                  Y8P          
echo      d88P888                               
echo     d88P 888  .d88b.  888d888 888  .d88b.  
echo    d88P  888 d8P  Y8b 888P"   888 d8P  Y8b 
echo   d88P   888 88888888 888     888 88888888 
echo  d8888888888 Y8b.     888     888 Y8b.     
echo d88P     888  "Y8888  888     888  "Y8888  
echo  Aerie Companion V 0.3.2-beta.0903-A12 - Dev Startup
echo ============================================
echo Root: %ROOT_DIR%
echo Python venv  : %VENV_DIR%
echo Venv source  : %VENV_SOURCE%
echo Python exe   : %PYTHON_EXE%
echo Electron user data: %AERIE_USER_DATA_DIR%
echo Env log      : %ENV_LOG%
echo.
echo Started: %DATE% %TIME%
echo AERIE_SILENT=%AERIE_SILENT%
echo.

REM Leave an audit trail: "which venv actually ran" is answered by
REM logs\startup-env.log without having to re-run anything.
REM Use %TIME% only: %DATE% carries the locale weekday (e.g. Chinese
REM "Zhou Qi") whose GBK bytes would garble the UTF-8 log. The ISO-dated
REM record is written right after this by check_venv_deps.py.
>>"%ENV_LOG%" echo [%TIME%] venv=%VENV_DIR% source="%VENV_SOURCE%" exe="%PYTHON_EXE%"

echo [1/4] Checking Python environment...
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python virtual environment not found.
    echo Missing: %PYTHON_EXE%
    echo.
    echo Please create the venv first, then run this script again.
    goto :fail
)

if not exist "%REQ_FILE%" (
    echo ERROR: requirements.txt not found.
    echo Missing: %REQ_FILE%
    goto :fail
)

REM Dependency self-check is driven by requirements.txt, not a hardcoded
REM module list. The old 8-module list let declared deps go missing while
REM the check still passed (qrcode / trafilatura), so the app started with
REM silently broken capabilities. That failure mode is worse than a crash:
REM nothing errors out, a whole feature just quietly stops working.
if not exist "%DEP_CHECK%" (
    echo ERROR: dependency self-check script not found.
    echo Missing: %DEP_CHECK%
    echo The repo looks incomplete; refusing to start with unverified deps.
    goto :fail
)

echo Checking dependencies against requirements.txt...
"%PYTHON_EXE%" "%DEP_CHECK%" --venv "%VENV_DIR%" --log "%ENV_LOG%"
if errorlevel 1 (
    echo Python dependencies incomplete. Installing from requirements.txt...
    "%PYTHON_EXE%" -m pip install -r "%REQ_FILE%"
    if errorlevel 1 (
        echo ERROR: Failed to install Python dependencies.
        goto :fail
    )
    echo Re-checking dependencies after install...
    "%PYTHON_EXE%" "%DEP_CHECK%" --venv "%VENV_DIR%" --log "%ENV_LOG%"
    if errorlevel 1 (
        echo ERROR: Dependencies still incomplete after install.
        echo See log: %ENV_LOG%
        goto :fail
    )
) else (
    echo Python dependencies OK.
)

echo.
echo [2/4] Checking Electron project...
if not exist "%ELECTRON_DIR%\package.json" (
    echo ERROR: Electron package.json not found.
    echo Missing: %ELECTRON_DIR%\package.json
    goto :fail
)

echo.
echo [3/4] Checking Electron dependencies...
if not exist "%ELECTRON_BIN%" (
    echo Electron dependencies missing. Running npm install...
    cd /d "%ELECTRON_DIR%" || goto :fail_cd
    call npm install
    if errorlevel 1 (
        echo ERROR: npm install failed.
        goto :fail
    )
) else (
    echo Electron dependencies OK.
)

echo.
echo [4/4] Starting Electron...
cd /d "%ELECTRON_DIR%" || goto :fail_cd
call npm start
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo ERROR: Electron exited with code %EXIT_CODE%.
    goto :fail
)

echo.
echo Aerie exited normally.
goto :end

:fail_cd
echo ERROR: Failed to switch working directory.
goto :fail

:fail
echo.
echo Startup failed.
if /i not "%AERIE_SILENT%"=="1" (
    echo Press any key to close this window.
    pause >nul
)
exit /b 1

:end
endlocal
