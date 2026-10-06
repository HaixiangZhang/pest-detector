@echo off
REM Double-click entry for pest_detector web UI.
REM Runs the PowerShell start script with ExecutionPolicy bypassed for this call only.
REM Usage:  start.bat  [same args as scripts\start.ps1, e.g. -Build -Open -Port 8001]

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo [start.bat] script exited with code %EXITCODE%
)

REM Keep the window open when double-clicked so errors stay visible.
if "%~1"=="" pause
exit /b %EXITCODE%