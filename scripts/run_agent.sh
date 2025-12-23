#!/bin/bash

export CDP_URL="http://127.0.0.1:9222"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
export PYTHONPATH="$PROJECT_ROOT"

echo "Connecting to browser at: $CDP_URL"
echo "Project Root: $PROJECT_ROOT"

python3 "$PROJECT_ROOT/src/main.py"
