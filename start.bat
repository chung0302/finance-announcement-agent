@echo off
rem Double-click launcher: starts the Streamlit app with the execution policy bypassed.
rem The .ps1 alone is often blocked by the default Windows execution policy.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo.
    echo Startup failed. Read the message above, then press any key to close.
    pause >nul
)
