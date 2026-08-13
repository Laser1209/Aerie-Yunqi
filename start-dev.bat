@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
REM Prefer the F: drive environment to avoid filling up C:; F: is the recommended install location
REM Otherwise use the project .venv directory
set "VENV_DIR=%ROOT_DIR%.venv"
if exist "F:\Roaming\Aerie-Yunqi\.venv\Scripts\python.exe" set "VENV_DIR=F:\Roaming\Aerie-Yunqi\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%ROOT_DIR%requirements.txt"
set "ELECTRON_DIR=%ROOT_DIR%electron"
set "ELECTRON_BIN=%ELECTRON_DIR%\node_modules\.bin\electron.cmd"
if not defined AERIE_USER_DATA_DIR set "AERIE_USER_DATA_DIR=F:\Roaming\Aerie-Yunqi\electron-user-data"

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
echo  Aerie Yunqi V 0.3.0-Beta.1 - Dev Startup
echo ============================================
echo Root: %ROOT_DIR%
echo Electron user data: %AERIE_USER_DATA_DIR%
echo.
echo Started: %DATE% %TIME%
echo AERIE_SILENT=%AERIE_SILENT%
echo.

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

REM Use find_spec instead of import: some packages (e.g. aiohttp) can hang
REM on first import under certain Windows/antivirus conditions, which made
REM the launcher appear stuck at step 1.
echo Checking core Python packages...
"%PYTHON_EXE%" -c "import importlib.util,sys; mods=['fastapi','uvicorn','aiohttp','websockets','psutil','yaml','dotenv','loguru']; missing=[m for m in mods if importlib.util.find_spec(m) is None]; print('MISSING:'+','.join(missing) if missing else 'OK'); sys.exit(1 if missing else 0)"
if errorlevel 1 (
    echo Python dependencies missing. Installing from requirements.txt...
    "%PYTHON_EXE%" -m pip install -r "%REQ_FILE%"
    if errorlevel 1 (
        echo ERROR: Failed to install Python dependencies.
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

