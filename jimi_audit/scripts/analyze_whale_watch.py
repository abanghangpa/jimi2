#!/usr/bin/env python3
"""
Whale Watch Strategy Failure Analysis
Period: Feb 1, 2026 -> Jul 6, 2026
"""
import sys, os, csv, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

import numpy as np
import pandas as pd

START = "2026-02-01"
END = "2026-07-06"
TP_PCT = 0.02
SL_PCT = 0.015
HOLD_BARS = 32
MIN_CONV = 0.5

print("=" * 70)
print("WHALE WATCH STRATEGY - FAILURE ANALYSIS")
print(f"Period: {START} -> {END}")
print(f"TP: {TP_PCT*100}% | SL: {SL_PCT*100}% | Hold: {HOLD_BARS} bars (8h)")
print("=" * 70)

print("\n[1/4] Loading ETH 15m data...")
df = pd.read_csv("eth_15m_merged.csv")
df['Open time'] = pd.to_datetime(df['Open time'])
df = df[(df['Open time'] >= START) & (df['Open time'] <= END)].reset_index(drop=True)
print(f"  Loaded {len(df)} bars from {df['Open time'].iloc[0]} to {df['Open time'].iloc[-1]}")

print("\n[2/4] Loading derivatives data...")
deriv_cache = {}
deriv_file = "data/derivatives_history/derivatives_collected.csv"
if os.path.exists(deriv_file):
    with open(deriv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("timestamp", "")
            ts = ts_raw[:16].replace("T", " ")
            ls = float(row.get("ls_ratio", 0) or 0)
            if ls > 0:
                deriv_cache[ts] = {
                    "ls_ratio": ls,
                    "long_pct": float(row.get("long_pct", 0) or 0),
                    "short_pct": float(row.get("short_pct", 0) or 0),
                    "top_ls_ratio": float(row.get("top_ls_ratio", 0) or 0),
                    "top_long_pct": float(row.get("top_long_pct", 0) or 0),
                    "top_short_pct": float(row.get("top_short_pct", 0) or 0),
                    "oi": float(row.get("oi", 0) or 0),
                    "oi_usd": float(row.get("oi_usd", 0) or 0),
                    "funding_rate": float(row.get("funding_rate", 0) or 0),
                }
    print(f"  Loaded {len(deriv_cache)} derivatives snapshots")
    sorted_ts = sorted(deriv_cache.keys())
    print(f"  Derivatives range: {sorted_ts[0]} -> {sorted_ts[-1]}")
else:
    print("  WARNING: No derivatives data found!")

print("\n[3/4] Aligning derivatives to 15m bars...")

def find_nearest_deriv(bar_time, max_delta_min=30):
    bar_str = bar_time.strftime("%Y-%m-%d %H:%M")
    if bar_str in deriv_cache:
        return deriv_cache[bar_str]
    best = None
    best_delta = timedelta(hours=999)
    for offset_min in range(-max_delta_min, max_delta_min + 1, 1):
        check = (bar_time + timedelta(minutes=offset_min)).strftime("%Y-%m-%d %H:%M")
        if check in deriv_cache:
            delta = abs(timedelta(minutes=offset_min))
            if delta < best_delta:
                best_delta = delta
                best = deriv_cache[check]
    return best

whale_signals = []
bars_with_deriv = 0
bars_without_deriv = 0

for i in range(len(df)):
    bar_time = df['Open time'].iloc[i]
    deriv = find_nearest_deriv(bar_time)
    if deriv:
        bars_with_deriv += 1
        ls = deriv['ls_ratio']
        if ls > 2.1:
            whale = "BEARISH"
        elif ls < 1.9:
            whale = "BULLISH"
        else:
            whale = "NEUTRAL"
        if ls > 2.5:
            positioning = "EXTREME_LONG"
        elif ls > 2.2:
            positioning = "BULLISH"
        elif ls < 1.5:
            positioning = "EXTREME_SHORT"
        elif ls < 1.8:
            positioning = "BEARISH"
        else:
            positioning = "NEUTRAL"
        whale_signals.append({
            'bar_idx': i, 'time': bar_time, 'ls_ratio': ls,
            'whale': whale, 'positioning': positioning,
            'top_ls_ratio': deriv['top_ls_ratio'],
            'oi': deriv['oi'], 'funding_rate': deriv['funding_rate'],
        })
    else:
        bars_without_deriv += 1
        whale_signals.append(None)

print(f"  Bars with derivatives: {bars_with_deriv}")
print(f"  Bars without derivatives: {bars_without_deriv}")

print("\n[4/4] Running strategy and checking outcomes...\n")

trades = []
no_signal_reasons = defaultdict(int)

for i in range(len(df)):
    ws = whale_signals[i]
    if ws is None:
        no_signal_reasons['no_derivatives_data'] += 1
        continue

    whale = ws['whale']
    ls = ws['ls_ratio']
    positioning = ws['positioning']

    if whale == 'NEUTRAL' or whale == '':
        no_signal_reasons['whale_neutral'] += 1
        continue

    if whale == 'BULLISH':
        direction = 'LONG'
    elif whale == 'BEARISH':
        direction = 'SHORT'
    else:
        no_signal_reasons['unknown_whale'] += 1
        continue

    pos_confirm = 0
    if (direction == 'LONG' and positioning in ('BULLISH', 'EXTREME_LONG')) or \
       (direction == 'SHORT' and positioning in ('BEARISH', 'EXTREME_SHORT')):
        pos_confirm = 0.15

    conviction = min(0.40 + pos_confirm + abs(ls - 1.0) * 0.2, 0.80)
    if conviction < MIN_CONV:
        no_signal_reasons['low_conviction'] += 1
        continue

    entry = float(df['Close'].iloc[i])
    if i >= 14:
        highs = df['High'].iloc[i-14:i+1].values.astype(float)
        lows = df['Low'].iloc[i-14:i+1].values.astype(float)
        closes = df['Close'].iloc[i-15:i].values.astype(float)
        trs = []
        for j in range(1, len(highs)):
            tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
            trs.append(tr)
        atr = np.mean(trs)
    else:
        atr = 0

    if atr <= 0:
        no_signal_reasons['no_atr'] += 1
        continue

    if direction == 'LONG':
        tp1 = entry + atr * 1.5
        sl = entry - atr * 1.0
    else:
        tp1 = entry - atr * 1.5
        sl = entry + atr * 1.0

    if direction == 'LONG':
        tp_pct_level = entry * (1 + TP_PCT)
        sl_pct_level = entry * (1 - SL_PCT)
        tp1 = min(tp1, tp_pct_level)
        sl = max(sl, sl_pct_level)
    else:
        tp_pct_level = entry * (1 - TP_PCT)
        sl_pct_level = entry * (1 + SL_PCT)
        tp1 = max(tp1, tp_pct_level)
        sl = min(sl, sl_pct_level)

    outcome = 'TIMEOUT'
    exit_price = entry
    bars_held = HOLD_BARS

    end_idx = min(i + HOLD_BARS, len(df))
    for j in range(i + 1, end_idx):
        high = float(df['High'].iloc[j])
        low = float(df['Low'].iloc[j])
        if direction == 'LONG':
            if high >= tp1:
                outcome = 'WIN'
                exit_price = tp1
                bars_held = j - i
                break
            if low <= sl:
                outcome = 'LOSS'
                exit_price = sl
                bars_held = j - i
                break
        else:
            if low <= tp1:
                outcome = 'WIN'
                exit_price = tp1
                bars_held = j - i
                break
            if high >= sl:
                outcome = 'LOSS'
                exit_price = sl
                bars_held = j - i
                break

    if outcome == 'TIMEOUT':
        exit_price = float(df['Close'].iloc[end_idx - 1])

    if direction == 'LONG':
        pnl_pct = (exit_price - entry) / entry * 100
    else:
        pnl_pct = (entry - exit_price) / entry * 100

    trades.append({
        'bar_idx': i, 'time': ws['time'], 'direction': direction,
        'entry': round(entry, 2), 'tp1': round(tp1, 2), 'sl': round(sl, 2),
        'exit': round(exit_price, 2), 'outcome': outcome,
        'pnl_pct': round(pnl_pct, 4), 'bars_held': bars_held,
        'conviction': round(conviction, 3), 'ls_ratio': round(ls, 4),
        'whale': whale, 'positioning': positioning,
        'top_ls_ratio': round(ws['top_ls_ratio'], 4),
        'oi': ws['oi'], 'funding_rate': ws['funding_rate'],
    })

# === RESULTS ===
print("=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)

total = len(trades)
wins = sum(1 for t in trades if t['outcome'] == 'WIN')
losses = sum(1 for t in trades if t['outcome'] == 'LOSS')
timeouts = sum(1 for t in trades if t['outcome'] == 'TIMEOUT')

print(f"\nTotal signals: {total}")
if total > 0:
    print(f"Wins: {wins} ({wins/total*100:.1f}%)")
    print(f"Losses: {losses} ({losses/total*100:.1f}%)")
    print(f"Timeouts: {timeouts} ({timeouts/total*100:.1f}%)")

    total_pnl = sum(t['pnl_pct'] for t in trades)
    avg_pnl = total_pnl / total
    win_pnl = np.mean([t['pnl_pct'] for t in trades if t['outcome'] == 'WIN']) if wins > 0 else 0
    loss_pnl = np.mean([t['pnl_pct'] for t in trades if t['outcome'] == 'LOSS']) if losses > 0 else 0
    timeout_pnl = np.mean([t['pnl_pct'] for t in trades if t['outcome'] == 'TIMEOUT']) if timeouts > 0 else 0
    
    print(f"\nTotal PnL: {total_pnl:+.2f}%")
    print(f"Avg PnL per trade: {avg_pnl:+.4f}%")
    print(f"Avg WIN: {win_pnl:+.4f}% | Avg LOSS: {loss_pnl:+.4f}% | Avg TIMEOUT: {timeout_pnl:+.4f}%")
    
    gross_wins = sum(t['pnl_pct'] for t in trades if t['outcome'] == 'WIN')
    gross_losses = abs(sum(t['pnl_pct'] for t in trades if t['outcome'] == 'LOSS'))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
    print(f"Profit Factor: {pf:.2f}")

print(f"\n{'-'*70}")
print("NO-SIGNAL REASONS:")
for reason, count in sorted(no_signal_reasons.items(), key=lambda x: -x[1]):
    pct = count / len(df) * 100
    print(f"  {reason}: {count} bars ({pct:.1f}%)")

print(f"\n{'-'*70}")
print("BY DIRECTION:")
for d in ['LONG', 'SHORT']:
    dt = [t for t in trades if t['direction'] == d]
    if not dt:
        continue
    dw = sum(1 for t in dt if t['outcome'] == 'WIN')
    dl = sum(1 for t in dt if t['outcome'] == 'LOSS')
    dtm = sum(1 for t in dt if t['outcome'] == 'TIMEOUT')
    dpnl = sum(t['pnl_pct'] for t in dt)
    print(f"  {d}: {len(dt)} trades | W:{dw} L:{dl} T:{dtm} | PnL: {dpnl:+.2f}%")

print(f"\n{'-'*70}")
print("BY MONTH:")
monthly = defaultdict(list)
for t in trades:
    month = t['time'].strftime('%Y-%m')
    monthly[month].append(t)
for month in sorted(monthly.keys()):
    mt = monthly[month]
    mw = sum(1 for t in mt if t['outcome'] == 'WIN')
    ml = sum(1 for t in mt if t['outcome'] == 'LOSS')
    mtm = sum(1 for t in mt if t['outcome'] == 'TIMEOUT')
    mpnl = sum(t['pnl_pct'] for t in mt)
    print(f"  {month}: {len(mt)} trades | W:{mw} L:{ml} T:{mtm} | PnL: {mpnl:+.2f}%")

print(f"\n{'='*70}")
print("FAILURE ANALYSIS - LOSS TRADES")
print("=" * 70)

loss_trades = [t for t in trades if t['outcome'] == 'LOSS']
if loss_trades:
    ls_at_loss = [t['ls_ratio'] for t in loss_trades]
    print(f"\nTotal loss trades: {len(loss_trades)}")
    print(f"L/S ratio at LOSS - min:{min(ls_at_loss):.4f} max:{max(ls_at_loss):.4f} avg:{np.mean(ls_at_loss):.4f}")
    conv_at_loss = [t['conviction'] for t in loss_trades]
    print(f"Conviction at LOSS - min:{min(conv_at_loss):.3f} max:{max(conv_at_loss):.3f} avg:{np.mean(conv_at_loss):.3f}")
    bars_to_loss = [t['bars_held'] for t in loss_trades]
    print(f"Bars to LOSS - min:{min(bars_to_loss)} max:{max(bars_to_loss)} avg:{np.mean(bars_to_loss):.1f}")
    
    print(f"\nTop 5 Worst Losses:")
    worst = sorted(loss_trades, key=lambda t: t['pnl_pct'])[:5]
    for t in worst:
        print(f"  {t['time']} | {t['direction']} @ ${t['entry']:.2f} -> ${t['exit']:.2f} | "
              f"PnL: {t['pnl_pct']:+.2f}% | ls={t['ls_ratio']:.4f} whale={t['whale']} pos={t['positioning']}")

print(f"\n{'='*70}")
print("WIN ANALYSIS")
print("=" * 70)
win_trades = [t for t in trades if t['outcome'] == 'WIN']
if win_trades:
    ls_at_win = [t['ls_ratio'] for t in win_trades]
    print(f"L/S ratio at WIN - min:{min(ls_at_win):.4f} max:{max(ls_at_win):.4f} avg:{np.mean(ls_at_win):.4f}")
    conv_at_win = [t['conviction'] for t in win_trades]
    print(f"Conviction at WIN - min:{min(conv_at_win):.3f} max:{max(conv_at_win):.3f} avg:{np.mean(conv_at_win):.3f}")
    print(f"\nTop 5 Best Wins:")
    best = sorted(win_trades, key=lambda t: -t['pnl_pct'])[:5]
    for t in best:
        print(f"  {t['time']} | {t['direction']} @ ${t['entry']:.2f} -> ${t['exit']:.2f} | "
              f"PnL: {t['pnl_pct']:+.2f}% | ls={t['ls_ratio']:.4f} whale={t['whale']} pos={t['positioning']}")

print(f"\n{'='*70}")
print("ALL TRADES (last 20)")
print("=" * 70)
for t in trades[-20:]:
    icon = "WIN" if t['outcome'] == 'WIN' else ("LOSS" if t['outcome'] == 'LOSS' else "TIME")
    print(f"  {icon:4s} {t['time']} | {t['direction']:5s} @ ${t['entry']:>8.2f} -> ${t['exit']:>8.2f} | "
          f"PnL: {t['pnl_pct']:+.2f}% | ls={t['ls_ratio']:.4f} conv={t['conviction']:.3f}")

print(f"\n{'='*70}")
print("KEY INSIGHTS & RECOMMENDATIONS")
print("=" * 70)

if total > 0:
    bull_trades = [t for t in trades if t['whale'] == 'BULLISH']
    bear_trades = [t for t in trades if t['whale'] == 'BEARISH']
    if bull_trades:
        bull_wr = sum(1 for t in bull_trades if t['outcome'] == 'WIN') / len(bull_trades) * 100
        print(f"\n1. BULLISH whale signals: {len(bull_trades)} trades, WR={bull_wr:.1f}%")
    if bear_trades:
        bear_wr = sum(1 for t in bear_trades if t['outcome'] == 'WIN') / len(bear_trades) * 100
        print(f"   BEARISH whale signals: {len(bear_trades)} trades, WR={bear_wr:.1f}%")
    
    high_conv = [t for t in trades if t['conviction'] >= 0.6]
    low_conv = [t for t in trades if t['conviction'] < 0.6]
    if high_conv:
        hc_wr = sum(1 for t in high_conv if t['outcome'] == 'WIN') / len(high_conv) * 100
        print(f"\n2. High conviction (>=0.6): {len(high_conv)} trades, WR={hc_wr:.1f}%")
    if low_conv:
        lc_wr = sum(1 for t in low_conv if t['outcome'] == 'WIN') / len(low_conv) * 100
        print(f"   Low conviction (<0.6): {len(low_conv)} trades, WR={lc_wr:.1f}%")
    
    coverage = bars_with_deriv / len(df) * 100
    print(f"\n3. Derivatives data coverage: {coverage:.1f}% of bars")
    if coverage < 50:
        print(f"   WARNING: LOW COVERAGE - strategy can't fire on {100-coverage:.1f}% of bars")
    
    avg_tp_dist = np.mean([(t['tp1'] - t['entry']) / t['entry'] * 100 if t['direction'] == 'LONG' 
                           else (t['entry'] - t['tp1']) / t['entry'] * 100 for t in trades])
    avg_sl_dist = np.mean([(t['entry'] - t['sl']) / t['entry'] * 100 if t['direction'] == 'LONG'
                           else (t['sl'] - t['entry']) / t['entry'] * 100 for t in trades])
    print(f"\n4. Avg TP distance: {avg_tp_dist:.4f}% | Avg SL distance: {avg_sl_dist:.4f}%")
    if avg_sl_dist > 0:
        print(f"   TP/SL ratio: {avg_tp_dist/avg_sl_dist:.2f}")

print(f"\n{'='*70}")
print("ANALYSIS COMPLETE")
print("=" * 70)
