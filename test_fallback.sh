#!/bin/bash
set -e

echo "Cleaning up existing processes..."
pkill -f "master_tiered_proxy.py" > /dev/null 2>&1
sleep 2

echo "Starting Ollama..."
OLLAMA_PID=$!
sleep 3

echo "Setting up environment..."
# Export NVIDIA_APIKEY and FREE_PROXY_KEY from .env, but set PROD_API_KEY to empty
export NVIDIA_API_KEY=$(grep NVIDIA_API_KEY /root/.openclaw/workspace/.env | cut -d= -f2)
export FREE_PROXY_KEY=$(grep FREE_PROXY_KEY /root/.openclaw/workspace/.env | cut -d= -f2)
export PROD_API_KEY=""   # invalidate Google key

echo "Starting proxy..."
cd /root/.openclaw/workspace
nohup python3 master_tiered_proxy.py > master_proxy.log 2>&1 &
PROXY_PID=$!
sleep 3

echo "Making test request..."
RESPONSE=$(curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "default", "messages": [{"role": "user", "content": "Say hello in one word"}]}' 2>&1)

echo "Response: $RESPONSE"

echo "Checking proxy log for tier info..."
tail -20 master_proxy.log

echo "Cleaning up..."
kill $OLLAMA_PID 2>/dev/null || true
kill $PROXY_PID 2>/dev/null || true
