#!/usr/bin/env python3
"""
Whale Watch Combo Backtest
==========================
Tests whale_watch paired with ALL event-based strategies.
Uses the scanner's actual signal generation (scan_signal).
Period: May 13 - Jul 6, 2026 (where derivatives data exists)
"""
import sys, os, json, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data
from src.utils.indicators import calc_atr, calc_vol_ratio, calc_ema, calc_rsi, calc_macd
from scripts.scanner import scan_signal, compute_indicators

# ============================================================
# CONFIG
# ============================================================
START_DATE = "2026-05-13"
END_DATE = "2026-07-06"
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.0005  # taker fee
STEP = 4  # every 1h

# Event strategies to test with whale_watch
EVENT_STRATEGIES = [
    "failed_breakout",
    "structural_break", 
    "squeeze_breakout",
    "positioning_fade",
    "orderbook_imbalance",
    "trade_flow",
    "funding_arb",
    "regime_switch",
    "liquidity_grab",
    "judas_sweep",
    "taker_flow",
    "vol_rotation",
    "scalp_v2",
    "momentum_v2",
    "cross_asset",
    "mtf_confluence",
    "power_of_3",
    "bb_mom6",
]

# ============================================================
# LOAD DATA
# ============================================================
print("=" * 70)
print("WHALE WATCH COMBO BACKTEST")
print(f"Period: {START_DATE} → {END_DATE}")
print("=" * 70)

print("\n[1/3] Loading data...")
df_raw = load_data("eth_15m_merged.csv")
df_raw['Open time'] = pd.to_datetime(df_raw['Open time'])

cfg = CONFIG
print("[2/3] Computing indicators (this takes a few minutes)...")
t0 = time.time()
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_raw.copy(), config=cfg)
print(f"  Indicators done in {time.time()-t0:.0f}s")

mask = (df_15m['Open time'] >= START_DATE) & (df_15m['Open time'] <= END_DATE)
indices = df_15m[mask].index.tolist()
start_idx = max(indices[0], 500) if indices else 500
end_idx = indices[-1] if indices else len(df_15m) - 1

print(f"  Period: {df_15m['Open time'].iloc[start_idx]} to {df_15m['Open time'].iloc[end_idx]}")
print(f"  Bars: {end_idx - start_idx + 1} | Step: {STEP}")

# ============================================================
# BACKTEST ENGINE
# ============================================================
def run_combo_backtest(event_strategy, use_whale=True, use_sweep_filter=False, sweep_threshold=0.0, use_fr_filter=False, fr_threshold=0.0):
    """Run backtest for one event strategy + whale_watch combo."""
    trades = []
    capital = INITIAL_CAPITAL
    peak = capital
    max_dd = 0
    open_positions = []
    total_signals = 0
    cooldown_until = {}

    for i in range(start_idx, end_idx + 1, STEP):
        row = df_15m.iloc[i]
        ts = row['Open time']
        price = float(row['Close'])
        high = float(row['High'])
        low = float(row['Low'])

        # Close open positions
        closed = []
        for pos in open_positions:
            bars_held = i - pos['entry_idx']
            max_bars = pos['hold_hours'] * 4
            
            hit_tp = hit_sl = timeout = False
            if pos['direction'] == 'LONG':
                if high >= pos['tp']: hit_tp = True
                elif low <= pos['sl']: hit_sl = True
            else:
                if low <= pos['tp']: hit_tp = True
                elif high >= pos['sl']: hit_sl = True
            
            if bars_held >= max_bars:
                timeout = True
            
            if hit_tp or hit_sl or timeout:
                if hit_tp:
                    exit_price = pos['tp']
                    outcome = 'WIN'
                elif hit_sl:
                    exit_price = pos['sl']
                    outcome = 'LOSS'
                else:
                    exit_price = price
                    outcome = 'WIN' if ((pos['direction'] == 'LONG' and price > pos['entry']) or 
                                        (pos['direction'] == 'SHORT' and price < pos['entry'])) else 'LOSS'
                
                pnl_pct = ((exit_price - pos['entry']) / pos['entry'] * 100) if pos['direction'] == 'LONG' \
                          else ((pos['entry'] - exit_price) / pos['entry'] * 100)
                pnl_dollar = pos['size'] * pnl_pct / 100
                fee = pos['size'] * FEE_RATE * 2
                net_pnl = pnl_dollar - fee
                capital += net_pnl
                
                if capital > peak: peak = capital
                dd = (peak - capital) / peak * 100 if peak > 0 else 0
                if dd > max_dd: max_dd = dd
                
                trades.append({
                    'time': str(ts), 'direction': pos['direction'],
                    'entry': pos['entry'], 'exit': exit_price,
                    'pnl_pct': pnl_pct, 'pnl_dollar': net_pnl,
                    'outcome': outcome, 'bars': bars_held,
                    'strategy': event_strategy,
                })
                closed.append(pos)
        
        for c in closed:
            open_positions.remove(c)
        
        if capital <= 0:
            break
        
        # Check cooldown
        if event_strategy in cooldown_until and i < cooldown_until[event_strategy]:
            continue
        
        # Skip if already have position from this strategy
        if any(p['strategy'] == event_strategy for p in open_positions):
            continue
        
        # Run scanner
        try:
            result = scan_signal(df_15m, df_1h, df_2h, df_4h, df_1d, config=cfg)
        except Exception as e:
            continue
        
        strategies = result.get('strategies', {})
        
        # Check if the event strategy fired
        event_sig = strategies.get(event_strategy)
        if not event_sig or not event_sig.get('direction'):
            continue
        
        direction = event_sig['direction']
        conviction = event_sig.get('conviction', 0.5)
        
        # Whale filter
        if use_whale:
            deriv = result.get('derivatives', {})
            ls_ratio = deriv.get('ls_ratio', 1.0) if deriv else 1.0
            
            # Whale must agree with direction
            if direction == 'SHORT' and ls_ratio <= 1.0:
                continue  # whale is long, disagrees
            if direction == 'LONG' and ls_ratio >= 1.0:
                continue  # whale is short, disagrees
        
        # FR filter
        if use_fr_filter:
            deriv = result.get('derivatives', {})
            fr = deriv.get('funding_rate', 0) if deriv else 0
            if direction == 'SHORT' and fr < fr_threshold:
                continue
            if direction == 'LONG' and fr > -fr_threshold:
                continue
        
        total_signals += 1
        
        # Entry
        entry = price
        atr = float(row.get('atr', 0)) if 'atr' in row else 0
        if atr <= 0:
            atr = abs(float(row['High']) - float(row['Low']))
        if atr <= 0:
            continue
        
        # TP/SL from strategy config
        tp_mult = 2.0
        sl_mult = 1.0
        hold_hours = 8
        
        if direction == 'LONG':
            tp = entry + tp_mult * atr
            sl = entry - sl_mult * atr
        else:
            tp = entry - tp_mult * atr
            sl = entry + sl_mult * atr
        
        size = capital * RISK_PCT * LEVERAGE
        
        open_positions.append({
            'entry_idx': i, 'entry': entry, 'direction': direction,
            'tp': tp, 'sl': sl, 'size': size, 'hold_hours': hold_hours,
            'strategy': event_strategy,
        })
        
        cooldown_until[event_strategy] = i + 6  # 1.5h cooldown
    
    # Compute metrics
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0, 'signals': total_signals}
    
    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    total_win = sum(t['pnl_dollar'] for t in wins)
    total_loss = sum(abs(t['pnl_dollar']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(len(wins) / len(trades) * 100, 1) if trades else 0,
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
        'pnl_pct': round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'final_capital': round(capital, 2),
        'max_dd': round(max_dd, 2),
        'signals': total_signals,
    }

# ============================================================
# RUN ALL COMBOS
# ============================================================
print("\n[3/3] Running backtests...")
print(f"  Testing {len(EVENT_STRATEGIES)} event strategies × 3 configs each\n")

results = []

for strat in EVENT_STRATEGIES:
    print(f"  Testing {strat}...", end="", flush=True)
    
    # Config 1: Event only (no whale)
    m1 = run_combo_backtest(strat, use_whale=False)
    
    # Config 2: Event + Whale
    m2 = run_combo_backtest(strat, use_whale=True)
    
    # Config 3: Event + Whale + FR filter
    m3 = run_combo_backtest(strat, use_whale=True, use_fr_filter=True, fr_threshold=0.00005)
    
    results.append({'strategy': strat, 'config': 'event_only', **m1})
    results.append({'strategy': strat, 'config': 'event+whale', **m2})
    results.append({'strategy': strat, 'config': 'event+whale+FR', **m3})
    
    # Print summary line
    if m2['trades'] > 0:
        hit = " ***" if m2['pf'] >= 2.0 and m2['wr'] >= 75 else ""
        print(f"  event={m1['trades']:>3d}t {m1['wr']:>5.1f}% PF={m1['pf']:>5.2f} | "
              f"+whale={m2['trades']:>3d}t {m2['wr']:>5.1f}% PF={m2['pf']:>5.2f} | "
              f"+FR={m3['trades']:>3d}t {m3['wr']:>5.1f}% PF={m3['pf']:>5.2f}{hit}")
    else:
        print(f"  event={m1['trades']:>3d}t | +whale=0t | +FR=0t  (no signals)")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY — Best Combos with Whale Watch")
print("=" * 70)

# Sort by PF, filter to meaningful trades
valid = [r for r in results if r['trades'] >= 3 and r['config'] == 'event+whale']
valid.sort(key=lambda x: (-x['pf'], -x['wr']))

print(f"\n  {'Strategy':>20s} | {'Config':>15s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s} | {'MaxDD':>6s}")
print("  " + "-" * 90)
for r in valid[:20]:
    hit = " ***" if r['pf'] >= 2.0 and r['wr'] >= 75 else ""
    print(f"  {r['strategy']:>20s} | {r['config']:>15s} | {r['trades']:>6d} | {r['wr']:>5.1f}% | {r['pf']:>6.2f} | ${r['pnl']:>+7.2f} | {r['pnl_pct']:>+6.2f}% | {r['max_dd']:>5.2f}%{hit}")

# Best with FR filter
valid_fr = [r for r in results if r['trades'] >= 3 and r['config'] == 'event+whale+FR']
valid_fr.sort(key=lambda x: (-x['pf'], -x['wr']))

if valid_fr:
    print(f"\n  With FR >= 0.00005 filter:")
    print(f"  {'Strategy':>20s} | {'Config':>15s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s}")
    print("  " + "-" * 75)
    for r in valid_fr[:10]:
        print(f"  {r['strategy']:>20s} | {r['config']:>15s} | {r['trades']:>6d} | {r['wr']:>5.1f}% | {r['pf']:>6.2f} | ${r['pnl']:>+7.2f} | {r['pnl_pct']:>+6.2f}%")

# Target hits
targets = [r for r in results if r['pf'] >= 2.0 and r['wr'] >= 75 and r['trades'] >= 3]
if targets:
    print(f"\n  *** TARGET HIT (PF>=2.0, WR>=75%, trades>=3): ***")
    for r in targets:
        print(f"    {r['strategy']} ({r['config']}): {r['trades']} trades, WR={r['wr']}%, PF={r['pf']}")
else:
    print(f"\n  No combo hit PF>=2.0 AND WR>=75% with >= 3 trades")

# Save
report_path = "/root/.openclaw/workspace/jimi_audit/reports/whale_combo_backtest.json"
with open(report_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {report_path}")
