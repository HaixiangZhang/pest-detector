@echo off
REM ============================================================================
REM  Double-click entry point (project root)
REM    no args  -> self-check + start web server + open browser
REM    with args -> passed through to scripts\start.ps1
REM                 e.g. start.bat -Build -Port 8001
REM  NOTE: keep this file ASCII-only. cmd.exe misreads multi-byte text when the
REM        code page changes mid-script, which breaks the whole batch file.
REM ============================================================================
cd /d "%~dp0"

if "%~1"=="" (
    call "%~dp0app\scripts\start.bat" -Open
) else (
    call "%~dp0app\scripts\start.bat" %*
)

exit /b %ERRORLEVEL%
