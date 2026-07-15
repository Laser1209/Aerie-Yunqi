@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo   OpenCloud Companion 一键启动
echo ========================================
echo.

REM ===== 1. 启动 NapCatQQ（快速登录伊塔 3998874040）=====
echo [1/2] 正在启动 NapCatQQ (伊塔 3998874040)...

REM 自动检测 QQ 安装路径
for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v "UninstallString" 2^>nul') do (
    set "RetString=%%~b"
)
if not defined RetString (
    echo [错误] 未检测到 QQ 安装，请确认 QQ 已安装
    pause
    exit /b 1
)
for %%a in ("%RetString%") do set "QQPath=%%~dpaQQ.exe"

if not exist "%QQPath%" (
    echo [错误] QQ.exe 未找到: %QQPath%
    pause
    exit /b 1
)

set "NAPCAT_PATCH_PACKAGE=%cd%\NapCat\NapCat.Shell\qqnt.json"
set "NAPCAT_LOAD_PATH=%cd%\NapCat\NapCat.Shell\loadNapCat.js"
set "NAPCAT_INJECT_PATH=%cd%\NapCat\NapCat.Shell\NapCatWinBootHook.dll"
set "NAPCAT_LAUNCHER_PATH=%cd%\NapCat\NapCat.Shell\NapCatWinBootMain.exe"
set "NAPCAT_MAIN_PATH=%cd%\NapCat\NapCat.Shell\napcat.mjs"

REM 写入 loader
set "NAPCAT_MAIN_PATH=%NAPCAT_MAIN_PATH:\=/%"
echo (async () =^> {await import("file:///%NAPCAT_MAIN_PATH%")})() > "%NAPCAT_LOAD_PATH%"

REM 启动 NapCat（-q 快速登录伊塔）
start "NapCat-伊塔" /MIN "%NAPCAT_LAUNCHER_PATH%" "%QQPath%" "%NAPCAT_INJECT_PATH%" -q 3998874040

REM 等待 NapCat 初始化
echo 等待 NapCat 初始化 (5秒)...
timeout /t 5 /nobreak >nul

REM ===== 2. 启动 AI Companion（后台运行，不依赖此窗口）=====
echo.
echo [2/2] 正在启动 AI Companion（后台）...
start "OpenCloud-Companion" /MIN python "%cd%\OpenCloud_Companion\main.py"

echo.
echo ========================================
echo   全部启动完成！现在可以关闭此窗口了
echo   - NapCatQQ: 伊塔 (3998874040)
echo   - AI Companion: 后台运行中
echo   手机发消息给伊塔即可测试～
echo ========================================
echo.
echo 此窗口将于 3 秒后自动关闭...
timeout /t 3 /nobreak >nul
exit
