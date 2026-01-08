#!/bin/bash
# FamZoo to YNAB Sync - Shell Wrapper
# This script handles virtual environment activation and runs the sync tool

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Virtual environment path
VENV_DIR="$SCRIPT_DIR/venv"

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment and run the command
source "$VENV_DIR/bin/activate"

# Run the main script with all passed arguments
python3 "$SCRIPT_DIR/main.py" "$@"

# Capture exit code
EXIT_CODE=$?

# Deactivate virtual environment
deactivate 2>/dev/null

exit $EXIT_CODE
