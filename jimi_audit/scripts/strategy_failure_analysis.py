#!/usr/bin/env python3
"""
Strategy Failure Analysis: Feb 2 - Jul 5, 2026
Analyzes each strategy individually for failure patterns.
"""
import sys, os, json, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data, resample_ohlcv
from src.utils.indicators import calc_atr, calc_vol_ratio, calc_ema, calc_rsi, calc_macd
from scripts.scanner import scan_signal, compute_indicators

START_DATE = "2026-02-02"
END_DATE = "2026-07-05"
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.001
STEP = 4  # every 1h (4 x 15m bars)

# All 23 strategies with their configs
ALL_STRATEGIES = {
    "failed_breakout": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.7, "direction": "SHORT"},
    "squeeze_breakout": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "cascade": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "positioning_fade": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": "LONG"},
    "kill_zone": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "liquidity_grab": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "taker_flow": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "regime_switch": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": "SHORT"},
    "power_of_3": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "structural_break": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.5, "direction": "SHORT"},
    "cross_asset": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 4, "min_conv": 0.5, "direction": None},
    "macro_surprise": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "funding_arb": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12, "min_conv": 0.5, "direction": None},
    "whale_watch": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 8, "min_conv": 0.5, "direction": "LONG"},
    "vol_rotation": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "mtf_confluence": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "scalp_v2": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "momentum_v2": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "orderbook_imbalance": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5, "direction": "LONG"},
    "liquidation_cascade": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "trade_flow": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5, "direction": "LONG"},
    "judas_sweep": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "bb_mom6": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
}

print("Loading data...")
df_raw = load_data("eth_15m_merged.csv")
df_raw['Open time'] = pd.to_datetime(df_raw['Open time'])

cfg = CONFIG
print("Computing indicators...")
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_raw.copy(), config=cfg)

mask = (df_15m['Open time'] >= START_DATE) & (df_15m['Open time'] <= END_DATE)
indices = df_15m[mask].index.tolist()
start_idx = max(indices[0], 500) if indices else 500
end_idx = indices[-1] if indices else len(df_15m) - 1

print(f"  Period: {df_15m['Open time'].iloc[start_idx]} to {df_15m['Open time'].iloc[end_idx]}")
print(f"  Bars: {end_idx - start_idx + 1} | Step: {STEP}")

# Per-strategy tracking
strat_trades = defaultdict(list)
strat_signals = defaultdict(int)
strat_no_signal = defaultdict(int)
total_scans = 0

t0 = time.time()
print("Running backtest...")

for i in range(start_idx, end_idx + 1, STEP):
    if time.time() - t0 > 800:
        print(f"  TIMEOUT at bar {i}")
        break
    
    if (i - start_idx) % 200 == 0:
        pct = (i - start_idx) / (end_idx - start_idx) * 100
        elapsed = time.time() - t0
        fired_total = sum(strat_signals.values())
        print(f"  {pct:.0f}% | bar {i} | total_signals={fired_total} | {elapsed:.0f}s")
    
    row = df_15m.iloc[i]
    ts = row['Open time']
    price = float(row['Close'])
    high = float(row['High'])
    low = float(row['Low'])
    
    # Run scanner at this bar
    try:
        result = scan_signal(df_15m.iloc[:i+1], df_1h, df_2h, df_4h, df_1d, config=cfg)
    except Exception as e:
        continue
    
    total_scans += 1
    
    # Get multi-strategy signals
    multi = result.get('multi_strategy') or {}
    all_sigs = multi.get('all_signals', [])
    
    # Track which strategies fired
    fired_strats = set()
    for sig in all_sigs:
        if not isinstance(sig, dict):
            continue
        sn = sig.get('strategy', '')
        direction = sig.get('direction')
        conviction = sig.get('conviction', 0) or 0
        
        sconfig = ALL_STRATEGIES.get(sn)
        if not sconfig:
            continue
        
        if not direction or conviction < sconfig['min_conv']:
            strat_no_signal[sn] += 1
            continue
        
        if sconfig['direction'] and direction != sconfig['direction']:
            strat_no_signal[sn] += 1
            continue
        
        fired_strats.add(sn)
        strat_signals[sn] += 1
        
        entry = sig.get('entry', price)
        sl = sig.get('sl', 0)
        tp1 = sig.get('tp1', 0)
        
        if not entry or not sl or not tp1:
            continue
        
        # Simulate trade outcome
        hold_bars = sconfig['hold_hours'] * 4
        outcome = 'TIMEOUT'
        exit_price = entry
        
        for j in range(1, min(hold_bars + 1, end_idx - i + 1)):
            bar = df_15m.iloc[i + j]
            h = float(bar['High'])
            l = float(bar['Low'])
            
            if direction == 'LONG':
                if h >= tp1:
                    outcome = 'WIN'
                    exit_price = tp1
                    break
                if l <= sl:
                    outcome = 'LOSS'
                    exit_price = sl
                    break
            else:
                if l <= tp1:
                    outcome = 'WIN'
                    exit_price = tp1
                    break
                if h >= sl:
                    outcome = 'LOSS'
                    exit_price = sl
                    break
        
        if outcome == 'TIMEOUT':
            if i + hold_bars < len(df_15m):
                exit_price = float(df_15m.iloc[i + hold_bars]['Close'])
        
        # Calculate PnL
        if direction == 'LONG':
            pnl_pct = (exit_price - entry) / entry * 100
        else:
            pnl_pct = (entry - exit_price) / entry * 100
        
        strat_trades[sn].append({
            'ts': str(ts),
            'direction': direction,
            'entry': round(entry, 2),
            'sl': round(sl, 2),
            'tp': round(tp1, 2),
            'exit': round(exit_price, 2),
            'outcome': outcome,
            'pnl_pct': round(pnl_pct, 4),
            'conviction': round(conviction, 4),
            'price_at_signal': round(price, 2),
        })
    
    # Track strategies that didn't fire
    for sn in ALL_STRATEGIES:
        if sn not in fired_strats:
            strat_no_signal[sn] += 1

# Save results
output = {
    'period': f'{START_DATE} to {END_DATE}',
    'total_scans': total_scans,
    'strategies': {}
}

for sn in sorted(ALL_STRATEGIES.keys()):
    trades = strat_trades[sn]
    signals = strat_signals.get(sn, 0)
    no_signal = strat_no_signal.get(sn, 0)
    
    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    timeouts = [t for t in trades if t['outcome'] == 'TIMEOUT']
    
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    avg_pnl = np.mean([t['pnl_pct'] for t in trades]) if trades else 0
    
    # Failure pattern analysis
    loss_long = [t for t in losses if t['direction'] == 'LONG']
    loss_short = [t for t in losses if t['direction'] == 'SHORT']
    win_long = [t for t in wins if t['direction'] == 'LONG']
    win_short = [t for t in wins if t['direction'] == 'SHORT']
    
    # Consecutive losses
    max_consec_loss = 0
    curr_consec = 0
    for t in trades:
        if t['outcome'] == 'LOSS':
            curr_consec += 1
            max_consec_loss = max(max_consec_loss, curr_consec)
        else:
            curr_consec = 0
    
    # Monthly breakdown
    monthly = defaultdict(lambda: {'w': 0, 'l': 0, 't': 0})
    for t in trades:
        month = t['ts'][:7]
        if t['outcome'] == 'WIN':
            monthly[month]['w'] += 1
        elif t['outcome'] == 'LOSS':
            monthly[month]['l'] += 1
        else:
            monthly[month]['t'] += 1
    
    output['strategies'][sn] = {
        'total_signals': signals,
        'no_signal_count': no_signal,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'timeouts': len(timeouts),
        'win_rate': round(wr, 1),
        'avg_pnl_pct': round(avg_pnl, 4),
        'avg_win_pct': round(avg_win, 4),
        'avg_loss_pct': round(avg_loss, 4),
        'max_consec_losses': max_consec_loss,
        'direction_breakdown': {
            'long_wins': len(win_long),
            'long_losses': len(loss_long),
            'short_wins': len(win_short),
            'short_losses': len(loss_short),
        },
        'monthly': {k: dict(v) for k, v in sorted(monthly.items())},
        'losing_trades': losses[-20:] if losses else [],  # last 20 losses
        'winning_trades': wins[-10:] if wins else [],  # last 10 wins
    }

# Save
with open('/root/.openclaw/workspace/jimi_audit/data/strategy_failure_analysis.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

# Print summary
print("\n" + "=" * 80)
print(f"STRATEGY FAILURE ANALYSIS: {START_DATE} to {END_DATE}")
print(f"Total scans: {total_scans}")
print("=" * 80)

for sn in sorted(ALL_STRATEGIES.keys()):
    s = output['strategies'][sn]
    print(f"\n{'─' * 60}")
    print(f"  {sn.upper()}")
    print(f"{'─' * 60}")
    print(f"  Signals fired: {s['total_signals']} | No signal: {s['no_signal_count']}")
    print(f"  Trades: {s['trades']} | W: {s['wins']} | L: {s['losses']} | T: {s['timeouts']}")
    print(f"  Win Rate: {s['win_rate']}% | Avg PnL: {s['avg_pnl_pct']:.2f}%")
    print(f"  Avg Win: {s['avg_win_pct']:.2f}% | Avg Loss: {s['avg_loss_pct']:.2f}%")
    print(f"  Max Consec Losses: {s['max_consec_losses']}")
    d = s['direction_breakdown']
    print(f"  LONG: {d['long_wins']}W/{d['long_losses']}L | SHORT: {d['short_wins']}W/{d['short_losses']}L")
    if s['monthly']:
        print(f"  Monthly: ", end="")
        for m, v in s['monthly'].items():
            print(f"{m}: {v['w']}W/{v['l']}L/{v['t']}T ", end="")
        print()

print("\n✅ Full analysis saved to data/strategy_failure_analysis.json")
