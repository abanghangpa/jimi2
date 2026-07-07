import csv, json, numpy as np
from datetime import datetime

BASE = "/root/.openclaw/workspace/jimi_audit"

# Load ETH bars
bars = {}
with open(f"{BASE}/eth_15m_merged.csv") as f:
    for row in csv.DictReader(f):
        bars[row["Open time"]] = {
            'high': float(row['High']),
            'low': float(row['Low']),
            'close': float(row['Close']),
            'open': float(row['Open']),
        }

# Load trades
with open(f"{BASE}/reports/whale_pair_analysis.json") as f:
    data = json.load(f)
trades = data['results']['liquidity_grab']['trades']

sorted_keys = sorted(bars.keys())

print("TRADE DEBUG — Sweep Magnitude")
print("="*80)
for t in trades:
    entry_time = t['time']
    direction = t['dir']
    entry_price = t['entry']
    
    if entry_time not in bars:
        print(f"  {entry_time} NOT IN DATA")
        continue
    
    idx = sorted_keys.index(entry_time)
    entry_bar = bars[entry_time]
    
    # Try different lookbacks
    for lb in [10, 20, 48]:
        if idx < lb:
            continue
        window = [bars[sorted_keys[i]] for i in range(idx-lb, idx)]
        swing_high = max(b['high'] for b in window)
        swing_low = min(b['low'] for b in window)
        
        # ATR
        trs = []
        for i in range(1, len(window)):
            tr = max(window[i]['high'] - window[i]['low'],
                     abs(window[i]['high'] - window[i-1]['close']),
                     abs(window[i]['low'] - window[i-1]['close']))
            trs.append(tr)
        atr = np.mean(trs) if trs else 0
        
        if direction == 'SHORT':
            sweep_raw = entry_bar['high'] - swing_high
        else:
            sweep_raw = swing_low - entry_bar['low']
        
        sweep_atr = sweep_raw / atr if atr > 0 else 0
        
        if lb == 20:
            marker = " <--" if sweep_atr > 0 else ""
            print(f"  {entry_time} {direction:5s} entry={entry_price:.2f} outcome={t['outcome']} pnl={t['pnl']:+.4f}")
            print(f"    LB={lb}: SH={swing_high:.2f} SL={swing_low:.2f} entry_H={entry_bar['high']:.2f} entry_L={entry_bar['low']:.2f}")
            print(f"    sweep_raw={sweep_raw:.2f} ATR={atr:.2f} sweep_atr={sweep_atr:.4f}{marker}")
    
    print()

# Summary
print("\nSWEEP DISTRIBUTION (LB=20):")
print("="*80)
positive = 0
negative = 0
for t in trades:
    entry_time = t['time']
    direction = t['dir']
    if entry_time not in bars:
        continue
    idx = sorted_keys.index(entry_time)
    if idx < 20:
        continue
    window = [bars[sorted_keys[i]] for i in range(idx-20, idx)]
    swing_high = max(b['high'] for b in window)
    swing_low = min(b['low'] for b in window)
    entry_bar = bars[entry_time]
    trs = []
    for i in range(1, len(window)):
        tr = max(window[i]['high'] - window[i]['low'],
                 abs(window[i]['high'] - window[i-1]['close']),
                 abs(window[i]['low'] - window[i-1]['close']))
        trs.append(tr)
    atr = np.mean(trs) if trs else 0
    if direction == 'SHORT':
        sweep_raw = entry_bar['high'] - swing_high
    else:
        sweep_raw = swing_low - entry_bar['low']
    sweep_atr = sweep_raw / atr if atr > 0 else 0
    
    if sweep_atr > 0:
        positive += 1
    else:
        negative += 1

print(f"  Positive sweep (poked past level): {positive}")
print(f"  Negative sweep (didn't reach level): {negative}")
print(f"  This means {negative} trades did NOT sweep past the 20-bar swing level")
print(f"  The scanner uses different logic to detect liquidity grabs (order book data)")
