#!/usr/bin/env python3
"""
FR State Filter Test — failed_breakout + judas_sweep
Tests whether FR conditioning improves event strategy performance.
Uses scanner's actual signal generation.
"""
import sys, os, time, json, csv
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data
from scripts.scanner import compute_indicators

START = "2026-05-13"
END = "2026-07-06"
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.0005
HOLD_BARS = 32  # 8 hours

# ============================================================
# LOAD DATA
# ============================================================
print("=" * 80)
print("FR STATE FILTER TEST — failed_breakout + judas_sweep")
print(f"Period: {START} -> {END}")
print("=" * 80)

print("\n[1/4] Loading ETH data...")
df_raw = load_data("eth_15m_merged.csv")
df_raw['Open time'] = pd.to_datetime(df_raw['Open time'])

cfg = CONFIG
print("[2/4] Computing indicators...")
t0 = time.time()
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_raw.copy(), config=cfg)
print(f"  Done in {time.time()-t0:.0f}s")

print("[3/4] Loading derivatives...")
deriv_cache = {}
with open("data/derivatives_history/derivatives_collected.csv") as f:
    for row in csv.DictReader(f):
        dt = datetime.fromisoformat(row['timestamp'])
        dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        deriv_cache[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
            'ls_ratio': float(row['ls_ratio']),
            'funding_rate': float(row['funding_rate']),
        }
print(f"  {len(deriv_cache)} snapshots")

def find_deriv(ts_str, max_min=30):
    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    for off in range(0, max_min + 1, 1):
        for d in [dt - timedelta(minutes=off), dt + timedelta(minutes=off)]:
            k = d.strftime('%Y-%m-%d %H:%M:%S')
            if k in deriv_cache:
                return deriv_cache[k]
    return None

mask = (df_15m['Open time'] >= START) & (df_15m['Open time'] <= END)
indices = df_15m[mask].index.tolist()
start_idx = max(indices[0], 500)
end_idx = indices[-1]
print(f"  Bars: {end_idx - start_idx + 1}")

# ============================================================
# BACKTEST ENGINE
# ============================================================
def run_backtest(strategy_name, fr_filter=None, fr_threshold=0.0, whale_filter=False, ema_filter=True, tp_mult=2.0, sl_mult=1.0, hold=32):
    """
    Run backtest for one strategy with optional FR/whale/EMA filters.
    
    fr_filter: None, 'confirm' (FR agrees with direction), 'extreme' (|FR| > threshold)
    whale_filter: True = L/S ratio must agree with direction
    ema_filter: True = EMA200 trend filter
    """
    from scripts.scanner import scan_signal
    
    trades = []
    capital = INITIAL_CAPITAL
    peak = capital
    max_dd = 0
    open_pos = None
    cooldown_until = 0
    signals_fired = 0
    signals_filtered = {'fr': 0, 'whale': 0, 'ema': 0, 'no_signal': 0}

    for i in range(start_idx, end_idx + 1):
        row = df_15m.iloc[i]
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
                if hit_tp:
                    exit_p = open_pos['tp']; outcome = 'WIN'
                elif hit_sl:
                    exit_p = open_pos['sl']; outcome = 'LOSS'
                else:
                    exit_p = price
                    outcome = 'WIN' if ((open_pos['dir'] == 'LONG' and price > open_pos['entry']) or
                                        (open_pos['dir'] == 'SHORT' and price < open_pos['entry'])) else 'LOSS'

                pnl_pct = ((exit_p - open_pos['entry']) / open_pos['entry'] * 100) if open_pos['dir'] == 'LONG' \
                          else ((open_pos['entry'] - exit_p) / open_pos['entry'] * 100)
                size = open_pos['size']
                net_pnl = size * pnl_pct / 100 - size * FEE_RATE * 2
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

        # Run scanner
        try:
            result = scan_signal(df_15m, df_1h, df_2h, df_4h, df_1d, config=cfg)
        except:
            continue

        strategies = result.get('strategies', {})
        sig = strategies.get(strategy_name)
        if not sig or not sig.get('direction'):
            signals_filtered['no_signal'] += 1
            continue

        direction = sig['direction']
        deriv = find_deriv(ts)
        if not deriv:
            continue

        fr = deriv['funding_rate']
        ls_ratio = deriv['ls_ratio']

        # FR filter
        if fr_filter == 'confirm':
            if direction == 'SHORT' and fr <= 0:
                signals_filtered['fr'] += 1; continue
            if direction == 'LONG' and fr >= 0:
                signals_filtered['fr'] += 1; continue
        elif fr_filter == 'extreme':
            if abs(fr) < fr_threshold:
                signals_filtered['fr'] += 1; continue
        elif fr_filter == 'confirm_extreme':
            if direction == 'SHORT' and (fr <= 0 or fr < fr_threshold):
                signals_filtered['fr'] += 1; continue
            if direction == 'LONG' and (fr >= 0 or abs(fr) < fr_threshold):
                signals_filtered['fr'] += 1; continue

        # Whale filter
        if whale_filter:
            if direction == 'SHORT' and ls_ratio <= 1.0:
                signals_filtered['whale'] += 1; continue
            if direction == 'LONG' and ls_ratio >= 1.0:
                signals_filtered['whale'] += 1; continue

        # EMA filter
        if ema_filter:
            ema_200 = float(df_1h['ema_200'].iloc[len(df_1h)-1]) if 'ema_200' in df_1h.columns else 0
            if ema_200 > 0:
                if direction == 'LONG' and price < ema_200:
                    signals_filtered['ema'] += 1; continue
                if direction == 'SHORT' and price > ema_200:
                    signals_filtered['ema'] += 1; continue

        signals_fired += 1

        atr = float(row.get('atr', 0)) if 'atr' in row else 0
        if atr <= 0: atr = abs(high - low)
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

    # Metrics
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0,
                'signals_fired': signals_fired, 'signals_filtered': signals_filtered}

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
        'signals_fired': signals_fired,
        'signals_filtered': signals_filtered,
    }

# ============================================================
# TEST MATRIX
# ============================================================
print("\n[4/4] Running backtests...")

strategies = ['failed_breakout', 'judas_sweep']
configs = [
    {'fr_filter': None, 'whale_filter': False, 'ema_filter': True, 'label': 'baseline (EMA only)'},
    {'fr_filter': None, 'whale_filter': True, 'ema_filter': True, 'label': '+whale'},
    {'fr_filter': 'confirm', 'whale_filter': False, 'ema_filter': True, 'label': '+FR confirm'},
    {'fr_filter': 'confirm', 'whale_filter': True, 'ema_filter': True, 'label': '+whale+FR confirm'},
    {'fr_filter': 'extreme', 'fr_threshold': 0.00005, 'whale_filter': False, 'ema_filter': True, 'label': '+FR>5e-5'},
    {'fr_filter': 'extreme', 'fr_threshold': 0.00005, 'whale_filter': True, 'ema_filter': True, 'label': '+whale+FR>5e-5'},
    {'fr_filter': 'confirm', 'whale_filter': False, 'ema_filter': False, 'label': '+FR confirm (no EMA)'},
    {'fr_filter': 'confirm', 'whale_filter': True, 'ema_filter': False, 'label': '+whale+FR confirm (no EMA)'},
]

all_results = []

for strat in strategies:
    print(f"\n{'='*80}")
    print(f"  STRATEGY: {strat}")
    print(f"{'='*80}")
    print(f"  {'Config':<35s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s} | {'MaxDD':>6s} | {'Sig':>4s}")
    print("  " + "-" * 100)

    for cfg_item in configs:
        m = run_backtest(
            strat,
            fr_filter=cfg_item.get('fr_filter'),
            fr_threshold=cfg_item.get('fr_threshold', 0.0),
            whale_filter=cfg_item.get('whale_filter', False),
            ema_filter=cfg_item.get('ema_filter', True),
        )
        m['strategy'] = strat
        m['config'] = cfg_item['label']
        all_results.append(m)

        hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
        print(f"  {cfg_item['label']:<35s} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f} | {m['pnl_pct']:>+6.2f}% | {m['max_dd']:>5.2f}% | {m['signals_fired']:>4d}{hit}")

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*80}")
print("SUMMARY — Best configs per strategy")
print(f"{'='*80}")

for strat in strategies:
    strat_results = [r for r in all_results if r['strategy'] == strat and r['trades'] >= 3]
    if not strat_results:
        print(f"\n  {strat}: no configs with 3+ trades")
        continue
    
    # Sort by PF
    strat_results.sort(key=lambda x: (-x['pf'], -x['wr']))
    best = strat_results[0]
    print(f"\n  {strat}:")
    print(f"    Best: {best['config']} | {best['trades']} trades, WR={best['wr']}%, PF={best['pf']}, PnL=${best['pnl']:+.2f}")
    
    # Compare with baseline
    baseline = next((r for r in all_results if r['strategy'] == strat and r['config'] == 'baseline (EMA only)'), None)
    if baseline and baseline['trades'] > 0:
        print(f"    Base: {baseline['config']} | {baseline['trades']} trades, WR={baseline['wr']}%, PF={baseline['pf']}, PnL=${baseline['pnl']:+.2f}")
        if best['pf'] > baseline['pf']:
            print(f"    Delta: PF +{best['pf'] - baseline['pf']:.2f}, WR +{best['wr'] - baseline['wr']:.1f}pp")
        else:
            print(f"    Delta: PF {best['pf'] - baseline['pf']:+.2f}, WR {best['wr'] - baseline['wr']:+.1f}pp (no improvement)")

# Save
with open("reports/fr_state_filter_test.json", "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\n  Saved to reports/fr_state_filter_test.json")
