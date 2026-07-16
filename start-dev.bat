@echo off
chcp 65001 >nul
echo ============================================
echo  Aerie · 云栖 v9.0 — 开发启动脚本
echo ============================================
echo.

cd /d "%~dp0"

:: Check Python dependencies
echo [1/3] 检查 Python 依赖...
.venv\Scripts\python.exe -c "import fastapi, uvicorn, aiohttp, websockets, psutil, yaml, dotenv, loguru" 2>nul
if %errorlevel% neq 0 (
    echo 正在安装缺失依赖...
    .venv\Scripts\pip.exe install -r requirements.txt --quiet
)

:: Kill any leftover Python processes
echo [2/3] 清理旧进程...
taskkill /f /im python.exe 2>nul >nul
taskkill /f /im pythonw.exe 2>nul >nul
timeout /t 1 /nobreak >nul

:: Start Electron (which auto-starts Python backend)
echo [3/3] 启动 Electron...
cd electron
call npm start

pause
