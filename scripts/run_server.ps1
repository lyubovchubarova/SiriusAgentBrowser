# Скрипт для запуска сервера агента
# Предварительно запустите start_chrome_debug.ps1

$env:CDP_URL = "http://127.0.0.1:9222"

# Get the project root directory
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = $ProjectRoot

Write-Host "Starting Agent Server..."
Write-Host "Connects to Chrome at: $env:CDP_URL"
Write-Host "API available at: http://127.0.0.1:8000"

$ServerPy = Join-Path $ProjectRoot "src\server.py"

python $ServerPy
