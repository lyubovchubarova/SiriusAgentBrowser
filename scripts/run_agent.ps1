# Script to run the agent connecting to Chrome
# Run start_chrome_debug.ps1 first

$env:CDP_URL = "http://127.0.0.1:9222"

# Get the project root directory (parent of the scripts directory)
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Set PYTHONPATH to the project root so imports work
$env:PYTHONPATH = $ProjectRoot

Write-Host "Connecting to browser at: $env:CDP_URL"
Write-Host "Project Root: $ProjectRoot"

# Construct absolute path to main.py
$MainPy = Join-Path $ProjectRoot "src\main.py"

python $MainPy
