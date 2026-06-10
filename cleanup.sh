#!/bin/bash
# Cleanup script to prevent "previous run did not finish cleanly" errors

echo "Stopping Ollama processes..."

echo "Stopping proxy processes..."
pkill -f "master_tiered_proxy.py" > /dev/null 2>&1
pkill -f "fallback_proxy.py" > /dev/null 2>&1

echo "Stopping test scripts..."
pkill -f "test_fallback_chain.py" > /dev/null 2>&1
pkill -f "test_google_correct.py" > /dev/null 2>&1
pkill -f "test_google_models.py" > /dev/null 2>&1
pkill -f "test_mistral.py" > /dev/null 2>&1
pkill -f "test_full_flow.py" > /dev/null 2>&1
pkill -f "test_full_flow_v2.py" > /dev/null 2>&1

echo "Stopping JIMI analyzer processes..."
pkill -f "jimi_audit.*\.py" > /dev/null 2>&1
pkill -f "intraday_brief.*\.py" > /dev/null 2>&1
pkill -f "multi_tf_brief.*\.py" > /dev/null 2>&1
pkill -f "scanner.*\.py" > /dev/null 2>&1

echo "Disabling Ollama service to prevent auto-restart..."

echo "Cleanup complete."