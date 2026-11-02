@echo off
REM ----------------------------------------------------------------------------
REM  pest_detector launcher (Windows)
REM    double-click        -> self-check + start server + open browser
REM    with args           -> start.bat -Build -Port 8001
REM  PowerShell runs with -ExecutionPolicy Bypass for this call only;
REM  system settings are NOT modified.
REM  NOTE: keep this file ASCII-only. Do not switch code page mid-script.
REM ----------------------------------------------------------------------------
setlocal

set "EXTRA=%*"
if "%EXTRA%"=="" set "EXTRA=-Open"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %EXTRA%
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [start.bat] Failed with exit code %EXITCODE% ^(see messages above^)
)

REM Keep the window open when double-clicked, so errors do not flash away.
if not defined PESTDET_NO_PAUSE pause
exit /b %EXITCODE%
