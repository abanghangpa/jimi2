#!/usr/bin/env python3
"""
Backtest scanner_executor strategies for $200 → $2500/month target.
Reads strategy_signals.jsonl, simulates trades with TP/SL from signals.
Tests: strategy selection, leverage, risk %, min conviction, vol gate.
"""
import json, time, random, sys, os
from datetime import datetime, timezone
from collections import defaultdict

t0 = time.time()

BASE = '/root/.openclaw/workspace/jimi_audit'
SIGNALS_FILE = os.path.join(BASE, 'data', 'strategy_signals_feb_apr.jsonl')

# Load signals
print("Loading signals...", end=" "); sys.stdout.flush()
signals = []
with open(SIGNALS_FILE) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            sig = json.loads(line)
            signals.append(sig)
        except:
            pass
print(f"{len(signals)} signals loaded in {time.time()-t0:.1f}s")

# Get unique timestamps and strategies
timestamps = sorted(set(s['timestamp'] for s in signals))
strategies = sorted(set(s['strategy'] for s in signals))
print(f"Timestamps: {len(timestamps)} ({timestamps[0]} to {timestamps[-1]})")
print(f"Strategies: {strategies}")

# Count fired signals per strategy
fired_counts = defaultdict(int)
for s in signals:
    if s.get('fired'):
        fired_counts[s['strategy']] += 1
print("\nFired signals per strategy:")
for strat in sorted(fired_counts.keys()):
    print(f"  {strat}: {fired_counts[strat]}")

# Build signal lookup: timestamp -> strategy -> signal
sig_lookup = {}
for s in signals:
    ts = s['timestamp']
    strat = s['strategy']
    if ts not in sig_lookup:
        sig_lookup[ts] = {}
    sig_lookup[ts][strat] = s

# Load price data for outcome checking
print("\nLoading price data...", end=" "); sys.stdout.flush()
price_file = os.path.join(BASE, 'data', 'eth_full_1h.json')
with open(price_file) as f:
    raw = json.load(f)

# Build price lookup by hour
price_by_hour = {}
for candle in raw:
    ts = datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc)
    key = ts.strftime('%Y-%m-%d %H:00:00')
    price_by_hour[key] = {
        'open': float(candle[1]),
        'high': float(candle[2]),
        'low': float(candle[3]),
        'close': float(candle[4]),
    }
print(f"{len(price_by_hour)} hourly candles loaded")

# Also build 15m price data from signals (they have price field)
# Use the signal price as entry, and check against subsequent prices

def get_prices_after(ts_str, hours=24):
    """Get hourly prices after a timestamp."""
    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    prices = []
    for h in range(1, hours+1):
        check_dt = dt + timedelta(hours=h)
        key = check_dt.strftime('%Y-%m-%d %H:00:00')
        if key in price_by_hour:
            prices.append(price_by_hour[key])
    return prices

from datetime import timedelta

def check_outcome(entry, sl, tp, direction, ts_str, hold_hours=12):
    """Check if TP or SL was hit within hold_hours."""
    prices = get_prices_after(ts_str, hold_hours)
    if not prices:
        return 'TIMEOUT', entry, 0
    
    for i, p in enumerate(prices):
        if direction == 'LONG':
            if p['low'] <= sl:
                return 'LOSS', sl, i+1
            if p['high'] >= tp:
                return 'WIN', tp, i+1
        else:  # SHORT
            if p['high'] >= sl:
                return 'LOSS', sl, i+1
            if p['low'] <= tp:
                return 'WIN', tp, i+1
    
    # Timeout - exit at last price
    last_price = prices[-1]['close']
    return 'TIMEOUT', last_price, len(prices)

# === BACKTEST ENGINE ===
def backtest(strategies_to_trade, risk_pct, leverage, min_conviction, 
             vol_gate_min, vol_gate_max, max_positions, tp_multiplier=1.0, 
             sl_multiplier=1.0, init=200, fee=0.001, slip=0.001,
             simulate_wd=False, wd_target=2700, wd_amount=2500, wd_keep=200):
    """Backtest scanner strategies with withdrawal simulation."""
    cap = float(init)
    pk = cap
    max_dd = 0.0
    wins = 0
    losses = 0
    timeouts = 0
    total = 0
    gross_p = 0.0
    gross_l = 0.0
    skipped_vol = 0
    skipped_conv = 0
    skipped_dir = 0
    open_positions = []
    withdrawals = []
    first_target = None
    
    for ts in timestamps:
        # Check open positions for TP/SL hits
        still_open = []
        for pos in open_positions:
            dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            pos_dt = datetime.strptime(pos['opened_at'], '%Y-%m-%d %H:%M:%S')
            hours_open = (dt - pos_dt).total_seconds() / 3600
            
            if hours_open >= pos['hold_hours']:
                # Timeout
                current_price = sig_lookup.get(ts, {}).get(pos['strategy'], {}).get('price', pos['entry'])
                if current_price is None:
                    current_price = pos['entry']
                if pos['direction'] == 'LONG':
                    pnl = (current_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage']
                else:
                    pnl = (pos['entry'] - current_price) / pos['entry'] * pos['size'] * pos['leverage']
                pnl -= pos['size'] * fee * 2
                cap += pnl
                total += 1
                timeouts += 1
                if pnl > 0: wins += 1; gross_p += pnl
                else: losses += 1; gross_l += abs(pnl)
                continue
            
            # Check current price for TP/SL
            current_sig = sig_lookup.get(ts, {}).get(pos['strategy'], {})
            current_price = current_sig.get('price')
            if current_price is None:
                still_open.append(pos)
                continue
            
            hit = False
            if pos['direction'] == 'LONG':
                if current_price <= pos['sl']:
                    exit_price = pos['sl'] * (1 - slip)
                    pnl = (exit_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage']
                    pnl -= pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1
                    if pnl > 0: gross_p += pnl
                    else: gross_l += abs(pnl)
                    hit = True
                elif current_price >= pos['tp']:
                    exit_price = pos['tp'] * (1 - slip)
                    pnl = (exit_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage']
                    pnl -= pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1
                    if pnl > 0: gross_p += pnl
                    else: gross_l += abs(pnl)
                    hit = True
            else:  # SHORT
                if current_price >= pos['sl']:
                    exit_price = pos['sl'] * (1 + slip)
                    pnl = (pos['entry'] - exit_price) / pos['entry'] * pos['size'] * pos['leverage']
                    pnl -= pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1
                    if pnl > 0: gross_p += pnl
                    else: gross_l += abs(pnl)
                    hit = True
                elif current_price <= pos['tp']:
                    exit_price = pos['tp'] * (1 + slip)
                    pnl = (pos['entry'] - exit_price) / pos['entry'] * pos['size'] * pos['leverage']
                    pnl -= pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1
                    if pnl > 0: gross_p += pnl
                    else: gross_l += abs(pnl)
                    hit = True
            
            if not hit:
                still_open.append(pos)
        
        open_positions = still_open
        
        # Check for new signals
        ts_signals = sig_lookup.get(ts, {})
        for strat_name, sig_data in ts_signals.items():
            if strat_name not in strategies_to_trade:
                continue
            if not sig_data.get('fired'):
                continue
            
            # Already have position for this strategy?
            if any(p['strategy'] == strat_name for p in open_positions):
                continue
            
            # Max positions check
            if len(open_positions) >= max_positions:
                continue
            
            direction = sig_data.get('direction')
            if not direction:
                skipped_dir += 1; continue
            
            conviction = sig_data.get('conviction', 0) or 0
            if conviction < min_conviction:
                skipped_conv += 1; continue
            
            vol_ratio = sig_data.get('vol_ratio', 0) or 0
            if vol_ratio < vol_gate_min or (vol_gate_max > 0 and vol_ratio > vol_gate_max):
                skipped_vol += 1; continue
            
            entry = sig_data.get('price', 0)
            sl = sig_data.get('sl', 0)
            tp = sig_data.get('tp1', 0)
            
            if not entry or not sl or not tp:
                continue
            
            # Apply multipliers
            if direction == 'LONG':
                sl_dist = entry - sl
                tp_dist = tp - entry
                sl = entry - sl_dist * sl_multiplier
                tp = entry + tp_dist * tp_multiplier
            else:
                sl_dist = sl - entry
                tp_dist = entry - tp
                sl = entry + sl_dist * sl_multiplier
                tp = entry - tp_dist * tp_multiplier
            
            # Position sizing
            if direction == 'LONG':
                sl_pct = (entry - sl) / entry
            else:
                sl_pct = (sl - entry) / entry
            
            if sl_pct <= 0:
                continue
            
            risk_amt = cap * risk_pct
            size = risk_amt / (sl_pct * leverage)
            
            if size < 1 or cap < 10:
                continue
            
            # Open position
            pos = {
                'strategy': strat_name,
                'direction': direction,
                'entry': entry,
                'sl': sl,
                'tp': tp,
                'size': size,
                'leverage': leverage,
                'hold_hours': 12,
                'opened_at': ts,
                'conviction': conviction,
            }
            open_positions.append(pos)
        
        # Peak/DD tracking
        total_pos_value = cap
        if total_pos_value > pk: pk = total_pos_value
        dd = (pk - cap) / pk * 100 if pk > 0 else 0
        if dd > max_dd: max_dd = dd
        
        # Withdrawal
        if simulate_wd and cap >= wd_target:
            if first_target is None:
                first_target = ts
            profit = cap - wd_keep
            if profit >= wd_amount:
                withdrawals.append({'date': ts, 'amount': wd_amount, 'cap_before': cap})
                cap -= wd_amount
    
    # Close remaining positions at last known price
    for pos in open_positions:
        last_ts = timestamps[-1]
        last_sig = sig_lookup.get(last_ts, {}).get(pos['strategy'], {})
        exit_price = last_sig.get('price', pos['entry'])
        if pos['direction'] == 'LONG':
            pnl = (exit_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage']
        else:
            pnl = (pos['entry'] - exit_price) / pos['entry'] * pos['size'] * pos['leverage']
        pnl -= pos['size'] * fee * 2
        cap += pnl; total += 1; timeouts += 1
        if pnl > 0: wins += 1; gross_p += pnl
        else: losses += 1; gross_l += abs(pnl)
    
    wr = (wins + timeouts) / total * 100 if total > 0 else 0
    pf = gross_p / gross_l if gross_l > 0 else 999
    total_wd = sum(w['amount'] for w in withdrawals)
    
    return {
        'final': cap, 'wr': wr, 'pf': pf, 'dd': max_dd,
        'trades': total, 'wins': wins, 'losses': losses, 'timeouts': timeouts,
        'gross_p': gross_p, 'gross_l': gross_l,
        'skipped_vol': skipped_vol, 'skipped_conv': skipped_conv,
        'withdrawals': withdrawals, 'total_withdrawn': total_wd,
        'first_target': first_target,
    }

# === PARAMETER SWEEP ===
SEEDS = list(range(50))

# Strategy groups
all_strats = [s for s in strategies if fired_counts.get(s, 0) > 0]
top_strats = ['trade_flow', 'funding_arb', 'orderbook_imbalance', 'positioning_fade', 'whale_watch', 'momentum_v2']
flow_strats = ['trade_flow', 'funding_arb', 'orderbook_imbalance']
momentum_strats = ['momentum_v2', 'squeeze_breakout', 'cascade']

configs = [
    # name, strategies, risk, leverage, min_conv, vol_min, vol_max, max_pos, tp_mult, sl_mult
    ("all_strats_risk2_lev10", all_strats, 0.02, 10, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk5_lev10", all_strats, 0.05, 10, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk10_lev10", all_strats, 0.10, 10, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk10_lev15", all_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk10_lev20", all_strats, 0.10, 20, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk15_lev15", all_strats, 0.15, 15, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk15_lev20", all_strats, 0.15, 20, 0.5, 0, 0, 3, 1.0, 1.0),
    ("all_strats_risk20_lev20", all_strats, 0.20, 20, 0.5, 0, 0, 3, 1.0, 1.0),
    # Top strategies only
    ("top_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0),
    ("top_risk15_lev20", top_strats, 0.15, 20, 0.5, 0, 0, 3, 1.0, 1.0),
    ("top_risk20_lev25", top_strats, 0.20, 25, 0.5, 0, 0, 3, 1.0, 1.0),
    # Flow strategies
    ("flow_risk10_lev15", flow_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0),
    ("flow_risk15_lev20", flow_strats, 0.15, 20, 0.5, 0, 0, 3, 1.0, 1.0),
    # Higher conviction filters
    ("top_conv60_risk10_lev15", top_strats, 0.10, 15, 0.6, 0, 0, 3, 1.0, 1.0),
    ("top_conv70_risk10_lev15", top_strats, 0.10, 15, 0.7, 0, 0, 3, 1.0, 1.0),
    ("top_conv60_risk15_lev20", top_strats, 0.15, 20, 0.6, 0, 0, 3, 1.0, 1.0),
    # Vol gate
    ("top_vol10_risk10_lev15", top_strats, 0.10, 15, 0.5, 0.10, 0, 3, 1.0, 1.0),
    ("top_vol15_risk10_lev15", top_strats, 0.10, 15, 0.5, 0.15, 0, 3, 1.0, 1.0),
    ("top_vol20_risk10_lev15", top_strats, 0.10, 15, 0.5, 0.20, 0, 3, 1.0, 1.0),
    # TP/SL multipliers
    ("top_tp1.5_sl1.0_risk10", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.5, 1.0),
    ("top_tp2.0_sl1.5_risk10", top_strats, 0.10, 15, 0.5, 0, 0, 3, 2.0, 1.5),
    ("top_tp1.0_sl0.8_risk10", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 0.8),
    ("top_tp0.8_sl0.5_risk10", top_strats, 0.10, 15, 0.5, 0, 0, 3, 0.8, 0.5),
    # Max positions
    ("top_max2_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 2, 1.0, 1.0),
    ("top_max5_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 5, 1.0, 1.0),
    # Aggressive combos
    ("yolo_top_risk20_lev25", top_strats, 0.20, 25, 0.5, 0, 0, 3, 1.0, 1.0),
    ("yolo_top_risk25_lev30", top_strats, 0.25, 30, 0.5, 0, 0, 3, 1.0, 1.0),
    ("yolo_all_risk20_lev25", all_strats, 0.20, 25, 0.5, 0, 0, 5, 1.0, 1.0),
]

print(f"\n{'='*120}")
print(f"Running {len(configs)} configs")
print(f"{'='*120}\n")

results = []
for ci, (name, strats, risk, lev, min_conv, vol_min, vol_max, max_pos, tp_m, sl_m) in enumerate(configs):
    r = backtest(strats, risk, lev, min_conv, vol_min, vol_max, max_pos, tp_m, sl_m,
                 simulate_wd=True, wd_target=2700, wd_amount=2500, wd_keep=200)
    
    results.append({
        'name': name, 'strats': strats, 'risk': risk, 'lev': lev,
        'min_conv': min_conv, 'vol_min': vol_min, 'vol_max': vol_max,
        'max_pos': max_pos, 'tp_m': tp_m, 'sl_m': sl_m,
        **r
    })
    
    print(f"[{ci+1:2d}/{len(configs)}] {name:<40} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} DD={r['dd']:5.1f}% Tr={r['trades']:4d} W={r['wins']:3d} L={r['losses']:3d} T={r['timeouts']:3d} WD=${r['total_withdrawn']:>8,.0f} Cap=${r['final']:>10,.2f}")

# Sort by total_withdrawn
results.sort(key=lambda x: x['total_withdrawn'], reverse=True)

print(f"\n{'='*120}")
print("TOP 10 BY TOTAL WITHDRAWN")
print(f"{'='*120}")
print(f"{'Config':<40} {'WR%':>6} {'PF':>6} {'DD%':>6} {'Tr':>5} {'W':>4} {'L':>4} {'T':>4} {'WD$':>10} {'Cap$':>12} {'1stWD':>20}")
print("-"*120)
for r in results[:10]:
    first = r['first_target'][:16] if r['first_target'] else 'N/A'
    print(f"{r['name']:<40} {r['wr']:>5.1f}% {r['pf']:>5.2f} {r['dd']:>5.1f}% {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} {r['timeouts']:>4} {r['total_withdrawn']:>9,.0f} {r['final']:>11,.2f} {first:>20}")

print(f"\n{'='*120}")
print("BOTTOM 5")
print(f"{'='*120}")
for r in results[-5:]:
    first = r['first_target'][:16] if r['first_target'] else 'N/A'
    print(f"{r['name']:<40} {r['wr']:>5.1f}% {r['pf']:>5.2f} {r['dd']:>5.1f}% {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} {r['timeouts']:>4} {r['total_withdrawn']:>9,.0f} {r['final']:>11,.2f} {first:>20}")

# Save
output = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': f'{len(signals)} signals, {len(timestamps)} timestamps, Feb-Apr 2026',
    'strategies': strategies,
    'fired_counts': dict(fired_counts),
    'results': results
}
with open(os.path.join(BASE, 'data', 'scanner_optimization.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s. Saved to scanner_optimization.json")
