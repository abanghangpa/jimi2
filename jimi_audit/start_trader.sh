#!/bin/bash
cd /root/.openclaw/workspace/jimi_audit
pkill -f 'trader_v2.py' 2>/dev/null
pkill -f 'live/trader.py' 2>/dev/null
sleep 1
nohup python3 live/trader_v2.py > /tmp/trader_v2.log 2>&1 &
echo "Started trader_v2.py PID=$!"
