#!/usr/bin/env python3
"""
Backtest scanner strategies using v3 signals (June 27 - July 5).
Only processes fired signals for efficiency.
"""
import json, time, sys, os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

t0 = time.time()

BASE = '/root/.openclaw/workspace/jimi_audit'
SIGNALS_FILE = os.path.join(BASE, 'data', 'strategy_signals_v3.jsonl')

# Load only fired signals
print("Loading fired signals...", end=" "); sys.stdout.flush()
fired = []
with open(SIGNALS_FILE) as f:
    for line in f:
        line = line.strip()
        if not line or '"fired": true' not in line:
            continue
        try:
            sig = json.loads(line)
            if sig.get('fired'):
                fired.append(sig)
        except:
            pass
print(f"{len(fired)} fired signals in {time.time()-t0:.1f}s")

# Stats
strat_counts = defaultdict(int)
strat_dirs = defaultdict(lambda: {'LONG': 0, 'SHORT': 0})
for s in fired:
    strat_counts[s['strategy']] += 1
    d = s.get('direction')
    if d and d in ('LONG', 'SHORT'):
        strat_dirs[s['strategy']][d] += 1

print(f"\nFired signals per strategy:")
for strat in sorted(strat_counts.keys()):
    d = strat_dirs[strat]
    print(f"  {strat}: {strat_counts[strat]} (L:{d['LONG']} S:{d['SHORT']})")

# Build price lookup from signal prices
# Group by timestamp
ts_groups = defaultdict(list)
for s in fired:
    ts_groups[s['timestamp']].append(s)

timestamps = sorted(ts_groups.keys())
print(f"\nTimestamps with signals: {len(timestamps)} ({timestamps[0]} to {timestamps[-1]})")

# Load hourly price data for outcome checking
print("Loading price data...", end=" "); sys.stdout.flush()
with open(os.path.join(BASE, 'data', 'eth_full_1h.json')) as f:
    raw = json.load(f)

price_by_hour = {}
for candle in raw:
    ts = datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc)
    key = ts.strftime('%Y-%m-%d %H:00:00')
    price_by_hour[key] = {
        'high': float(candle[2]),
        'low': float(candle[3]),
        'close': float(candle[4]),
    }
print(f"{len(price_by_hour)} hourly candles")

# Build sorted price keys for lookups
sorted_price_keys = sorted(price_by_hour.keys())

def get_price_at_or_after(ts_str):
    """Get the first price at or after a timestamp."""
    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    for h in range(24):
        check = (dt + timedelta(hours=h)).strftime('%Y-%m-%d %H:00:00')
        if check in price_by_hour:
            return price_by_hour[check], h
    return None, -1

# === BACKTEST ENGINE ===
def backtest(strategies, risk_pct, leverage, min_conviction, vol_min, vol_max,
             max_positions, tp_mult, sl_mult, hold_hours, init=200, fee=0.001,
             simulate_wd=False, wd_target=2700, wd_amount=2500, wd_keep=200):
    cap = float(init)
    pk = cap
    max_dd = 0.0
    wins = 0; losses = 0; timeouts = 0; total = 0
    gross_p = 0.0; gross_l = 0.0
    skipped = 0
    open_positions = []
    withdrawals = []
    first_target = None
    
    for ts in timestamps:
        signals_at_ts = ts_groups[ts]
        
        # Check open positions for TP/SL/timeouts
        still_open = []
        for pos in open_positions:
            # Check how long position has been open
            pos_dt = datetime.strptime(pos['opened_at'][:19], '%Y-%m-%d %H:%M:%S')
            now_dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
            hours = (now_dt - pos_dt).total_seconds() / 3600
            
            # Get current price from signals
            current_price = None
            for s in signals_at_ts:
                if s['strategy'] == pos['strategy'] and s.get('price'):
                    current_price = s['price']
                    break
            
            if current_price is None:
                still_open.append(pos)
                continue
            
            # Check TP/SL
            hit = False
            if pos['direction'] == 'LONG':
                if current_price <= pos['sl']:
                    exit_p = pos['sl'] * (1 - 0.001)
                    pnl = (exit_p - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1; gross_l += abs(pnl) if pnl < 0 else 0
                    hit = True
                elif current_price >= pos['tp']:
                    exit_p = pos['tp'] * (1 - 0.001)
                    pnl = (exit_p - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1; gross_p += pnl if pnl > 0 else 0
                    hit = True
            else:
                if current_price >= pos['sl']:
                    exit_p = pos['sl'] * (1 + 0.001)
                    pnl = (pos['entry'] - exit_p) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1; gross_l += abs(pnl) if pnl < 0 else 0
                    hit = True
                elif current_price <= pos['tp']:
                    exit_p = pos['tp'] * (1 + 0.001)
                    pnl = (pos['entry'] - exit_p) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1; gross_p += pnl if pnl > 0 else 0
                    hit = True
            
            # Timeout
            if not hit and hours >= hold_hours:
                pnl = (current_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                if pos['direction'] == 'SHORT':
                    pnl = (pos['entry'] - current_price) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                cap += pnl; total += 1; timeouts += 1
                if pnl > 0: wins += 1; gross_p += pnl
                else: losses += 1; gross_l += abs(pnl)
                hit = True
            
            if not hit:
                still_open.append(pos)
        
        open_positions = still_open
        
        # Process new signals
        for sig in signals_at_ts:
            strat = sig['strategy']
            if strat not in strategies:
                continue
            
            # Skip if already have position for this strategy
            if any(p['strategy'] == strat for p in open_positions):
                continue
            
            if len(open_positions) >= max_positions:
                continue
            
            direction = sig.get('direction')
            if not direction:
                skipped += 1; continue
            
            conviction = sig.get('conviction', 0) or 0
            if conviction < min_conviction:
                skipped += 1; continue
            
            vol_ratio = sig.get('vol_ratio', 0) or 0
            if vol_ratio < vol_min or (vol_max > 0 and vol_ratio > vol_max):
                skipped += 1; continue
            
            entry = sig.get('price', 0)
            sl = sig.get('sl', 0)
            tp = sig.get('tp1', 0)
            
            if not entry or not sl or not tp:
                continue
            
            # Apply TP/SL multipliers
            if direction == 'LONG':
                sl_dist = entry - sl
                tp_dist = tp - entry
                sl = entry - sl_dist * sl_mult
                tp = entry + tp_dist * tp_mult
            else:
                sl_dist = sl - entry
                tp_dist = entry - tp
                sl = entry + sl_dist * sl_mult
                tp = entry - tp_dist * tp_mult
            
            # Position sizing
            if direction == 'LONG':
                sl_pct = (entry - sl) / entry
            else:
                sl_pct = (sl - entry) / entry
            
            if sl_pct <= 0:
                continue
            
            size = (cap * risk_pct) / (sl_pct * leverage)
            if size < 1 or cap < 10:
                continue
            
            open_positions.append({
                'strategy': strat, 'direction': direction,
                'entry': entry, 'sl': sl, 'tp': tp,
                'size': size, 'leverage': leverage,
                'opened_at': ts, 'hold_hours': hold_hours,
            })
        
        # DD tracking
        if cap > pk: pk = cap
        dd = (pk - cap) / pk * 100 if pk > 0 else 0
        if dd > max_dd: max_dd = dd
        
        # Withdrawal
        if simulate_wd and cap >= wd_target:
            if first_target is None: first_target = ts
            if cap - wd_keep >= wd_amount:
                withdrawals.append({'date': ts, 'amount': wd_amount, 'cap_before': cap})
                cap -= wd_amount
    
    # Close remaining
    for pos in open_positions:
        last_price = fired[-1].get('price', pos['entry'])
        if pos['direction'] == 'LONG':
            pnl = (last_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
        else:
            pnl = (pos['entry'] - last_price) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
        cap += pnl; total += 1; timeouts += 1
        if pnl > 0: wins += 1; gross_p += pnl
        else: losses += 1; gross_l += abs(pnl)
    
    wr = wins / total * 100 if total > 0 else 0
    pf = gross_p / gross_l if gross_l > 0 else 999
    total_wd = sum(w['amount'] for w in withdrawals)
    
    return {
        'final': cap, 'wr': wr, 'pf': pf, 'dd': max_dd,
        'trades': total, 'wins': wins, 'losses': losses, 'timeouts': timeouts,
        'gross_p': gross_p, 'gross_l': gross_l, 'skipped': skipped,
        'withdrawals': withdrawals, 'total_withdrawn': total_wd,
        'first_target': first_target,
    }

# === TEST MATRIX ===
all_strats = list(strat_counts.keys())
# Strategies that actually fire frequently
active_strats = [s for s in all_strats if strat_counts[s] >= 100]
# Top performers from memory
top_strats = ['trade_flow', 'funding_arb', 'orderbook_imbalance', 'positioning_fade', 'whale_watch', 'momentum_v2', 'taker_flow', 'power_of_3']
# Filter to those that actually exist
top_strats = [s for s in top_strats if s in strat_counts]

configs = [
    # name, strategies, risk, leverage, min_conv, vol_min, vol_max, max_pos, tp_mult, sl_mult, hold_hours
    ("all_risk2_lev10", all_strats, 0.02, 10, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("all_risk5_lev10", all_strats, 0.05, 10, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("all_risk10_lev10", all_strats, 0.10, 10, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("all_risk10_lev15", all_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("all_risk10_lev20", all_strats, 0.10, 20, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("all_risk15_lev20", all_strats, 0.15, 20, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("all_risk20_lev25", all_strats, 0.20, 25, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    # Active strategies only
    ("active_risk10_lev15", active_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("active_risk15_lev20", active_strats, 0.15, 20, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("active_risk20_lev25", active_strats, 0.20, 25, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    # Top strategies
    ("top_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("top_risk15_lev20", top_strats, 0.15, 20, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    ("top_risk20_lev25", top_strats, 0.20, 25, 0.5, 0, 0, 3, 1.0, 1.0, 12),
    # Higher conviction
    ("top_conv60_risk10_lev15", top_strats, 0.10, 15, 0.6, 0, 0, 3, 1.0, 1.0, 12),
    ("top_conv70_risk10_lev15", top_strats, 0.10, 15, 0.7, 0, 0, 3, 1.0, 1.0, 12),
    # TP/SL multipliers
    ("top_tp1.5_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.5, 1.0, 12),
    ("top_tp2.0_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 2.0, 1.0, 12),
    ("top_sl0.5_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 0.5, 12),
    ("top_sl0.8_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 0.8, 12),
    # Hold time
    ("top_hold4_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0, 4),
    ("top_hold8_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0, 8),
    ("top_hold24_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 3, 1.0, 1.0, 24),
    # Max positions
    ("top_max2_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 2, 1.0, 1.0, 12),
    ("top_max5_risk10_lev15", top_strats, 0.10, 15, 0.5, 0, 0, 5, 1.0, 1.0, 12),
    # Vol gate
    ("top_vol10_risk10_lev15", top_strats, 0.10, 15, 0.5, 0.10, 0, 3, 1.0, 1.0, 12),
    ("top_vol15_risk10_lev15", top_strats, 0.10, 15, 0.5, 0.15, 0, 3, 1.0, 1.0, 12),
    # Aggressive
    ("yolo_risk25_lev30", top_strats, 0.25, 30, 0.5, 0, 0, 5, 1.0, 1.0, 12),
    ("yolo_risk30_lev30", top_strats, 0.30, 30, 0.5, 0, 0, 5, 1.0, 1.0, 12),
]

print(f"\n{'='*130}")
print(f"Running {len(configs)} configs")
print(f"{'='*130}\n")

results = []
for ci, (name, strats, risk, lev, min_conv, vol_min, vol_max, max_pos, tp_m, sl_m, hold) in enumerate(configs):
    r = backtest(strats, risk, lev, min_conv, vol_min, vol_max, max_pos, tp_m, sl_m, hold,
                 simulate_wd=True, wd_target=2700, wd_amount=2500, wd_keep=200)
    
    results.append({'name': name, **r})
    
    wd_str = f"${r['total_withdrawn']:>8,.0f}" if r['total_withdrawn'] > 0 else "      $0"
    print(f"[{ci+1:2d}/{len(configs)}] {name:<40} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} DD={r['dd']:5.1f}% Tr={r['trades']:5d} WD={wd_str} Cap=${r['final']:>10,.2f}")

results.sort(key=lambda x: x['total_withdrawn'], reverse=True)

print(f"\n{'='*130}")
print("TOP 10")
print(f"{'='*130}")
for r in results[:10]:
    first = r['first_target'][:16] if r['first_target'] else 'N/A'
    print(f"{r['name']:<40} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} DD={r['dd']:5.1f}% Tr={r['trades']:5d} WD=${r['total_withdrawn']:>8,.0f} Cap=${r['final']:>10,.2f} 1st={first}")

# Save
with open(os.path.join(BASE, 'data', 'scanner_opt_v3.json'), 'w') as f:
    json.dump({'timestamp': datetime.now(timezone.utc).isoformat(), 'results': results}, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s")
