#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# 0. Cleanup existing server on port 8000
echo "Checking for existing server on port 8000..."
PID=$(lsof -t -i:8000)
if [ -n "$PID" ]; then
    echo "Killing old server process (PID: $PID)..."
    kill -9 "$PID"
    sleep 1
fi

# 1. Start Chrome
echo "=== Step 1: Launching Chrome in Debug Mode ==="
bash "$SCRIPT_DIR/start_chrome_debug.sh"

# Wait for Chrome to initialize
echo "Waiting for Chrome to initialize..."
sleep 2

# 2. Start Server
echo ""
echo "=== Step 2: Starting Agent Server ==="
echo "Keep this window open! The agent is running here."
echo "You can now open the Side Panel in Chrome to chat."

bash "$SCRIPT_DIR/run_server.sh"
