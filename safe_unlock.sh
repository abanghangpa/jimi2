#!/bin/bash
# safe_unlock.sh - Safely clears stale session locks without killing live handlers

echo "🛡️ Running Liveness-Aware Lock Clearance..."

# Target session lock directory
LOCK_DIR="/root/.openclaw/agents/main/sessions/"

# Find all .lock files
LOCK_FILES=$(find "$LOCK_DIR" -name "*.lock" -type f)

if [ -z "$LOCK_FILES" ]; then
    echo "✅ No lock files found. Session is fluid."
    exit 0
fi

for FILE in $LOCK_FILES; do
    echo "Checking lock: $(basename "$FILE")"
    
    # Extract PID from the JSON lock file
    PID=$(grep -o '"pid": [0-9]*' "$FILE" | grep -o '[0-9]*')
    
    if [ -z "$PID" ]; then
        echo "   ⚠️  Could not find PID in lock file. Removing corrupted lock."
        rm -f "$FILE"
        continue
    fi
    
    # Check if the process is actually running (kill -0 sends no signal but checks existence)
    if kill -0 "$PID" 2>/dev/null; then
        echo "   🚀 PID $PID is LIVE. This is the active session handler. DO NOT TOUCH."
    else
        echo "   💀 PID $PID is DEAD. This is a stale lock from a crashed process."
        rm -f "$FILE"
        echo "   ✅ Stale lock removed."
    fi
done

echo "✨ Cleanup complete. Environment integrity preserved."
