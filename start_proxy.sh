#!/bin/bash
# Load env vars
export $(grep -v '^#' /root/.openclaw/workspace/.env | xargs)
# Start proxy
nohup python3 /root/.openclaw/workspace/master_tiered_proxy.py > /root/.openclaw/workspace/proxy.log 2>&1 &
