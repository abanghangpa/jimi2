#!/usr/bin/env python3
"""
FR Conditioning on ACTUALLY FIRED signals.
Uses strategy_signals.jsonl (891 failed_breakout, 849 trade_flow, etc.)
Simulates outcomes with different FR filters.
"""
import json, csv, os, sys
import numpy as np
from datetime import datetime, timedelta

BASE = "/root/.openclaw/workspace/jimi_audit"
SIGNALS_FILE = os.path.join(BASE, "data", "strategy_signals.jsonl")
ETH_FILE = os.path.join(BASE, "eth_15m_merged.csv")
DERIV_FILE = os.path.join(BASE, "data", "derivatives_history", "derivatives_collected.csv")

INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.0005
HOLD_BARS = 32  # 8 hours

# ============================================================
# LOAD DATA
# ============================================================
print("=" * 80)
print("FR CONDITIONING ON FIRED SIGNALS")
print("=" * 80)

# Load ETH bars
print("\n[1/3] Loading ETH data...")
eth = {}
with open(ETH_FILE) as f:
    for row in csv.DictReader(f):
        eth[row['Open time']] = {
            'open': float(row['Open']),
            'high': float(row['High']),
            'low': float(row['Low']),
            'close': float(row['Close']),
            'volume': float(row['Volume']),
        }
eth_keys = sorted(eth.keys())
print(f"  {len(eth)} bars")

# Load derivatives
print("[2/3] Loading derivatives...")
deriv = {}
with open(DERIV_FILE) as f:
    for row in csv.DictReader(f):
        dt = datetime.fromisoformat(row['timestamp'])
        dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        deriv[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
            'ls_ratio': float(row['ls_ratio']),
            'funding_rate': float(row['funding_rate']),
        }
print(f"  {len(deriv)} snapshots")

def find_deriv(ts_str, max_min=30):
    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    for off in range(0, max_min + 1, 1):
        for d in [dt - timedelta(minutes=off), dt + timedelta(minutes=off)]:
            k = d.strftime('%Y-%m-%d %H:%M:%S')
            if k in deriv:
                return deriv[k]
    return None

# Load fired signals
print("[3/3] Loading fired signals...")
signals_by_strategy = {}
with open(SIGNALS_FILE) as f:
    for line in f:
        try:
            d = json.loads(line)
            if not d.get('fired'):
                continue
            strat = d.get('strategy', 'unknown')
            if strat not in signals_by_strategy:
                signals_by_strategy[strat] = []
            signals_by_strategy[strat].append(d)
        except:
            pass

for strat, sigs in sorted(signals_by_strategy.items(), key=lambda x: -len(x[1])):
    print(f"  {strat}: {len(sigs)} fired signals")

# ============================================================
# SIMULATE OUTCOMES
# ============================================================
def simulate(signals, tp_mult=2.0, sl_mult=1.0, hold=32, fr_filter=None, whale_filter=False, label=""):
    """Simulate outcomes for a set of signals with optional FR/whale filters."""
    trades = []
    capital = INITIAL_CAPITAL
    peak = capital
    max_dd = 0

    for sig in signals:
        ts = sig['timestamp']
        direction = sig['direction']
        entry_price = sig.get('entry') or sig.get('price', 0)

        if not direction or not entry_price:
            continue

        # Find derivatives
        d = find_deriv(ts)
        if not d:
            continue

        fr = d['funding_rate']
        ls_ratio = d['ls_ratio']

        # FR filter
        if fr_filter == 'confirm':
            if direction == 'SHORT' and fr <= 0: continue
            if direction == 'LONG' and fr >= 0: continue
        elif fr_filter == 'positive':
            if fr <= 0: continue
        elif fr_filter == 'negative':
            if fr >= 0: continue
        elif fr_filter == 'extreme':
            if abs(fr) < 0.00005: continue

        # Whale filter
        if whale_filter:
            if direction == 'SHORT' and ls_ratio <= 1.0: continue
            if direction == 'LONG' and ls_ratio >= 1.0: continue

        # Find entry bar
        if ts not in eth:
            continue
        entry_idx = eth_keys.index(ts)

        # Compute ATR from recent bars
        if entry_idx < 14:
            continue
        recent = [eth[eth_keys[j]] for j in range(entry_idx - 14, entry_idx)]
        trs = []
        for i in range(1, len(recent)):
            tr = max(recent[i]['high'] - recent[i]['low'],
                     abs(recent[i]['high'] - recent[i-1]['close']),
                     abs(recent[i]['low'] - recent[i-1]['close']))
            trs.append(tr)
        atr = np.mean(trs)
        if atr <= 0:
            continue

        # TP/SL
        if direction == 'LONG':
            tp = entry_price + tp_mult * atr
            sl = entry_price - sl_mult * atr
        else:
            tp = entry_price - tp_mult * atr
            sl = entry_price + sl_mult * atr

        # Simulate forward
        outcome = None
        exit_price = None
        for j in range(entry_idx + 1, min(entry_idx + hold + 1, len(eth_keys))):
            bar = eth[eth_keys[j]]
            if direction == 'LONG':
                if bar['high'] >= tp:
                    outcome = 'WIN'; exit_price = tp; break
                if bar['low'] <= sl:
                    outcome = 'LOSS'; exit_price = sl; break
            else:
                if bar['low'] <= tp:
                    outcome = 'WIN'; exit_price = tp; break
                if bar['high'] >= sl:
                    outcome = 'LOSS'; exit_price = sl; break

        if outcome is None:
            last_bar = eth[eth_keys[min(entry_idx + hold, len(eth_keys) - 1)]]
            exit_price = last_bar['close']
            outcome = 'WIN' if ((direction == 'LONG' and exit_price > entry_price) or
                                (direction == 'SHORT' and exit_price < entry_price)) else 'LOSS'

        pnl_pct = ((exit_price - entry_price) / entry_price * 100) if direction == 'LONG' \
                  else ((entry_price - exit_price) / entry_price * 100)

        size = capital * RISK_PCT * LEVERAGE
        net_pnl = size * pnl_pct / 100 - size * FEE_RATE * 2
        capital += net_pnl
        if capital > peak: peak = capital
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd

        trades.append({
            'time': ts, 'dir': direction, 'entry': entry_price, 'exit': exit_price,
            'pnl_pct': pnl_pct, 'pnl_dollar': net_pnl, 'outcome': outcome,
            'fr': fr, 'ls': ls_ratio,
        })

    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0, 'label': label}

    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    total_win = sum(t['pnl_dollar'] for t in wins)
    total_loss = sum(abs(t['pnl_dollar']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')

    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(len(wins) / len(trades) * 100, 1),
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
        'pnl_pct': round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'final_capital': round(capital, 2),
        'max_dd': round(max_dd, 2),
        'label': label,
    }

# ============================================================
# TEST MATRIX
# ============================================================
print("\n" + "=" * 80)
print("RUNNING TESTS")
print("=" * 80)

configs = [
    {'fr_filter': None, 'whale_filter': False, 'label': 'baseline'},
    {'fr_filter': 'confirm', 'whale_filter': False, 'label': '+FR confirm'},
    {'fr_filter': 'positive', 'whale_filter': False, 'label': '+FR>0'},
    {'fr_filter': 'negative', 'whale_filter': False, 'label': '+FR<0'},
    {'fr_filter': 'extreme', 'whale_filter': False, 'label': '+FR extreme'},
    {'fr_filter': None, 'whale_filter': True, 'label': '+whale'},
    {'fr_filter': 'confirm', 'whale_filter': True, 'label': '+whale+FR confirm'},
]

target_strategies = ['failed_breakout', 'trade_flow', 'taker_flow', 'orderbook_imbalance', 'squeeze_breakout']

all_results = []

for strat in target_strategies:
    sigs = signals_by_strategy.get(strat, [])
    if not sigs:
        print(f"\n  {strat}: no fired signals, skipping")
        continue

    print(f"\n{'='*80}")
    print(f"  {strat} ({len(sigs)} fired signals)")
    print(f"{'='*80}")
    print(f"  {'Config':<25s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s} | {'MaxDD':>6s}")
    print("  " + "-" * 85)

    for cfg in configs:
        m = simulate(sigs, fr_filter=cfg.get('fr_filter'), whale_filter=cfg.get('whale_filter'), label=cfg['label'])
        m['strategy'] = strat
        m['config'] = cfg['label']
        all_results.append(m)

        hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
        print(f"  {cfg['label']:<25s} | {m['trades']:>6d} | {m.get('wins',0):>3d} {m.get('losses',0):>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f} | {m['pnl_pct']:>+6.2f}% | {m['max_dd']:>5.2f}%{hit}")

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*80}")
print("SUMMARY — Best FR filter per strategy")
print(f"{'='*80}")

for strat in target_strategies:
    strat_results = [r for r in all_results if r['strategy'] == strat and r['trades'] >= 3]
    if not strat_results:
        continue
    strat_results.sort(key=lambda x: (-x['pf'], -x['wr']))
    best = strat_results[0]
    baseline = next((r for r in all_results if r['strategy'] == strat and r['config'] == 'baseline'), None)

    print(f"\n  {strat}:")
    if baseline and baseline['trades'] > 0:
        print(f"    Base: {baseline['trades']} trades, WR={baseline['wr']}%, PF={baseline['pf']}, PnL=${baseline['pnl']:+.2f}")
    print(f"    Best: {best['config']} | {best['trades']} trades, WR={best['wr']}%, PF={best['pf']}, PnL=${best['pnl']:+.2f}")
    if baseline and baseline['trades'] > 0 and best['pf'] > baseline['pf']:
        print(f"    Improvement: PF +{best['pf'] - baseline['pf']:.2f}, WR +{best['wr'] - baseline['wr']:.1f}pp")
    elif baseline and baseline['trades'] > 0:
        print(f"    No improvement over baseline")

# Save
with open(os.path.join(BASE, "reports", "fr_conditioning_results.json"), "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\n  Saved to reports/fr_conditioning_results.json")
