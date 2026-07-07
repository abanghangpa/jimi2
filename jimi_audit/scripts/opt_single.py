#!/usr/bin/env python3
"""
Single-strategy optimization for $200 → $2500/month target.
Tests all TP/SL/hold/leverage/risk combos for one strategy.
"""
import json, time, sys, os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

t0 = time.time()
STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "power_of_3"

BASE = '/root/.openclaw/workspace/jimi_audit'
SIGNALS_FILE = os.path.join(BASE, 'data', 'strategy_signals_v3.jsonl')

# Load fired signals for this strategy only
print(f"Loading {STRATEGY} signals...", end=" "); sys.stdout.flush()
fired = []
with open(SIGNALS_FILE) as f:
    for line in f:
        if f'"fired": true' not in line:
            continue
        try:
            sig = json.loads(line.strip())
            if sig.get('fired') and sig.get('strategy') == STRATEGY:
                fired.append(sig)
        except:
            pass
print(f"{len(fired)} fired signals in {time.time()-t0:.1f}s")

if len(fired) < 5:
    print(f"ERROR: Only {len(fired)} signals. Need at least 5 to backtest.")
    sys.exit(1)

# Stats
dirs = defaultdict(int)
for s in fired:
    d = s.get('direction')
    if d in ('LONG', 'SHORT'):
        dirs[d] += 1
print(f"Directions: LONG={dirs['LONG']}, SHORT={dirs['SHORT']}")

# Conviction range
convs = [s['conviction'] for s in fired if s.get('conviction')]
print(f"Conviction: min={min(convs):.3f}, max={max(convs):.3f}, avg={sum(convs)/len(convs):.3f}")

# Build timestamp groups
ts_groups = defaultdict(list)
for s in fired:
    ts_groups[s['timestamp']].append(s)
timestamps = sorted(ts_groups.keys())
print(f"Timestamps: {len(timestamps)} ({timestamps[0]} to {timestamps[-1]})")

# Load hourly prices
with open(os.path.join(BASE, 'data', 'eth_full_1h.json')) as f:
    raw = json.load(f)
price_by_hour = {}
for candle in raw:
    ts = datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc)
    key = ts.strftime('%Y-%m-%d %H:00:00')
    price_by_hour[key] = {'high': float(candle[2]), 'low': float(candle[3]), 'close': float(candle[4])}

# === BACKTEST ===
def backtest(direction_filter, tp_pct, sl_pct, hold_hours, leverage, risk_pct,
             min_conviction, init=200, fee=0.001,
             simulate_wd=False, wd_target=2700, wd_amount=2500, wd_keep=200):
    cap = float(init); pk = cap; max_dd = 0.0
    wins = 0; losses = 0; timeouts = 0; total = 0
    gross_p = 0.0; gross_l = 0.0
    open_positions = []
    withdrawals = []; first_target = None

    for ts in timestamps:
        # Check positions
        still_open = []
        for pos in open_positions:
            pos_dt = datetime.strptime(pos['opened_at'][:19], '%Y-%m-%d %H:%M:%S')
            now_dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
            hours = (now_dt - pos_dt).total_seconds() / 3600

            # Get current price from signal
            current_price = None
            for s in ts_groups[ts]:
                if s.get('price'):
                    current_price = s['price']
                    break
            if current_price is None:
                still_open.append(pos)
                continue

            # TP/SL check
            hit = False
            if pos['direction'] == 'LONG':
                if current_price <= pos['sl']:
                    pnl = (pos['sl'] - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1; gross_l += max(0, -pnl)
                    hit = True
                elif current_price >= pos['tp']:
                    pnl = (pos['tp'] - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1; gross_p += max(0, pnl)
                    hit = True
            else:
                if current_price >= pos['sl']:
                    pnl = (pos['entry'] - pos['sl']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1; gross_l += max(0, -pnl)
                    hit = True
                elif current_price <= pos['tp']:
                    pnl = (pos['entry'] - pos['tp']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1; gross_p += max(0, pnl)
                    hit = True

            if not hit and hours >= hold_hours:
                if pos['direction'] == 'LONG':
                    pnl = (current_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                else:
                    pnl = (pos['entry'] - current_price) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                cap += pnl; total += 1; timeouts += 1
                if pnl > 0: wins += 1; gross_p += pnl
                else: losses += 1; gross_l += abs(pnl)
                hit = True

            if not hit:
                still_open.append(pos)
        open_positions = still_open

        # New signals
        for sig in ts_groups[ts]:
            d = sig.get('direction')
            if direction_filter and d != direction_filter:
                continue
            if d not in ('LONG', 'SHORT'):
                continue

            conv = sig.get('conviction', 0) or 0
            if conv < min_conviction:
                continue

            if any(p for p in open_positions):
                continue

            entry = sig.get('price', 0)
            if not entry:
                continue

            # TP/SL from signal or use fixed %
            sl_sig = sig.get('sl', 0)
            tp_sig = sig.get('tp1', 0)

            if sl_sig and tp_sig:
                # Use signal's TP/SL
                sl_val = sl_sig
                tp_val = tp_sig
            else:
                # Use fixed %
                if d == 'LONG':
                    tp_val = entry * (1 + tp_pct / 100)
                    sl_val = entry * (1 - sl_pct / 100)
                else:
                    tp_val = entry * (1 - tp_pct / 100)
                    sl_val = entry * (1 + sl_pct / 100)

            # Position sizing
            if d == 'LONG':
                sl_dist = entry - sl_val
            else:
                sl_dist = sl_val - entry
            if sl_dist <= 0:
                continue

            sl_pct_actual = sl_dist / entry
            size = (cap * risk_pct) / (sl_pct_actual * leverage)
            if size < 0.001 or cap < 10:
                continue

            open_positions.append({
                'direction': d, 'entry': entry, 'tp': tp_val, 'sl': sl_val,
                'size': size, 'leverage': leverage, 'opened_at': ts,
                'hold_hours': hold_hours,
            })

        if cap > pk: pk = cap
        dd = (pk - cap) / pk * 100 if pk > 0 else 0
        if dd > max_dd: max_dd = dd

        if simulate_wd and cap >= wd_target:
            if first_target is None: first_target = ts
            if cap - wd_keep >= wd_amount:
                withdrawals.append({'date': ts, 'amount': wd_amount})
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
        'total_withdrawn': total_wd, 'first_target': first_target,
    }

# === PARAMETER SWEEP ===
configs = []
dirs_to_test = [None, 'LONG', 'SHORT']
tp_pcts = [0.5, 1.0, 1.5, 2.0, 3.0]
sl_pcts = [0.3, 0.5, 1.0, 1.5, 2.0]
holds = [4, 8, 12, 24]
leverages = [15, 20, 25, 30]
risks = [0.10, 0.15, 0.20]
min_convs = [0.3, 0.5, 0.6, 0.7]

# First: test with signal's own TP/SL (no override)
for d in dirs_to_test:
    for lev in leverages:
        for risk in risks:
            for hold in holds:
                for conv in min_convs:
                    label = f"sig_{'ALL' if d is None else d}_lev{lev}_risk{int(risk*100)}_h{hold}_c{int(conv*100)}"
                    configs.append((label, d, 0, 0, hold, lev, risk, conv))

# Also test fixed TP/SL overrides
for d in dirs_to_test:
    for tp in tp_pcts:
        for sl in sl_pcts:
            if tp < sl * 0.5:  # Skip bad R:R
                continue
            label = f"tp{tp}_sl{sl}_{'ALL' if d is None else d}_lev25_r15_h8"
            configs.append((label, d, tp, sl, 8, 25, 0.15, 0.5))

print(f"\n{len(configs)} configs to test...")

# Run and find best
results = []
for ci, (label, d, tp, sl, hold, lev, risk, conv) in enumerate(configs):
    r = backtest(d, tp, sl, hold, lev, risk, conv,
                 simulate_wd=True, wd_target=2700, wd_amount=2500, wd_keep=200)
    results.append((label, r))
    if (ci + 1) % 50 == 0:
        print(f"  [{ci+1}/{len(configs)}] best so far: {max(results, key=lambda x: x[1]['total_withdrawn'])[0]}")

# Sort by total_withdrawn
results.sort(key=lambda x: x[1]['total_withdrawn'], reverse=True)

print(f"\n{'='*100}")
print(f"TOP 10 CONFIGS FOR {STRATEGY}")
print(f"{'='*100}")
print(f"{'Config':<50} {'WR%':>6} {'PF':>6} {'DD%':>6} {'Tr':>5} {'WD$':>10} {'Cap$':>12} {'1stWD':>12}")
print("-" * 100)
for label, r in results[:10]:
    first = r['first_target'][:10] if r['first_target'] else 'N/A'
    print(f"{label:<50} {r['wr']:>5.1f}% {r['pf']:>5.2f} {r['dd']:>5.1f}% {r['trades']:>5} {r['total_withdrawn']:>9,.0f} {r['final']:>11,.2f} {first:>12}")

# Also show signal TP/SL vs fixed TP/SL best
sig_best = max([x for x in results if x[0].startswith('sig_')], key=lambda x: x[1]['total_withdrawn'], default=None)
fixed_best = max([x for x in results if not x[0].startswith('sig_')], key=lambda x: x[1]['total_withdrawn'], default=None)

print(f"\nBest with signal TP/SL: {sig_best[0]} → WD=${sig_best[1]['total_withdrawn']:,.0f}, WR={sig_best[1]['wr']:.1f}%, PF={sig_best[1]['pf']:.2f}" if sig_best else "No signal TP/SL results")
print(f"Best with fixed TP/SL: {fixed_best[0]} → WD=${fixed_best[1]['total_withdrawn']:,.0f}, WR={fixed_best[1]['wr']:.1f}%, PF={fixed_best[1]['pf']:.2f}" if fixed_best else "No fixed TP/SL results")

# Save
output = {
    'strategy': STRATEGY,
    'signals': len(fired),
    'directions': dict(dirs),
    'conviction_range': [min(convs), max(convs)] if convs else [0, 0],
    'best_config': results[0][0] if results else None,
    'best_result': results[0][1] if results else None,
    'top_10': [(l, r) for l, r in results[:10]],
}
with open(os.path.join(BASE, 'data', f'opt_{STRATEGY}.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s")
