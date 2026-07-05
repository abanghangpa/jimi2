#!/bin/bash
cd /root/.openclaw/workspace/jimi_audit
pkill -9 -f 'trader_v2.py' 2>/dev/null
pkill -9 -f 'trader_v3.py' 2>/dev/null
pkill -9 -f 'live/trader.py' 2>/dev/null
sleep 1

# Upload handled separately, just reset and start
python3 -c "
import json
state = {
    'capital': 200.0, 'peak_capital': 200.0, 'positions': [], 'closed_trades': [],
    'total_pnl': 0, 'total_fees': 0, 'trades_count': 0, 'wins': 0, 'losses': 0,
    'withdrawals': [], 'total_withdrawn': 0, 'dd_cooldown_until': None,
    'dd_triggered_count': 0, 'current_strategy': 'combined_bb_mom6',
    'last_signal_check': None, 'vol_gate_skips': 0, 'vol_gate_active': True,
}
with open('live/data/state.json', 'w') as f:
    json.dump(state, f, indent=2)
print('State reset: capital=200, strategy=combined_bb_mom6')
"
echo '[]' > live/data/trades.json

nohup python3 live/trader_v3.py > /tmp/trader_v3.log 2>&1 &
echo "Started PID=$!"
