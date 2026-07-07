#!/usr/bin/env python3
"""
Single-strategy optimization with CORRECT 15m candle data.
Fixes: timestamp parsing, 15m TP/SL checking.
"""
import json, time, sys, os, csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict

t0 = time.time()
STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "whale_watch"

BASE = '/root/.openclaw/workspace/jimi_audit'
SIGNALS_FILE = os.path.join(BASE, 'data', 'strategy_signals_v3.jsonl')
CANDLES_FILE = os.path.join(BASE, 'eth_15m_merged.csv')

# Load fired signals for this strategy
print(f"Loading {STRATEGY} signals...", end=" "); sys.stdout.flush()
fired = []
with open(SIGNALS_FILE) as f:
    for line in f:
        if '"fired": true' not in line:
            continue
        try:
            sig = json.loads(line.strip())
            if sig.get('fired') and sig.get('strategy') == STRATEGY:
                fired.append(sig)
        except:
            pass
print(f"{len(fired)} fired signals in {time.time()-t0:.1f}s")

if len(fired) < 5:
    print(f"ERROR: Only {len(fired)} signals. Need at least 5.")
    sys.exit(1)

# Stats
dirs = defaultdict(int)
for s in fired:
    d = s.get('direction')
    if d in ('LONG', 'SHORT'):
        dirs[d] += 1
print(f"Directions: LONG={dirs['LONG']}, SHORT={dirs['SHORT']}")

convs = [s['conviction'] for s in fired if s.get('conviction')]
print(f"Conviction: min={min(convs):.3f}, max={max(convs):.3f}, avg={sum(convs)/len(convs):.3f}")

# Fix timestamp format: '2026-06-25 14:30:00:00' -> '2026-06-25 14:30:00'
def fix_ts(ts):
    if ts and len(ts) > 19:
        return ts[:19]
    return ts

# Build signal groups by fixed timestamp
ts_groups = defaultdict(list)
for s in fired:
    s['_ts'] = fix_ts(s['timestamp'])
    ts_groups[s['_ts']].append(s)
timestamps = sorted(ts_groups.keys())
print(f"Timestamps: {len(timestamps)} ({timestamps[0]} to {timestamps[-1]})")

# Load 15m candle data
print(f"Loading 15m candles from {CANDLES_FILE}...", end=" "); sys.stdout.flush()
candles_by_ts = {}
with open(CANDLES_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        ts_str = row.get('Open time', row.get('timestamp', '')).strip()
        if not ts_str:
            continue
        # Try to parse various formats
        try:
            if 'T' in ts_str:
                dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(ts_str[:19], '%Y-%m-%d %H:%M:%S')
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            key = dt.strftime('%Y-%m-%d %H:%M:%S')
            candles_by_ts[key] = {
                'high': float(row.get('High', row.get('high', 0))),
                'low': float(row.get('Low', row.get('low', 0))),
                'close': float(row.get('Close', row.get('close', 0))),
                'open': float(row.get('Open', row.get('open', 0))),
            }
        except:
            pass
print(f"{len(candles_by_ts)} candles loaded")

# Check timestamp alignment
sample_ts = timestamps[0]
sample_in_candles = sample_ts in candles_by_ts
if not sample_in_candles:
    # Try matching with different formats
    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%m/%d/%Y %H:%M']:
        try:
            dt = datetime.strptime(sample_ts, fmt)
            alt_key = dt.strftime('%Y-%m-%d %H:%M:%S')
            if alt_key in candles_by_ts:
                sample_in_candles = True
                print(f"Timestamp format mismatch! Signal: '{sample_ts}', candle key: '{alt_key}'")
                break
        except:
            pass

if not sample_in_candles:
    # Show candle keys for debugging
    sorted_keys = sorted(candles_by_ts.keys())[:5]
    print(f"WARNING: Signal timestamp '{sample_ts}' not found in candles!")
    print(f"Sample candle keys: {sorted_keys}")
    print("Attempting fuzzy matching...")

# Build sorted candle timestamps for lookup
sorted_candle_ts = sorted(candles_by_ts.keys())

def find_candle_at_or_after(ts_str):
    """Find the candle at or after a given timestamp."""
    # Direct lookup
    if ts_str in candles_by_ts:
        return ts_str
    # Try +15min, +30min, +45min, +1h
    try:
        dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    except:
        return None
    for offset_min in [0, 15, 30, 45, 60]:
        check = (dt + timedelta(minutes=offset_min)).strftime('%Y-%m-%d %H:%M:%S')
        if check in candles_by_ts:
            return check
    return None

# === BACKTEST ===
def backtest(direction_filter, hold_candles, leverage, risk_pct,
             min_conviction, init=200, fee=0.001,
             simulate_wd=False, wd_target=2700, wd_amount=2500, wd_keep=200):
    """Backtest using 15m candle data. hold_candles = number of 15m bars."""
    cap = float(init); pk = cap; max_dd = 0.0
    wins = 0; losses = 0; timeouts = 0; total = 0
    gross_p = 0.0; gross_l = 0.0
    open_positions = []
    withdrawals = []; first_target = None

    for ts in timestamps:
        # Check positions against candle data
        still_open = []
        for pos in open_positions:
            # Find candle at this timestamp
            candle_key = find_candle_at_or_after(ts)
            if candle_key is None:
                still_open.append(pos)
                continue

            candle = candles_by_ts[candle_key]
            high = candle['high']
            low = candle['low']

            # Count bars held
            pos_dt = datetime.strptime(pos['opened_at'], '%Y-%m-%d %H:%M:%S')
            now_dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            bars_held = int((now_dt - pos_dt).total_seconds() / 900)  # 15min bars

            # Check TP/SL against candle high/low (TP first like bb_full_test.py)
            hit = False
            if pos['direction'] == 'LONG':
                if high >= pos['tp']:
                    pnl = (pos['tp'] - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1; gross_p += max(0, pnl)
                    hit = True
                elif low <= pos['sl']:
                    pnl = (pos['sl'] - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1; gross_l += max(0, -pnl)
                    hit = True
            else:  # SHORT
                if low <= pos['tp']:
                    pnl = (pos['entry'] - pos['tp']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; wins += 1; gross_p += max(0, pnl)
                    hit = True
                elif high >= pos['sl']:
                    pnl = (pos['entry'] - pos['sl']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                    cap += pnl; total += 1; losses += 1; gross_l += max(0, -pnl)
                    hit = True

            # Timeout
            if not hit and bars_held >= hold_candles:
                close_price = candle['close']
                if pos['direction'] == 'LONG':
                    pnl = (close_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
                else:
                    pnl = (pos['entry'] - close_price) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
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

            if len(open_positions) >= 1:  # One position at a time per strategy
                continue

            entry = sig.get('entry') or sig.get('price', 0)
            sl = sig.get('sl', 0)
            tp1 = sig.get('tp1', 0)

            if not entry or not sl or not tp1:
                continue

            # Position sizing
            if d == 'LONG':
                sl_dist = entry - sl
            else:
                sl_dist = sl - entry
            if sl_dist <= 0:
                continue

            sl_pct = sl_dist / entry
            size = (cap * risk_pct) / (sl_pct * leverage)
            if size < 0.001 or cap < 10:
                continue

            open_positions.append({
                'direction': d, 'entry': entry, 'tp': tp1, 'sl': sl,
                'size': size, 'leverage': leverage, 'opened_at': sig['_ts'],
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
        last_candle_key = find_candle_at_or_after(timestamps[-1])
        if last_candle_key:
            close_price = candles_by_ts[last_candle_key]['close']
        else:
            close_price = pos['entry']
        if pos['direction'] == 'LONG':
            pnl = (close_price - pos['entry']) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
        else:
            pnl = (pos['entry'] - close_price) / pos['entry'] * pos['size'] * pos['leverage'] - pos['size'] * fee * 2
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
# hold_candles: 4=1h, 8=2h, 16=4h, 32=8h, 48=12h, 96=24h
configs = []
dirs_to_test = [None, 'LONG', 'SHORT']
holds = [4, 8, 16, 32, 48]  # 1h, 2h, 4h, 8h, 12h
leverages = [15, 20, 25, 30]
risks = [0.10, 0.15, 0.20, 0.25]
min_convs = [0.3, 0.5, 0.6, 0.7]

for d in dirs_to_test:
    for hold in holds:
        for lev in leverages:
            for risk in risks:
                for conv in min_convs:
                    hold_h = hold * 15 / 60
                    label = f"{'ALL' if d is None else d}_lev{lev}_r{int(risk*100)}_h{hold_h:.0f}h_c{int(conv*100)}"
                    configs.append((label, d, hold, lev, risk, conv))

print(f"\n{len(configs)} configs to test...")

results = []
for ci, (label, d, hold, lev, risk, conv) in enumerate(configs):
    r = backtest(d, hold, lev, risk, conv,
                 simulate_wd=True, wd_target=2700, wd_amount=2500, wd_keep=200)
    results.append((label, r))
    if (ci + 1) % 100 == 0:
        best = max(results, key=lambda x: x[1]['total_withdrawn'])
        print(f"  [{ci+1}/{len(configs)}] best: {best[0]} WD=${best[1]['total_withdrawn']:,.0f} PF={best[1]['pf']:.2f}")

results.sort(key=lambda x: (x[1]['total_withdrawn'], x[1]['pf']), reverse=True)

print(f"\n{'='*110}")
print(f"TOP 10 CONFIGS FOR {STRATEGY}")
print(f"{'='*110}")
print(f"{'Config':<45} {'WR%':>6} {'PF':>6} {'DD%':>6} {'Tr':>5} {'WD$':>10} {'Cap$':>12} {'1stWD':>12}")
print("-" * 110)
for label, r in results[:10]:
    first = r['first_target'][:10] if r['first_target'] else 'N/A'
    print(f"{label:<45} {r['wr']:>5.1f}% {r['pf']:>5.2f} {r['dd']:>5.1f}% {r['trades']:>5} {r['total_withdrawn']:>9,.0f} {r['final']:>11,.2f} {first:>12}")

# Save
output = {
    'strategy': STRATEGY, 'signals': len(fired), 'directions': dict(dirs),
    'best_config': results[0][0] if results else None,
    'best_result': results[0][1] if results else None,
    'top_10': [(l, r) for l, r in results[:10]],
}
with open(os.path.join(BASE, 'data', f'opt_{STRATEGY}.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s")
