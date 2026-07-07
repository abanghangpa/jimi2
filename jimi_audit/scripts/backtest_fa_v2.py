#!/usr/bin/env python3
"""
Backtest: funding_arb v2 (actual FR) on ETH 15m data
Period: May 13 - Jul 6, 2026 (where derivatives data exists)
"""
import sys, os, time, json
import numpy as np
import pandas as pd
from datetime import datetime

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
HOLD_BARS = 48  # 12 hours

print("=" * 70)
print("FUNDING ARB V2 BACKTEST")
print(f"Period: {START} -> {END}")
print(f"Capital: ${INITIAL_CAPITAL} | Leverage: {LEVERAGE}x | Risk: {RISK_PCT*100}%")
print("=" * 70)

# Load data
print("\n[1/4] Loading ETH data...")
df_raw = load_data("eth_15m_merged.csv")
df_raw['Open time'] = pd.to_datetime(df_raw['Open time'])

cfg = CONFIG
print("[2/4] Computing indicators...")
t0 = time.time()
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_raw.copy(), config=cfg)
print(f"  Done in {time.time()-t0:.0f}s")

# Load derivatives
print("[3/4] Loading derivatives...")
import csv
from datetime import timedelta

deriv_cache = {}
with open("data/derivatives_history/derivatives_collected.csv") as f:
    for row in csv.DictReader(f):
        ts = row['timestamp']
        dt = datetime.fromisoformat(ts)
        dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        deriv_cache[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
            'ls_ratio': float(row['ls_ratio']),
            'funding_rate': float(row['funding_rate']),
            'oi': float(row.get('oi', 0)),
            'oi_usd': float(row.get('oi_usd', 0)),
        }
print(f"  {len(deriv_cache)} derivative snapshots")

def find_deriv(ts_str, max_min=30):
    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    for off in range(0, max_min + 1, 1):
        for d in [dt - timedelta(minutes=off), dt + timedelta(minutes=off)]:
            k = d.strftime('%Y-%m-%d %H:%M:%S')
            if k in deriv_cache:
                return deriv_cache[k]
    return None

# Filter period
mask = (df_15m['Open time'] >= START) & (df_15m['Open time'] <= END)
indices = df_15m[mask].index.tolist()
start_idx = max(indices[0], 500)
end_idx = indices[-1]

print(f"\n[4/4] Running backtest...")
print(f"  Bars: {end_idx - start_idx + 1}")

# Strategy parameters
FR_EXTREME = 0.00008
FR_MODERATE = 0.00005
TP_MULT = 3.0
SL_MULT = 0.6
COOLDOWN = 24  # bars (6 hours)

trades = []
capital = INITIAL_CAPITAL
peak = capital
max_dd = 0
open_pos = None
cooldown_until = 0
signals_fired = 0
signals_filtered_fr = 0
signals_filtered_whale = 0
signals_filtered_ema = 0

for i in range(start_idx, end_idx + 1):
    row = df_15m.iloc[i]
    ts = str(row['Open time'])
    price = float(row['Close'])
    high = float(row['High'])
    low = float(row['Low'])

    # Close open position
    if open_pos:
        bars_held = i - open_pos['entry_idx']
        hit_tp = hit_sl = timeout = False

        if open_pos['dir'] == 'LONG':
            if high >= open_pos['tp']: hit_tp = True
            elif low <= open_pos['sl']: hit_sl = True
        else:
            if low <= open_pos['tp']: hit_tp = True
            elif high >= open_pos['sl']: hit_sl = True

        if bars_held >= HOLD_BARS:
            timeout = True

        if hit_tp or hit_sl or timeout:
            if hit_tp:
                exit_p = open_pos['tp']
                outcome = 'WIN'
            elif hit_sl:
                exit_p = open_pos['sl']
                outcome = 'LOSS'
            else:
                exit_p = price
                outcome = 'WIN' if ((open_pos['dir'] == 'LONG' and price > open_pos['entry']) or
                                    (open_pos['dir'] == 'SHORT' and price < open_pos['entry'])) else 'LOSS'

            pnl_pct = ((exit_p - open_pos['entry']) / open_pos['entry'] * 100) if open_pos['dir'] == 'LONG' \
                      else ((open_pos['entry'] - exit_p) / open_pos['entry'] * 100)
            size = open_pos['size']
            pnl_dollar = size * pnl_pct / 100
            fee = size * FEE_RATE * 2
            net_pnl = pnl_dollar - fee
            capital += net_pnl

            if capital > peak: peak = capital
            dd = (peak - capital) / peak * 100 if peak > 0 else 0
            if dd > max_dd: max_dd = dd

            trades.append({
                'time': open_pos['time'], 'dir': open_pos['dir'],
                'entry': open_pos['entry'], 'exit': exit_p,
                'tp': open_pos['tp'], 'sl': open_pos['sl'],
                'pnl_pct': pnl_pct, 'pnl_dollar': net_pnl,
                'outcome': outcome, 'bars': bars_held,
                'fr': open_pos['fr'], 'ls': open_pos['ls'],
            })
            open_pos = None

    if capital <= 0:
        break

    # Skip if in cooldown or already have position
    if open_pos or i < cooldown_until:
        continue

    # Get derivatives
    deriv = find_deriv(ts)
    if not deriv:
        continue

    fr = deriv['funding_rate']
    ls_ratio = deriv['ls_ratio']
    atr = float(row.get('atr', 0)) if 'atr' in row else 0
    if atr <= 0:
        atr = abs(high - low)
    if atr <= 0:
        continue

    ema_200 = float(df_1h['ema_200'].iloc[len(df_1h)-1]) if 'ema_200' in df_1h.columns else 0

    # ── SIGNAL LOGIC ──
    direction = None
    fr_abs = abs(fr)

    if fr > FR_EXTREME:
        direction = 'SHORT'
    elif fr < -FR_EXTREME:
        direction = 'LONG'
    elif fr > FR_MODERATE:
        direction = 'SHORT'
    elif fr < -FR_MODERATE:
        direction = 'LONG'
    else:
        signals_filtered_fr += 1
        continue

    # Whale confirmation
    if direction == 'SHORT' and ls_ratio < 1.0:
        signals_filtered_whale += 1
        continue
    if direction == 'LONG' and ls_ratio > 1.0:
        signals_filtered_whale += 1
        continue

    # EMA200 trend filter
    if ema_200 and ema_200 > 0:
        if direction == 'LONG' and price < ema_200:
            signals_filtered_ema += 1
            continue
        if direction == 'SHORT' and price > ema_200:
            signals_filtered_ema += 1
            continue

    signals_fired += 1

    # Entry
    if direction == 'LONG':
        tp = price + TP_MULT * atr
        sl = price - SL_MULT * atr
    else:
        tp = price - TP_MULT * atr
        sl = price + SL_MULT * atr

    size = capital * RISK_PCT * LEVERAGE

    open_pos = {
        'entry_idx': i, 'entry': price, 'dir': direction,
        'tp': tp, 'sl': sl, 'size': size, 'time': ts,
        'fr': fr, 'ls': ls_ratio,
    }
    cooldown_until = i + COOLDOWN

# ── RESULTS ──
print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)

if not trades:
    print("  NO TRADES")
    print(f"\n  Signals fired: {signals_fired}")
    print(f"  Filtered by FR: {signals_filtered_fr}")
    print(f"  Filtered by whale: {signals_filtered_whale}")
    print(f"  Filtered by EMA: {signals_filtered_ema}")
else:
    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    total_win = sum(t['pnl_dollar'] for t in wins)
    total_loss = sum(abs(t['pnl_dollar']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    wr = len(wins) / len(trades) * 100

    print(f"\n  Trades: {len(trades)} ({len(wins)}W / {len(losses)}L)")
    print(f"  WR: {wr:.1f}%")
    print(f"  PF: {pf:.2f}")
    print(f"  Capital: ${INITIAL_CAPITAL:.2f} -> ${capital:.2f} ({(capital-INITIAL_CAPITAL)/INITIAL_CAPITAL*100:+.2f}%)")
    print(f"  Max DD: {max_dd:.2f}%")
    print(f"  Total fees: ${sum(t['pnl_dollar'] for t in trades) - (capital - INITIAL_CAPITAL):.2f}")

    print(f"\n  Signal stats:")
    print(f"    Fired: {signals_fired}")
    print(f"    Filtered (FR neutral): {signals_filtered_fr}")
    print(f"    Filtered (whale disagree): {signals_filtered_whale}")
    print(f"    Filtered (EMA trend): {signals_filtered_ema}")

    print(f"\n  All trades:")
    print(f"  {'#':>3s} {'Time':<20s} {'Dir':>5s} {'Out':>4s} {'Entry':>9s} {'Exit':>9s} {'FR':>10s} {'LS':>6s} {'PnL%':>7s} {'PnL$':>8s} {'Bars':>4s}")
    print("  " + "-" * 90)
    for i, t in enumerate(trades):
        fr_str = f"{t['fr']:.6f}"
        print(f"  {i+1:>3d} {t['time']:<20s} {t['dir']:>5s} {t['outcome']:>4s} {t['entry']:>9.2f} {t['exit']:>9.2f} {fr_str:>10s} {t['ls']:>6.3f} {t['pnl_pct']:>+6.2f}% ${t['pnl_dollar']:>+7.2f} {t['bars']:>4d}")

    # Compounding projection
    print(f"\n  Compounding projection (if pace holds):")
    days = (datetime.strptime(trades[-1]['time'], '%Y-%m-%d %H:%M:%S') - datetime.strptime(trades[0]['time'], '%Y-%m-%d %H:%M:%S')).days
    if days > 0:
        daily_return = (capital / INITIAL_CAPITAL) ** (1/days) - 1
        annual_return = (1 + daily_return) ** 365 - 1
        print(f"    Period: {days} days")
        print(f"    Daily return: {daily_return*100:+.2f}%")
        print(f"    Annualized: {annual_return*100:+.1f}%")
        print(f"    $200 -> $1000: ~{np.log(5)/np.log(1+daily_return):.0f} days")

# Save
with open("reports/funding_arb_v2_backtest.json", "w") as f:
    json.dump({'trades': trades, 'final_capital': capital, 'signals_fired': signals_fired,
               'signals_filtered_fr': signals_filtered_fr, 'signals_filtered_whale': signals_filtered_whale,
               'signals_filtered_ema': signals_filtered_ema}, f, indent=2, default=str)
print(f"\n  Saved to reports/funding_arb_v2_backtest.json")
