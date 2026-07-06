#!/usr/bin/env python3
"""
Fast backtest — uses scan files + ETH CSV, no API calls.
Tests: failed_breakout, judas_sweep with FR state filter variations.
"""
import sys, os, json, csv, time, glob
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data
from src.utils.indicators import calc_atr, calc_ema
from src.strategies.s01_failed_breakout import FailedBreakoutStrategy
from src.strategies.s22_judas_sweep import JudasSweepStrategy

# ============================================================
# CONFIG
# ============================================================
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.0005
HOLD_BARS = 32  # 8 hours

# ============================================================
# LOAD DATA
# ============================================================
print("=" * 80)
print("FAST BACKTEST — FR State Filter on Event Strategies")
print("=" * 80)

print("\n[1/3] Loading ETH data...")
df = load_data("eth_15m_merged.csv")
df['Open time'] = pd.to_datetime(df['Open time'])
df['atr'] = calc_atr(df['High'], df['Low'], df['Close'], 14)
df['ema_200'] = calc_ema(df['Close'], 200)
print(f"  {len(df)} bars")

print("[2/3] Loading scan files for derivatives data...")
scan_dir = "data/scans"
scan_files = sorted(glob.glob(os.path.join(scan_dir, "scan_*.json")))
print(f"  {len(scan_files)} scan files")

# Build derivatives lookup from scan files
deriv_by_ts = {}
for sf in scan_files:
    try:
        with open(sf) as f:
            d = json.load(f)
        ts = d.get('timestamp', '')
        deriv = d.get('derivatives', {})
        if ts and deriv:
            deriv_by_ts[ts] = deriv
    except:
        pass
print(f"  {len(deriv_by_ts)} scans with derivatives")

# Also load from CSV
deriv_csv = {}
with open("data/derivatives_history/derivatives_collected.csv") as f:
    for row in csv.DictReader(f):
        dt = datetime.fromisoformat(row['timestamp'])
        dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        deriv_csv[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
            'ls_ratio': float(row['ls_ratio']),
            'funding_rate': float(row['funding_rate']),
            'oi': float(row.get('oi', 0)),
            'oi_usd': float(row.get('oi_usd', 0)),
        }
print(f"  {len(deriv_csv)} CSV derivative snapshots")

def find_deriv(ts_str):
    """Find derivatives for a timestamp — scan files first, then CSV."""
    # Try scan file (exact match)
    if ts_str in deriv_by_ts:
        return deriv_by_ts[ts_str]
    # Try CSV (nearest 15m)
    if ts_str in deriv_csv:
        return deriv_csv[ts_str]
    # Try CSV with ±30min search
    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    for off in range(1, 31, 1):
        for d in [dt - timedelta(minutes=off), dt + timedelta(minutes=off)]:
            k = d.strftime('%Y-%m-%d %H:%M:%S')
            if k in deriv_csv:
                return deriv_csv[k]
    return None

# Filter to derivatives period
START = "2026-05-13"
END = "2026-07-06"
mask = (df['Open time'] >= START) & (df['Open time'] <= END)
indices = df[mask].index.tolist()
start_idx = max(indices[0], 200)
end_idx = indices[-1]
print(f"  Backtest bars: {start_idx} to {end_idx} ({end_idx - start_idx + 1} bars)")

# ============================================================
# BUILD DATA DICT FOR STRATEGIES
# ============================================================
def build_data_dict(row, deriv):
    """Build the data dict that strategies expect."""
    price = float(row['Close'])
    atr = float(row['atr']) if not np.isnan(row['atr']) else abs(float(row['High']) - float(row['Low']))
    ema_200 = float(row['ema_200']) if 'ema_200' in row and not np.isnan(row['ema_200']) else 0

    data = {
        'price': price,
        'atr': atr,
        'ema_200': ema_200,
        'vol_ratio': 1.0,  # default
        'timestamp': str(row['Open time']),
    }

    if deriv:
        data['derivatives'] = {
            'ls_ratio': deriv.get('ls_ratio', 1.0),
            'funding_rate': deriv.get('funding_rate', 0),
            'oi': deriv.get('oi', 0),
            'oi_usd': deriv.get('oi_usd', 0),
            'whale_signal': 'BEARISH' if deriv.get('ls_ratio', 1.0) > 2.1 else 'BULLISH' if deriv.get('ls_ratio', 1.0) < 1.9 else 'NEUTRAL',
            'positioning': 'NEUTRAL',
        }

    return data

# ============================================================
# BACKTEST ENGINE
# ============================================================
def run_backtest(strategy, fr_filter=None, whale_filter=False, tp_mult=2.0, sl_mult=1.0, hold=32, label=""):
    trades = []
    capital = INITIAL_CAPITAL
    peak = capital
    max_dd = 0
    open_pos = None
    cooldown_until = 0
    signals = 0

    for i in range(start_idx, end_idx + 1):
        row = df.iloc[i]
        ts = str(row['Open time'])
        price = float(row['Close'])
        high = float(row['High'])
        low = float(row['Low'])

        # Close position
        if open_pos:
            bars_held = i - open_pos['entry_idx']
            hit_tp = hit_sl = timeout = False
            if open_pos['dir'] == 'LONG':
                if high >= open_pos['tp']: hit_tp = True
                elif low <= open_pos['sl']: hit_sl = True
            else:
                if low <= open_pos['tp']: hit_tp = True
                elif high >= open_pos['sl']: hit_sl = True
            if bars_held >= hold:
                timeout = True

            if hit_tp or hit_sl or timeout:
                exit_p = open_pos['tp'] if hit_tp else (open_pos['sl'] if hit_sl else price)
                if hit_tp:
                    outcome = 'WIN'
                elif hit_sl:
                    outcome = 'LOSS'
                else:
                    outcome = 'WIN' if ((open_pos['dir'] == 'LONG' and price > open_pos['entry']) or
                                        (open_pos['dir'] == 'SHORT' and price < open_pos['entry'])) else 'LOSS'

                pnl_pct = ((exit_p - open_pos['entry']) / open_pos['entry'] * 100) if open_pos['dir'] == 'LONG' \
                          else ((open_pos['entry'] - exit_p) / open_pos['entry'] * 100)
                net_pnl = open_pos['size'] * pnl_pct / 100 - open_pos['size'] * FEE_RATE * 2
                capital += net_pnl
                if capital > peak: peak = capital
                dd = (peak - capital) / peak * 100 if peak > 0 else 0
                if dd > max_dd: max_dd = dd

                trades.append({
                    'time': open_pos['time'], 'dir': open_pos['dir'],
                    'entry': open_pos['entry'], 'exit': exit_p,
                    'pnl_pct': pnl_pct, 'pnl_dollar': net_pnl,
                    'outcome': outcome, 'bars': bars_held,
                    'fr': open_pos.get('fr', 0), 'ls': open_pos.get('ls', 1),
                })
                open_pos = None

        if capital <= 0 or open_pos or i < cooldown_until:
            continue

        # Get data
        deriv = find_deriv(ts)
        data = build_data_dict(row, deriv)
        if not deriv:
            continue

        # Run strategy
        try:
            result = strategy.check(data, df_15m=df, idx=i)
        except:
            continue

        if not result or not result.direction:
            continue

        direction = result.direction
        fr = deriv.get('funding_rate', 0)
        ls_ratio = deriv.get('ls_ratio', 1.0)

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

        signals += 1
        atr = data['atr']
        if atr <= 0: continue

        if direction == 'LONG':
            tp = price + tp_mult * atr; sl = price - sl_mult * atr
        else:
            tp = price - tp_mult * atr; sl = price + sl_mult * atr

        open_pos = {
            'entry_idx': i, 'entry': price, 'dir': direction,
            'tp': tp, 'sl': sl, 'size': capital * RISK_PCT * LEVERAGE,
            'time': ts, 'fr': fr, 'ls': ls_ratio,
        }
        cooldown_until = i + 6

    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0, 'signals': signals, 'label': label}

    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    total_win = sum(t['pnl_dollar'] for t in wins)
    total_loss = sum(abs(t['pnl_dollar']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')

    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(len(wins)/len(trades)*100, 1),
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
        'pnl_pct': round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'final_capital': round(capital, 2),
        'max_dd': round(max_dd, 2),
        'signals': signals,
        'label': label,
    }

# ============================================================
# RUN TESTS
# ============================================================
print("\n[3/3] Running backtests...")

strategies = {
    'failed_breakout': FailedBreakoutStrategy(config=CONFIG),
    'judas_sweep': JudasSweepStrategy(config=CONFIG),
}

configs = [
    {'fr_filter': None, 'whale_filter': False, 'label': 'baseline'},
    {'fr_filter': 'confirm', 'whale_filter': False, 'label': '+FR confirm'},
    {'fr_filter': 'positive', 'whale_filter': False, 'label': '+FR>0'},
    {'fr_filter': 'negative', 'whale_filter': False, 'label': '+FR<0'},
    {'fr_filter': 'extreme', 'whale_filter': False, 'label': '+FR extreme'},
    {'fr_filter': None, 'whale_filter': True, 'label': '+whale'},
    {'fr_filter': 'confirm', 'whale_filter': True, 'label': '+whale+FR confirm'},
    {'fr_filter': 'positive', 'whale_filter': True, 'label': '+whale+FR>0'},
    {'fr_filter': 'negative', 'whale_filter': True, 'label': '+whale+FR<0'},
    {'fr_filter': 'extreme', 'whale_filter': True, 'label': '+whale+FR extreme'},
]

all_results = []

for strat_name, strat_obj in strategies.items():
    print(f"\n{'='*80}")
    print(f"  {strat_name}")
    print(f"{'='*80}")
    print(f"  {'Config':<25s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'Sig':>4s}")
    print("  " + "-" * 75)

    for cfg in configs:
        m = run_backtest(
            strat_obj,
            fr_filter=cfg.get('fr_filter'),
            whale_filter=cfg.get('whale_filter', False),
            label=cfg['label'],
        )
        m['strategy'] = strat_name
        m['config'] = cfg['label']
        all_results.append(m)

        hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
        print(f"  {cfg['label']:<25s} | {m['trades']:>6d} | {m.get('wins',0):>3d} {m.get('losses',0):>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f} | {m['signals']:>4d}{hit}")

# Summary
print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")

for strat_name in strategies:
    strat_results = [r for r in all_results if r['strategy'] == strat_name and r['trades'] >= 3]
    if not strat_results:
        print(f"\n  {strat_name}: no configs with 3+ trades")
        continue
    strat_results.sort(key=lambda x: (-x['pf'], -x['wr']))
    best = strat_results[0]
    baseline = next((r for r in all_results if r['strategy'] == strat_name and r['config'] == 'baseline'), None)
    print(f"\n  {strat_name}:")
    print(f"    Best: {best['config']} | {best['trades']} trades, WR={best['wr']}%, PF={best['pf']}")
    if baseline and baseline['trades'] > 0:
        print(f"    Base: {baseline['config']} | {baseline['trades']} trades, WR={baseline['wr']}%, PF={baseline['pf']}")
        if best['pf'] > baseline['pf']:
            print(f"    FR improvement: PF +{best['pf'] - baseline['pf']:.2f}, WR +{best['wr'] - baseline['wr']:.1f}pp")
        else:
            print(f"    FR effect: PF {best['pf'] - baseline['pf']:+.2f} (no improvement)")

# Save
with open("reports/fr_state_filter_test.json", "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\n  Saved to reports/fr_state_filter_test.json")
