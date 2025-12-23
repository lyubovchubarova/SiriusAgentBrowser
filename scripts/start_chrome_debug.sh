#!/bin/bash

# Script to launch Google Chrome in debug mode

# Detect OS
OS="$(uname)"

CHROME_BIN=""

if [ "$OS" = "Darwin" ]; then
    # macOS
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif [ "$OS" = "Linux" ]; then
    # Linux
    if command -v google-chrome &> /dev/null; then
        CHROME_BIN="google-chrome"
    elif command -v google-chrome-stable &> /dev/null; then
        CHROME_BIN="google-chrome-stable"
    elif command -v chromium &> /dev/null; then
        CHROME_BIN="chromium"
    fi
fi

if [ -z "$CHROME_BIN" ]; then
    echo "Error: Google Chrome not found."
    exit 1
fi

# User profile folder
PROFILE_DIR="$HOME/selenium/chrome_profile"
mkdir -p "$PROFILE_DIR"

# Extension path
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
EXTENSION_PATH="$PROJECT_ROOT/extension"

echo "Launching Chrome from: $CHROME_BIN"
echo "Debug port: 9222"
echo "Profile: $PROFILE_DIR"
echo "Loading extension from: $EXTENSION_PATH"

# Launch Chrome
"$CHROME_BIN" \
  --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  --load-extension="$EXTENSION_PATH" &

echo "Chrome launched. You can now run the agent."
