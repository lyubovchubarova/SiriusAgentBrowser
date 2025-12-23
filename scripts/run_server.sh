#!/bin/bash

export CDP_URL="http://127.0.0.1:9222"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
export PYTHONPATH="$PROJECT_ROOT"

echo "Starting Agent Server..."
echo "Connects to Chrome at: $CDP_URL"
echo "API available at: http://127.0.0.1:8000"

python3 "$PROJECT_ROOT/src/server.py"
