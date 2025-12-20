# Master script to start the entire environment (Chrome + Server)

$ScriptsDir = $PSScriptRoot

# 0. Cleanup existing server on port 8000
Write-Host "Checking for existing server on port 8000..."
$ExistingProcess = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($ExistingProcess) {
    $PID_to_Kill = $ExistingProcess.OwningProcess
    Write-Host "Killing old server process (PID: $PID_to_Kill)..." -ForegroundColor Yellow
    try {
        Stop-Process -Id $PID_to_Kill -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "Could not kill process. It might be already gone."
    }
    Start-Sleep -Seconds 1
}

# 1. Start Chrome
Write-Host "=== Step 1: Launching Chrome in Debug Mode ===" -ForegroundColor Cyan
try {
    & "$ScriptsDir\start_chrome_debug.ps1"
} catch {
    Write-Error "Failed to launch Chrome script: $_"
    exit 1
}

# Wait for Chrome to actually start
Write-Host "Waiting for Chrome to initialize..."
Start-Sleep -Seconds 3

# 2. Start Server
Write-Host "`n=== Step 2: Starting Agent Server ===" -ForegroundColor Cyan
Write-Host "Keep this window open! The agent is running here." -ForegroundColor Yellow
Write-Host "You can now open the Side Panel in Chrome to chat." -ForegroundColor Green

try {
    & "$ScriptsDir\run_server.ps1"
} catch {
    Write-Error "Failed to start server: $_"
    exit 1
}
