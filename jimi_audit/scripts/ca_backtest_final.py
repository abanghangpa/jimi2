#!/usr/bin/env python3
"""
Cross-Asset + FR<0 Backtest — Final Version
- Real data: May 13 - Jul 6 (derivatives)
- 10 synthetic scenarios for Feb 1 - May 12 gap
- De-duplicated signals (one per bar)
- TP/SL grid search
- Hold-out validation
"""
import json, csv, os, sys, glob
import numpy as np
from datetime import datetime, timedelta

BASE = '/root/.openclaw/workspace/jimi_audit'

# ============================================================
# LOAD DATA
# ============================================================
print("=" * 80)
print("CROSS-ASSET + FR<0 BACKTEST — FINAL")
print("=" * 80)

# Load ETH bars
print("\n[1/4] Loading ETH data...")
eth = {}
with open(f'{BASE}/eth_15m_merged.csv') as f:
    for row in csv.DictReader(f):
        eth[row['Open time']] = {
            'high': float(row['High']), 'low': float(row['Low']),
            'close': float(row['Close']), 'open': float(row['Open']),
        }
eth_keys = sorted(eth.keys())
print(f"  {len(eth)} bars ({eth_keys[0]} to {eth_keys[-1]})")

# Compute ATR for all bars
print("[2/4] Computing ATR...")
atr_cache = {}
closes = [eth[k]['close'] for k in eth_keys]
highs = [eth[k]['high'] for k in eth_keys]
lows = [eth[k]['low'] for k in eth_keys]
for i in range(14, len(eth_keys)):
    trs = []
    for j in range(i - 14, i):
        tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
        trs.append(tr)
    atr_cache[eth_keys[i]] = np.mean(trs)
print(f"  {len(atr_cache)} ATR values computed")

# Load derivatives (real + synthetic scenarios)
print("[3/4] Loading derivatives...")

def load_deriv_csv(path):
    deriv = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                dt = datetime.fromisoformat(row['timestamp'])
                dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
                k = dt_floor.strftime('%Y-%m-%d %H:%M:%S')
                deriv[k] = {
                    'ls_ratio': float(row.get('ls_ratio', 0) or 0),
                    'funding_rate': float(row.get('funding_rate', 0) or 0),
                }
            except:
                pass
    return deriv

real_deriv = load_deriv_csv(f'{BASE}/data/derivatives_history/derivatives_collected.csv')
print(f"  Real: {len(real_deriv)} snapshots ({min(real_deriv.keys())} to {max(real_deriv.keys())})")

synth_dir = f'{BASE}/data/derivatives_synthetic'
synth_scenarios = {}
for f in sorted(glob.glob(os.path.join(synth_dir, '*_merged.csv'))):
    name = os.path.basename(f).replace('derivatives_', '').replace('_merged.csv', '')
    synth_scenarios[name] = load_deriv_csv(f)
    print(f"  Synthetic '{name}': {len(synth_scenarios[name])} snapshots")

# Load cross_asset signals
print("[4/4] Loading cross_asset signals...")
signals = []
with open(f'{BASE}/data/strategy_signals.jsonl') as f:
    for line in f:
        try:
            d = json.loads(line)
            if d.get('fired') and d.get('strategy') == 'cross_asset':
                signals.append(d)
        except:
            pass
print(f"  {len(signals)} fired cross_asset signals")

# ============================================================
# SIMULATION ENGINE
# ============================================================
def find_deriv(deriv_map, ts, max_min=30):
    if ts in deriv_map:
        return deriv_map[ts]
    dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    for off in range(1, max_min + 1, 1):
        for d in [dt - timedelta(minutes=off), dt + timedelta(minutes=off)]:
            k = d.strftime('%Y-%m-%d %H:%M:%S')
            if k in deriv_map:
                return deriv_map[k]
    return None

def sim(signals, deriv_map, fr_filter=None, tp=1.5, sl=1.5, hold=16, dedup=True, label=""):
    trades = []
    capital = 200.0
    peak = capital
    max_dd = 0
    used_bars = set()

    for sig in signals:
        ts = sig['timestamp']
        direction = sig['direction']
        p = sig.get('entry') or sig.get('price', 0)
        if not direction or not p:
            continue

        if dedup and ts in used_bars:
            continue
        used_bars.add(ts)

        dv = find_deriv(deriv_map, ts)
        if not dv:
            continue

        fr = dv['funding_rate']
        ls = dv['ls_ratio']

        if fr_filter == 'neg' and fr >= 0:
            continue
        if fr_filter == 'pos' and fr <= 0:
            continue

        if ts not in atr_cache:
            continue
        atr = atr_cache[ts]
        if atr <= 0:
            continue

        if direction == 'LONG':
            tp_p = p + tp * atr
            sl_p = p - sl * atr
        else:
            tp_p = p - tp * atr
            sl_p = p + sl * atr

        idx = eth_keys.index(ts) if ts in eth_keys else -1
        if idx < 0 or idx >= len(eth_keys) - hold:
            continue

        outcome = None
        exit_p = None
        for j in range(idx + 1, min(idx + hold + 1, len(eth_keys))):
            h = highs[j]
            l = lows[j]
            if direction == 'LONG':
                if h >= tp_p:
                    outcome = 'W'; exit_p = tp_p; break
                if l <= sl_p:
                    outcome = 'L'; exit_p = sl_p; break
            else:
                if l <= tp_p:
                    outcome = 'W'; exit_p = tp_p; break
                if h >= sl_p:
                    outcome = 'L'; exit_p = sl_p; break

        if outcome is None:
            exit_p = closes[min(idx + hold, len(eth_keys) - 1)]
            outcome = 'W' if ((direction == 'LONG' and exit_p > p) or
                              (direction == 'SHORT' and exit_p < p)) else 'L'

        pnl_pct = ((exit_p - p) / p * 100) if direction == 'LONG' else ((p - exit_p) / p * 100)
        size = capital * 0.10 * 25
        net_pnl = size * pnl_pct / 100 - size * 0.0005 * 2
        capital += net_pnl
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

        trades.append({
            'time': ts, 'dir': direction, 'entry': p, 'exit': exit_p,
            'pnl_pct': pnl_pct, 'pnl_dollar': net_pnl, 'outcome': outcome,
            'fr': fr, 'ls': ls,
        })

    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0, 'label': label}

    wins = [t for t in trades if t['outcome'] == 'W']
    losses = [t for t in trades if t['outcome'] == 'L']
    tw = sum(t['pnl_dollar'] for t in wins)
    tl = sum(abs(t['pnl_dollar']) for t in losses)
    pf = tw / tl if tl > 0 else float('inf')

    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(len(wins) / len(trades) * 100, 1),
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
        'pnl_pct': round((capital - 200) / 200 * 100, 2),
        'final_capital': round(capital, 2),
        'max_dd': round(max_dd, 2),
        'label': label,
        'trades_detail': trades,
    }

# ============================================================
# TEST 1: BASELINE vs FR<0 (real data)
# ============================================================
print("\n" + "=" * 80)
print("TEST 1: BASELINE vs FR<0 (real derivatives, May 13 - Jul 6)")
print("=" * 80)

print(f"\n  {'Config':<25s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s} | {'MaxDD':>6s}")
print("  " + "-" * 85)

for fr_filter, label in [(None, 'baseline'), ('neg', 'FR<0'), ('pos', 'FR>0')]:
    m = sim(signals, real_deriv, fr_filter=fr_filter, label=label)
    hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
    print(f"  {label:<25s} | {m['trades']:>6d} | {m.get('wins',0):>3d} {m.get('losses',0):>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f} | {m['pnl_pct']:>+6.2f}% | {m['max_dd']:>5.2f}%{hit}")

# ============================================================
# TEST 2: TP/SL GRID with FR<0
# ============================================================
print("\n" + "=" * 80)
print("TEST 2: TP/SL GRID with FR<0 (real data)")
print("=" * 80)

print(f"\n  {'TP':>4s} / {'SL':>4s} / {'Hold':>4s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s}")
print("  " + "-" * 60)

best_pf = 0
best_cfg = None

for hold in [8, 16, 24, 32]:
    for tp in [1.0, 1.5, 2.0, 2.5, 3.0]:
        for sl in [0.5, 1.0, 1.5, 2.0]:
            m = sim(signals, real_deriv, fr_filter='neg', tp=tp, sl=sl, hold=hold)
            if m['trades'] >= 3:
                hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
                print(f"  {tp:>4.1f} / {sl:>4.1f} / {hold:>4d} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f}{hit}")
                if m['pf'] > best_pf:
                    best_pf = m['pf']
                    best_cfg = {'tp': tp, 'sl': sl, 'hold': hold, **m}

# ============================================================
# TEST 3: HOLD-OUT VALIDATION
# ============================================================
print("\n" + "=" * 80)
print("TEST 3: HOLD-OUT VALIDATION")
print("=" * 80)

p1_cutoff = '2026-06-20'
p1_sigs = [s for s in signals if s['timestamp'] < p1_cutoff]
p2_sigs = [s for s in signals if s['timestamp'] >= p1_cutoff]

print(f"  P1 (before {p1_cutoff}): {len(p1_sigs)} signals")
print(f"  P2 ({p1_cutoff}+): {len(p2_sigs)} signals")

for fr_filter, label in [(None, 'baseline'), ('neg', 'FR<0')]:
    m1 = sim(p1_sigs, real_deriv, fr_filter=fr_filter)
    m2 = sim(p2_sigs, real_deriv, fr_filter=fr_filter)
    print(f"\n  {label}:")
    print(f"    P1: {m1['trades']:>4d} trades, WR={m1['wr']:>5.1f}%, PF={m1['pf']:>6.2f}, PnL=${m1['pnl']:>+7.2f}")
    print(f"    P2: {m2['trades']:>4d} trades, WR={m2['wr']:>5.1f}%, PF={m2['pf']:>6.2f}, PnL=${m2['pnl']:>+7.2f}")

# ============================================================
# TEST 4: SYNTHETIC SCENARIOS (10 scenarios)
# ============================================================
print("\n" + "=" * 80)
print("TEST 4: SYNTHETIC SCENARIOS (Feb 1 - May 12 gap)")
print("Using real signals but synthetic derivatives for the gap period")
print("=" * 80)

# For each synthetic scenario, merge with real data and run
print(f"\n  {'Scenario':<25s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s}")
print("  " + "-" * 65)

for name, synth_deriv in synth_scenarios.items():
    # Merge: synthetic for gap, real for rest
    merged_deriv = {}
    merged_deriv.update(synth_deriv)  # synthetic covers Feb-Jul
    merged_deriv.update(real_deriv)   # real overrides May-Jul

    m = sim(signals, merged_deriv, fr_filter='neg', label=name)
    hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
    print(f"  {name:<25s} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f}{hit}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

if best_cfg:
    print(f"\n  Best config (real data): TP={best_cfg['tp']}, SL={best_cfg['sl']}, Hold={best_cfg['hold']}")
    print(f"    Trades: {best_cfg['trades']}, WR={best_cfg['wr']}%, PF={best_cfg['pf']}")
    print(f"    Capital: $200 -> ${best_cfg['final_capital']:.2f} ({best_cfg['pnl_pct']:+.2f}%)")
    print(f"    Max DD: {best_cfg['max_dd']:.2f}%")

# Save
with open(f'{BASE}/reports/cross_asset_fr_final.json', 'w') as f:
    json.dump({'best_config': best_cfg}, f, indent=2, default=str)
print(f"\n  Saved to reports/cross_asset_fr_final.json")
