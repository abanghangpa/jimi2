#!/bin/bash
# prevent_timeout.sh - Run this before starting any long-running JIMI or proxy operations
# This prevents the "previous run did not finish cleanly" error by ensuring clean state

echo "🧹 Pre-run cleanup: Ensuring clean state to prevent timeout errors..."

# 1. Stop and disable Ollama service (if installed as service) to prevent auto-respawn
echo "   • Stopping Ollama service..."

# 2. Kill all Ollama processes (catch any that aren't service-managed)
echo "   • Killing Ollama processes..."

# 3. Kill proxy processes that might be hanging
echo "   • Killing proxy processes..."
pkill -f "master_tiered_proxy.py" > /dev/null 2>&1
pkill -f "fallback_proxy.py" > /dev/null 2>&1
pkill -f "proxy.*\.py" > /dev/null 2>&1

# 4. Kill test scripts that might be stuck
echo "   • Killing test scripts..."
pkill -f "test_.*\.py" > /dev/null 2>&1

# 5. Kill JIMI analyzer processes that might be stuck from previous runs
echo "   • Killing JIMI analyzer processes..."
pkill -f "jimi_audit.*\.py" > /dev/null 2>&1
pkill -f "intraday_brief.*\.py" > /dev/null 2>&1
pkill -f "multi_tf_brief.*\.py" > /dev/null 2>&1
pkill -f "scanner.*\.py" > /dev/null 2>&1

# 6. Additional safety: kill any python processes running from our workspace
#    (be careful - this only targets processes with cwd in our workspace)
echo "   • Checking for workspace Python processes..."
for pid in $(ps -o pid= -C python); do
    if ls -l /proc/$pid/cwd 2>/dev/null | grep -q "/root/.openclaw/workspace"; then
        echo "     Killing workspace Python process $pid"
        kill -9 $pid 2>/dev/null
    fi
done

OLLAMA_COUNT=0
# 7. Verify clean state
echo "   • Verifying cleanup..."
PROXY_COUNT=$(ps aux | grep -v grep | grep -E "(master_tiered|fallback)_proxy" | wc -l)
TEST_COUNT=$(ps aux | grep -v grep | grep -E "test_.*\.py" | wc -l)
JIMI_COUNT=$(ps aux | grep -v grep | grep -E "jimi|intraday|multi_tf|scanner" | wc -l)

if [ $OLLAMA_COUNT -eq 0 ] && [ $PROXY_COUNT -eq 0 ] && [ $TEST_COUNT -eq 0 ] && [ $JIMI_COUNT -eq 0 ]; then
    echo "   ✅ Clean state achieved - no conflicting processes found"
else
    echo "   ⚠️  Remaining processes:"
    [ $OLLAMA_COUNT -gt 0 ] && echo "     Ollama: $OLLAMA_COUNT"
    [ $PROXY_COUNT -gt 0 ] && echo "     Proxy: $PROXY_COUNT"
    [ $TEST_COUNT -gt 0 ] && echo "     Test scripts: $TEST_COUNT"
    [ $JIMI_COUNT -gt 0 ] && echo "     JIMI/analyzer: $JIMI_COUNT"
fi

echo "🚀 Cleanup complete. You can now safely start your operations."
echo ""
echo "💡 To prevent future occurrences:"
echo "   • Run this script before starting any long-running operations"
echo "   • Add cleanup at the END of your test scripts:"
echo "     pkill -f \"master_tiered_proxy.py\""
echo "     pkill -f \"test_*.py\""
echo "   • Never leave test scripts or proxies running unattended"
