# Script to launch Google Chrome in debug mode
# This allows the agent to connect to this window and control it.

$ChromePaths = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$ChromeExe = $null
foreach ($path in $ChromePaths) {
    if (Test-Path $path) {
        $ChromeExe = $path
        break
    }
}

if (-not $ChromeExe) {
    Write-Error "Google Chrome not found in standard locations."
    exit 1
}

# User profile folder (to avoid interfering with the main profile)
$ProfileDir = "C:\selenium\chrome_profile"
if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
}

Write-Host "Launching Chrome from: $ChromeExe"
Write-Host "Debug port: 9222"
Write-Host "Profile: $ProfileDir"

# Launch process
Start-Process -FilePath $ChromeExe -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=`"$ProfileDir`"", "--no-first-run", "--no-default-browser-check"

Write-Host "Chrome launched. You can now run the agent."
