@echo off
REM ============================================================================
REM  双击启动入口（项目根目录）
REM    直接双击 -> 自检 + 启动 Web 服务 + 自动打开浏览器
REM    带参数    -> 透传给 scripts\start.ps1（例如: start.bat -Build -Port 8001）
REM ============================================================================
chcp 65001 >nul
cd /d "%~dp0"

if "%~1"=="" (
    call "%~dp0scripts\start.bat" -Open
) else (
    call "%~dp0scripts\start.bat" %*
)

exit /b %ERRORLEVEL%
