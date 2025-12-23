@echo off
TITLE Sirius Agent Launcher
echo Starting Sirius Agent...
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\start_all.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred. Please check the output above.
    pauses
)