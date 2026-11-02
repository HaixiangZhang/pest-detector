@echo off
REM ----------------------------------------------------------------------------
REM  pest_detector 启动脚本（Windows）
REM    双击 scripts\start.bat  -> 自检 + 启动 + 自动打开浏览器
REM    带参数透传            -> start.bat -Build -Port 8001
REM  PowerShell 只对本次调用绕过 ExecutionPolicy，不修改系统设置。
REM ----------------------------------------------------------------------------
chcp 65001 >nul

set "EXTRA=%*"
if "%EXTRA%"=="" set "EXTRA=-Open"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %EXTRA%
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo [start.bat] 启动失败，退出码 %EXITCODE%（上方是原因与解决办法）
)

REM 双击运行时保留窗口，避免报错一闪而过。
if not defined PESTDET_NO_PAUSE pause
exit /b %EXITCODE%
