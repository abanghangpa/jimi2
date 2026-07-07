#!/usr/bin/env python3
"""
Phase 2: Backtest with cached data — no API calls during backtest.
Monkey-patches all fetch functions to return cached data.
"""
import sys, os, json, time, pickle
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

CACHE_DIR = "/root/.openclaw/workspace/jimi_audit/data/backtest_cache"

# ============================================================
# MONKEY-PATCH: Replace all fetch functions with cached versions
# ============================================================

# Load cached data
print("Loading cached data...")
with open(os.path.join(CACHE_DIR, "tradfi.pkl"), "rb") as f:
    CACHED_TRADFI = pickle.load(f)
with open(os.path.join(CACHE_DIR, "btc_daily.json")) as f:
    CACHED_BTC_DAILY = json.load(f)
with open(os.path.join(CACHE_DIR, "ethbtc_daily.json")) as f:
    CACHED_ETHBTC_DAILY = json.load(f)
with open(os.path.join(CACHE_DIR, "macro.json")) as f:
    CACHED_MACRO = json.load(f)
with open(os.path.join(CACHE_DIR, "exchange.json")) as f:
    CACHED_EXCHANGE = json.load(f)

# Patch fetch_all_tradfi_data
import scripts.scanner as scanner_mod
_orig_fetch_tradfi = scanner_mod.fetch_all_tradfi_data
scanner_mod.fetch_all_tradfi_data = lambda config=None: CACHED_TRADFI

# Patch fetch_all_exchange_data
import src.modules.m16_exchange_activity as exch_mod
_orig_fetch_exch = exch_mod.fetch_all_exchange_data
exch_mod.fetch_all_exchange_data = lambda: CACHED_EXCHANGE

# Patch individual macro fetches to return cached
import src.utils.macro_fetch as mf
for fn_name, cached_val in CACHED_MACRO.items():
    if hasattr(mf, fn_name):
        setattr(mf, fn_name, lambda _cv=cached_val: _cv)

# Patch requests.get for Binance API calls to return cached data
import requests
_orig_get = requests.get

class MockResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
    def json(self):
        return self._data
    def raise_for_status(self):
        pass

def cached_get(url, **kwargs):
    """Return cached data for known Binance endpoints."""
    if "klines" in url and "BTCUSDT" in url and "interval=1d" in url:
        return MockResponse(CACHED_BTC_DAILY)
    if "klines" in url and "ETHBTC" in url and "interval=1d" in url:
        return MockResponse(CACHED_ETHBTC_DAILY)
    if "klines" in url and "ETHUSDT" in url and "interval=1h" in url:
        # Return dummy — we have indicators pre-computed
        return MockResponse([])
    if "klines" in url and "ETHUSDT" in url and "interval=15m" in url:
        return MockResponse([])
    if "klines" in url and "ETHUSDT" in url and "interval=1m" in url:
        return MockResponse([])  # Skip intrabar CVD
    if "ticker/price" in url:
        return MockResponse({"price": "0"})
    if "fundingRate" in url or "openInterest" in url:
        return MockResponse([])
    if "fapi" in url:
        return MockResponse({})
    # Fall through to real request for anything else
    return _orig_get(url, **kwargs)

requests.get = cached_get

# Also patch the intrabar CVD to skip
import src.modules.intrabar_cvd as icvd_mod
icvd_mod.get_intrabar_cvd_summary = lambda *a, **kw: (None, {})

# Patch BTC 15m fetch
import src.utils.data_handler as dh_mod
if hasattr(CACHED_TRADFI, 'get') and CACHED_TRADFI.get('btc_15m') is not None:
    pass  # Already cached

print("All fetch functions patched to use cached data.")

# ============================================================
# BACKTEST
# ============================================================
from src.config import CONFIG
from src.utils.data_handler import load_data, resample_ohlcv
from src.utils.indicators import calc_atr, calc_vol_ratio, calc_ema, calc_rsi, calc_macd
from scripts.scanner import scan_signal, compute_indicators

START_DATE = "2026-02-02"
END_DATE = "2026-06-06"
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.001
STEP = 4  # every 1h

ENABLED = {
    "whale_watch": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 8, "min_conv": 0.5},
    "funding_arb": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12, "min_conv": 0.5},
    "orderbook_imbalance": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5},
    "failed_breakout": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.7},
    "positioning_fade": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5},
    "trade_flow": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5},
    "structural_break": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.5},
    "regime_switch": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5},
}

print("\nLoading ETH data...")
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
print(f"  Strategies: {list(ENABLED.keys())}")

trades = []
capital = INITIAL_CAPITAL
peak_capital = INITIAL_CAPITAL
max_dd = 0
open_positions = []
total_signals = 0
scanner_calls = 0
errors = 0

t0 = time.time()
print("\nRunning backtest...")

for i in range(start_idx, end_idx + 1, STEP):
    if time.time() - t0 > 540:
        print(f"  TIMEOUT at bar {i}")
        break
    
    if (i - start_idx) % 200 == 0:
        pct = (i - start_idx) / (end_idx - start_idx) * 100
        elapsed = time.time() - t0
        print(f"  {pct:.0f}% | bar {i} | trades={len(trades)} | cap=${capital:.2f} | sigs={total_signals} | errs={errors} | {elapsed:.0f}s")
    
    row = df_15m.iloc[i]
    ts = row['Open time']
    price = float(row['Close'])
    high = float(row['High'])
    low = float(row['Low'])
    
    # TP/SL check
    closed = []
    for pos in open_positions:
        bars_held = i - pos['entry_idx']
        max_bars = pos['hold_hours'] * 4
        if pos['direction'] == 'LONG':
            if high >= pos['tp']:
                pnl = pos['size'] * (pos['tp'] - pos['entry']) / pos['entry'] - pos['fee']
                capital += pnl; trades.append({**pos, 'exit': pos['tp'], 'pnl': pnl, 'outcome': 'WIN', 'bars': bars_held}); closed.append(pos)
            elif low <= pos['sl']:
                pnl = pos['size'] * (pos['sl'] - pos['entry']) / pos['entry'] - pos['fee']
                capital += pnl; trades.append({**pos, 'exit': pos['sl'], 'pnl': pnl, 'outcome': 'LOSS', 'bars': bars_held}); closed.append(pos)
            elif bars_held >= max_bars:
                pnl = pos['size'] * (price - pos['entry']) / pos['entry'] - pos['fee']
                capital += pnl; trades.append({**pos, 'exit': price, 'pnl': pnl, 'outcome': 'WIN' if pnl > 0 else 'LOSS', 'bars': bars_held}); closed.append(pos)
        else:
            if low <= pos['tp']:
                pnl = pos['size'] * (pos['entry'] - pos['tp']) / pos['entry'] - pos['fee']
                capital += pnl; trades.append({**pos, 'exit': pos['tp'], 'pnl': pnl, 'outcome': 'WIN', 'bars': bars_held}); closed.append(pos)
            elif high >= pos['sl']:
                pnl = pos['size'] * (pos['entry'] - pos['sl']) / pos['entry'] - pos['fee']
                capital += pnl; trades.append({**pos, 'exit': pos['sl'], 'pnl': pnl, 'outcome': 'LOSS', 'bars': bars_held}); closed.append(pos)
            elif bars_held >= max_bars:
                pnl = pos['size'] * (pos['entry'] - price) / pos['entry'] - pos['fee']
                capital += pnl; trades.append({**pos, 'exit': price, 'pnl': pnl, 'outcome': 'WIN' if pnl > 0 else 'LOSS', 'bars': bars_held}); closed.append(pos)
    for p in closed:
        open_positions.remove(p)
    
    if capital > peak_capital: peak_capital = capital
    dd = (peak_capital - capital) / peak_capital * 100 if peak_capital > 0 else 0
    if dd > max_dd: max_dd = dd
    if len(open_positions) >= 3 or capital <= 0: continue
    
    df_s = df_15m.iloc[:i+1].copy()
    df_1h_s = df_1h[df_1h['Open time'] <= ts].copy()
    df_2h_s = df_2h[df_2h['Open time'] <= ts].copy()
    df_4h_s = df_4h[df_4h['Open time'] <= ts].copy()
    df_1d_s = df_1d[df_1d['Open time'] <= ts].copy()
    
    if len(df_1h_s) < 20 or len(df_1d_s) < 2: continue
    
    try:
        result = scan_signal(df_s, df_1h_s, df_2h_s, df_4h_s, df_1d_s, config=cfg)
        scanner_calls += 1
    except Exception as e:
        errors += 1
        continue
    
    if not result: continue
    
    # Check multi_strategy signals
    multi = result.get('multi_strategy', {})
    if isinstance(multi, dict):
        all_sigs = multi.get('all_signals', [])
        if isinstance(all_sigs, list):
            for sig_data in all_sigs:
                if not isinstance(sig_data, dict): continue
                strat_name = sig_data.get('strategy', '')
                if strat_name not in ENABLED: continue
                direction = sig_data.get('direction')
                conviction = sig_data.get('conviction', 0)
                if not direction or conviction < ENABLED[strat_name]['min_conv']: continue
                if any(p['strategy'] == strat_name for p in open_positions): continue
                total_signals += 1
                cfg_s = ENABLED[strat_name]
                tp_pct = cfg_s['tp_pct'] / 100; sl_pct = cfg_s['sl_pct'] / 100
                if direction == 'LONG':
                    entry = price * 1.001; tp = entry * (1 + tp_pct); sl = entry * (1 - sl_pct)
                else:
                    entry = price * 0.999; tp = entry * (1 - tp_pct); sl = entry * (1 + sl_pct)
                sl_dist = abs(entry - sl)
                if sl_dist == 0: continue
                size = min(capital * RISK_PCT / sl_dist, capital * LEVERAGE / entry)
                if size <= 0: continue
                fee = size * entry * FEE_RATE
                open_positions.append({
                    'strategy': strat_name, 'direction': direction,
                    'entry': round(entry, 2), 'tp': round(tp, 2), 'sl': round(sl, 2),
                    'size': round(size, 6), 'fee': fee, 'hold_hours': cfg_s['hold_hours'],
                    'entry_idx': i, 'conviction': conviction, 'ts': str(ts),
                })
                break

# Close remaining
for pos in open_positions:
    price = float(df_15m['Close'].iloc[end_idx])
    if pos['direction'] == 'LONG':
        pnl = pos['size'] * (price - pos['entry']) / pos['entry'] - pos['fee']
    else:
        pnl = pos['size'] * (pos['entry'] - price) / pos['entry'] - pos['fee']
    capital += pnl
    trades.append({**pos, 'exit': price, 'pnl': pnl, 'outcome': 'WIN' if pnl > 0 else 'LOSS', 'bars': end_idx - pos['entry_idx']})

elapsed = time.time() - t0

print(f"\n{'='*80}")
print(f"BACKTEST: {START_DATE} to {END_DATE}")
print(f"{'='*80}")
print(f"Scanner calls: {scanner_calls} | Signals: {total_signals} | Errors: {errors}")
print(f"Capital: ${INITIAL_CAPITAL:.2f} -> ${capital:.2f} ({(capital-INITIAL_CAPITAL)/INITIAL_CAPITAL*100:+.1f}%)")
nt = len(trades); nw = len([t for t in trades if t['outcome']=='WIN']); nl = nt - nw
print(f"Trades: {nt} | W: {nw} | L: {nl}")
wr = nw / nt * 100 if nt else 0
print(f"WR: {wr:.1f}%")
gp = sum(t['pnl'] for t in trades if t['pnl'] > 0)
gl = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
pf = gp / gl if gl > 0 else float('inf')
print(f"PF: {pf:.2f} | MaxDD: {max_dd:.1f}% | Fees: ${sum(t.get('fee',0) for t in trades):.2f}")
print(f"Time: {elapsed:.0f}s")

print(f"\nPER-STRATEGY:")
ss = defaultdict(lambda: {'n': 0, 'w': 0, 'pnl': 0})
for t in trades:
    ss[t['strategy']]['n'] += 1; ss[t['strategy']]['pnl'] += t['pnl']
    if t['outcome'] == 'WIN': ss[t['strategy']]['w'] += 1
for s, v in sorted(ss.items(), key=lambda x: x[1]['pnl'], reverse=True):
    wr_s = v['w'] / v['n'] * 100 if v['n'] > 0 else 0
    g_profit = sum(t['pnl'] for t in trades if t['strategy'] == s and t['pnl'] > 0)
    g_loss = abs(sum(t['pnl'] for t in trades if t['strategy'] == s and t['pnl'] < 0))
    pf_s = g_profit / g_loss if g_loss > 0 else float('inf')
    tag = "PASS" if pf_s >= 2.0 and wr_s >= 70 else "FAIL"
    print(f"  [{tag}] {s:25s} n={v['n']:4d} WR={wr_s:5.1f}% PF={pf_s:5.2f} PnL=${v['pnl']:+8.2f}")

print(f"\nMONTHLY:")
monthly = defaultdict(lambda: {'n': 0, 'w': 0, 'pnl': 0})
for t in trades:
    m = t['ts'][:7]; monthly[m]['n'] += 1; monthly[m]['pnl'] += t['pnl']
    if t['outcome'] == 'WIN': monthly[m]['w'] += 1
for m in sorted(monthly):
    v = monthly[m]
    wr_m = v['w'] / v['n'] * 100 if v['n'] > 0 else 0
    print(f"  {m} n={v['n']:4d} WR={wr_m:5.1f}% PnL=${v['pnl']:+8.2f}")

print("Done.")
