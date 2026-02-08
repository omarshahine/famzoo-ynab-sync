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

# Log timestamp for scheduled runs
echo ""
echo "========================================"
echo "FamZoo Sync: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# Run the main script with all passed arguments, capturing output
# NO_COLOR prevents Click from emitting ANSI escape codes when piped
OUTPUT=$(NO_COLOR=1 python3 "$SCRIPT_DIR/main.py" "$@" 2>&1)
EXIT_CODE=$?

# Print output to log as usual
echo "$OUTPUT"

# Send notification via macOS Shortcuts (if installed)
SHORTCUT_NAME="FamZoo Notification"
if shortcuts list 2>/dev/null | grep -q "^${SHORTCUT_NAME}$"; then
    if [ "$EXIT_CODE" -eq 0 ]; then
        # Extract the result message from output
        CREATED=$(echo "$OUTPUT" | grep -o 'Created [0-9]* new transactions' || true)
        DUPES=$(echo "$OUTPUT" | grep -o 'Skipped [0-9]* duplicate transactions' || true)
        if [ -n "$CREATED" ]; then
            NOTIFY_MSG="FamZoo Sync: $CREATED"
            [ -n "$DUPES" ] && NOTIFY_MSG="$NOTIFY_MSG, $DUPES"
        elif echo "$OUTPUT" | grep -q 'No new transactions to sync'; then
            NOTIFY_MSG="FamZoo Sync: No new transactions"
        elif echo "$OUTPUT" | grep -q 'No transactions found'; then
            NOTIFY_MSG="FamZoo Sync: No transactions found"
        else
            NOTIFY_MSG="FamZoo Sync: Completed successfully"
        fi
    else
        # Extract error message
        ERROR_MSG=$(echo "$OUTPUT" | grep '\[ERROR\]' | tail -1 | sed 's/\[ERROR\] //')
        NOTIFY_MSG="FamZoo Sync Error: ${ERROR_MSG:-Sync failed with exit code $EXIT_CODE}"
    fi

    echo "$NOTIFY_MSG" | shortcuts run "$SHORTCUT_NAME" 2>/dev/null || true
else
    echo "WARNING: macOS Shortcut '$SHORTCUT_NAME' not installed."
    echo "Install it by running: open \"$SCRIPT_DIR/FamZoo Notification.shortcut\""
fi

# Deactivate virtual environment
deactivate 2>/dev/null

exit $EXIT_CODE
