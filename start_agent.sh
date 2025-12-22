#!/bin/bash

# Get the directory of the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"

# 0. Cleanup existing server on port 8000
echo "Checking for existing server on port 8000..."
PID=$(lsof -t -i:8000)
if [ -n "$PID" ]; then
    echo "Killing old server process (PID: $PID)..."
    kill -9 $PID
fi

# 1. Find Chrome
CHROME_EXE=""
if command -v google-chrome &> /dev/null; then
    CHROME_EXE="google-chrome"
elif command -v google-chrome-stable &> /dev/null; then
    CHROME_EXE="google-chrome-stable"
elif command -v chromium &> /dev/null; then
    CHROME_EXE="chromium"
elif command -v chromium-browser &> /dev/null; then
    CHROME_EXE="chromium-browser"
else
    # Check for Playwright Chromium
    PLAYWRIGHT_CHROME=$(find "$HOME/.cache/ms-playwright" -name chrome -type f | head -n 1)
    if [ -n "$PLAYWRIGHT_CHROME" ]; then
        CHROME_EXE="$PLAYWRIGHT_CHROME"
    fi
fi

if [ -z "$CHROME_EXE" ]; then
    echo "Error: Google Chrome or Chromium not found."
    echo "Please install Google Chrome or run 'playwright install chromium'"
    exit 1
fi

# 2. Launch Chrome
PROFILE_DIR="$HOME/.chrome_debug_profile"
EXTENSION_PATH="$PROJECT_ROOT/extension"

echo "=== Step 1: Launching Chrome in Debug Mode ==="
echo "Chrome: $CHROME_EXE"
echo "Profile: $PROFILE_DIR"
echo "Extension: $EXTENSION_PATH"

mkdir -p "$PROFILE_DIR"

# Start Chrome in background
"$CHROME_EXE" \
    --remote-debugging-port=9222 \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --load-extension="$EXTENSION_PATH" \
    --remote-allow-origins=* \
    &

CHROME_PID=$!
echo "Chrome launched (PID: $CHROME_PID)"

# Wait for Chrome to initialize
sleep 3

# 3. Start Server
echo ""
echo "=== Step 2: Starting Agent Server ==="
echo "API available at: http://127.0.0.1:8000"

export CDP_URL="http://127.0.0.1:9222"
export PYTHONPATH="$PROJECT_ROOT"

# Use the virtual environment python
# Check in project root first
PYTHON_EXE="$PROJECT_ROOT/.venv/bin/python"

# Check in parent directory (common pattern)
if [ ! -f "$PYTHON_EXE" ]; then
    PYTHON_EXE="$PROJECT_ROOT/../.venv/bin/python"
fi

# Check in standard venv name
if [ ! -f "$PYTHON_EXE" ]; then
    PYTHON_EXE="$PROJECT_ROOT/venv/bin/python"
fi

if [ ! -f "$PYTHON_EXE" ]; then
    echo "Error: Virtual environment python not found."
    echo "Checked: $PROJECT_ROOT/.venv/bin/python"
    echo "Checked: $PROJECT_ROOT/../.venv/bin/python"
    echo "Checked: $PROJECT_ROOT/venv/bin/python"
    exit 1
fi

"$PYTHON_EXE" "$PROJECT_ROOT/src/server.py"

# Cleanup Chrome when server exits
kill $CHROME_PID
