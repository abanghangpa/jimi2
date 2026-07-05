#!/usr/bin/env python3
"""
Aggressive Backtester - Find params that compound $200 -> $1M
Tests higher risk %, higher leverage, tighter TP/SL, more frequency
"""
import json, os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "eth_60d_1h.json")

def load_candles():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    return [{"ts": c[0], "dt": datetime.fromtimestamp(c[0]/1000, tz=timezone.utc),
             "open": float(c[1]), "high": float(c[2]), "low": float(c[3]),
             "close": float(c[4]), "volume": float(c[5])} for c in raw]

def run_backtest(candles, signal_fn, tp_pct, sl_pct, risk_pct, leverage, initial=200.0, **kw):
    capital = initial
    peak = capital
    max_dd = 0
    trades = []
    open_trade = None
    reached_1m = None
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    
    for i in range(1, len(candles)):
        c = candles[i]
        if open_trade:
            hit_tp = hit_sl = False
            if open_trade["dir"] == "LONG":
                if highs[i] >= open_trade["tp"]: hit_tp = True; ep = open_trade["tp"]
                elif lows[i] <= open_trade["sl"]: hit_sl = True; ep = open_trade["sl"]
            else:
                if lows[i] <= open_trade["tp"]: hit_tp = True; ep = open_trade["tp"]
                elif highs[i] >= open_trade["sl"]: hit_sl = True; ep = open_trade["sl"]
            if hit_tp or hit_sl:
                pnl_eth = (ep - open_trade["entry"]) if open_trade["dir"] == "LONG" else (open_trade["entry"] - ep)
                pnl = pnl_eth * open_trade["size"]
                capital += pnl
                trades.append({"dir": open_trade["dir"], "entry": open_trade["entry"], "exit": ep, "pnl": pnl, "win": hit_tp})
                if capital > peak: peak = capital
                dd = (peak - capital) / peak * 100 if peak > 0 else 0
                if dd > max_dd: max_dd = dd
                if capital <= 0: break
                if capital >= 1_000_000 and not reached_1m:
                    reached_1m = c["dt"].isoformat()
                open_trade = None
        
        if not open_trade and capital > 1:
            signal = signal_fn(candles, i, **kw)
            if signal:
                entry = c["close"]
                if signal == "LONG":
                    tp = entry * (1 + tp_pct)
                    sl = entry * (1 - sl_pct)
                else:
                    tp = entry * (1 - tp_pct)
                    sl = entry * (1 + sl_pct)
                risk_amount = capital * risk_pct
                sl_dist = abs(entry - sl)
                if sl_dist > 0:
                    size = risk_amount / sl_dist
                    size = min(size, (capital * leverage) / entry)
                    if size > 0:
                        open_trade = {"dir": signal, "entry": entry, "tp": tp, "sl": sl, "size": size}
    
    if open_trade:
        ep = candles[-1]["close"]
        pnl_eth = (ep - open_trade["entry"]) if open_trade["dir"] == "LONG" else (open_trade["entry"] - ep)
        pnl = pnl_eth * open_trade["size"]
        capital += pnl
        trades.append({"dir": open_trade["dir"], "entry": open_trade["entry"], "exit": ep, "pnl": pnl, "win": pnl > 0})
    
    wins = sum(1 for t in trades if t["win"])
    return {
        "final": capital, "trades": len(trades), "wins": wins,
        "losses": len(trades) - wins,
        "wr": wins / len(trades) * 100 if trades else 0,
        "max_dd": max_dd, "reached_1m": reached_1m is not None,
        "reached_1m_at": reached_1m,
    }

# Signal functions
def sig_rsi(candles, idx, rsi_period=14, rsi_os=30, rsi_ob=70, **kw):
    if idx < rsi_period + 1: return None
    closes = [c["close"] for c in candles[:idx+1]]
    g, l = [], []
    for i in range(len(closes) - rsi_period, len(closes)):
        d = closes[i] - closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag = sum(g)/rsi_period; al = sum(l)/rsi_period
    if al == 0: return None
    rsi = 100 - (100/(1+ag/al))
    if rsi < rsi_os: return "LONG"
    if rsi > rsi_ob: return "SHORT"
    return None

def sig_momentum(candles, idx, lookback=12, threshold=0.02, **kw):
    if idx < lookback: return None
    chg = (candles[idx]["close"] - candles[idx-lookback]["close"]) / candles[idx-lookback]["close"]
    if chg > threshold: return "LONG"
    if chg < -threshold: return "SHORT"
    return None

def sig_ema_cross(candles, idx, fast=9, slow=21, **kw):
    if idx < slow + 1: return None
    closes = [c["close"] for c in candles[:idx+1]]
    def ema(data, p):
        k = 2/(p+1); e = data[0]
        for v in data[1:]: e = v*k + e*(1-k)
        return e
    f = ema(closes[-fast*3:], fast); s = ema(closes[-slow*3:], slow)
    pf = ema(closes[-fast*3-1:-1], fast); ps = ema(closes[-slow*3-1:-1], slow)
    if pf <= ps and f > s: return "LONG"
    if pf >= ps and f < s: return "SHORT"
    return None

def sig_breakout(candles, idx, lookback=24, **kw):
    if idx < lookback: return None
    recent = candles[idx-lookback:idx]
    hi = max(c["high"] for c in recent); lo = min(c["low"] for c in recent)
    p = candles[idx]["close"]
    if p > hi: return "LONG"
    if p < lo: return "SHORT"
    return None

def sig_swing(candles, idx, lookback=48, **kw):
    if idx < lookback: return None
    closes = [c["close"] for c in candles[idx-lookback:idx+1]]
    mid = len(closes)//2
    fa = sum(closes[:mid])/mid; sa = sum(closes[mid:])/(len(closes)-mid)
    hi = max(closes); lo = min(closes); rng = hi - lo
    if rng == 0: return None
    pos = (closes[-1] - lo) / rng
    if sa > fa and pos < 0.3: return "LONG"
    if sa < fa and pos > 0.7: return "SHORT"
    return None

def sig_vol_break(candles, idx, atr_p=14, atr_m=1.5, **kw):
    if idx < atr_p + 1: return None
    trs = []
    for j in range(idx-atr_p, idx):
        tr = max(candles[j]["high"]-candles[j]["low"],
            abs(candles[j]["high"]-candles[j-1]["close"]),
            abs(candles[j]["low"]-candles[j-1]["close"]))
        trs.append(tr)
    atr = sum(trs)/len(trs)
    move = candles[idx]["close"] - candles[idx-1]["close"]
    if move > atr * atr_m: return "LONG"
    if move < -atr * atr_m: return "SHORT"
    return None

def sig_mean_rev(candles, idx, period=48, std_m=2.0, **kw):
    if idx < period: return None
    closes = [c["close"] for c in candles[idx-period:idx]]
    mean = sum(closes)/len(closes)
    std = (sum((x-mean)**2 for x in closes)/len(closes))**0.5
    p = candles[idx]["close"]
    if p < mean - std_m*std: return "LONG"
    if p > mean + std_m*std: return "SHORT"
    return None

def sig_trend_follow(candles, idx, ema_fast=9, ema_slow=21, rsi_period=14, **kw):
    if idx < ema_slow + rsi_period: return None
    closes = [c["close"] for c in candles[:idx+1]]
    def ema(data, p):
        k = 2/(p+1); e = data[0]
        for v in data[1:]: e = v*k + e*(1-k)
        return e
    f = ema(closes[-ema_fast*3:], ema_fast); s = ema(closes[-ema_slow*3:], ema_slow)
    g, l = [], []
    for i in range(len(closes)-rsi_period, len(closes)):
        d = closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g)/rsi_period; al=sum(l)/rsi_period
    rsi = 100-(100/(1+ag/al)) if al > 0 else 100
    if f > s and 50 < rsi < 70: return "LONG"
    if f < s and 30 < rsi < 50: return "SHORT"
    return None

# ========== MAIN SWEEP ==========
def main():
    candles = load_candles()
    print(f"Loaded {len(candles)} candles: ${candles[0]['close']:.2f} -> ${candles[-1]['close']:.2f}")
    print(f"Range: ${min(c['low'] for c in candles):.2f} - ${max(c['high'] for c in candles):.2f}\n")
    
    signals = [
        ("RSI_7", lambda c,i,**kw: sig_rsi(c,i,rsi_period=7,**kw)),
        ("RSI_14", lambda c,i,**kw: sig_rsi(c,i,rsi_period=14,**kw)),
        ("RSI_21", lambda c,i,**kw: sig_rsi(c,i,rsi_period=21,**kw)),
        ("Momentum_6", lambda c,i,**kw: sig_momentum(c,i,lookback=6,**kw)),
        ("Momentum_12", lambda c,i,**kw: sig_momentum(c,i,lookback=12,**kw)),
        ("EMA_9_21", lambda c,i,**kw: sig_ema_cross(c,i,fast=9,slow=21,**kw)),
        ("EMA_5_34", lambda c,i,**kw: sig_ema_cross(c,i,fast=5,slow=34,**kw)),
        ("Breakout_24", lambda c,i,**kw: sig_breakout(c,i,lookback=24,**kw)),
        ("Swing_48", lambda c,i,**kw: sig_swing(c,i,lookback=48,**kw)),
        ("VolBreak", lambda c,i,**kw: sig_vol_break(c,i,**kw)),
        ("MeanRev", lambda c,i,**kw: sig_mean_rev(c,i,**kw)),
        ("TrendFollow", lambda c,i,**kw: sig_trend_follow(c,i,**kw)),
    ]
    
    # Risk levels: 5%, 10%, 15%, 20%, 25%, 30%, 40%, 50%
    risk_levels = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    # Leverage: 5x, 10x, 20x, 50x
    leverage_levels = [5, 10, 20, 50]
    # TP/SL: (tp%, sl%)
    tp_sl = [
        (0.005, 0.003),  # 0.5% TP, 0.3% SL (scalping, 1.67:1)
        (0.01, 0.005),   # 1% TP, 0.5% SL (2:1)
        (0.015, 0.008),  # 1.5% TP, 0.8% SL (1.88:1)
        (0.02, 0.01),    # 2% TP, 1% SL (2:1)
        (0.03, 0.015),   # 3% TP, 1.5% SL (2:1)
        (0.003, 0.002),  # 0.3% TP, 0.2% SL (1.5:1) ultra scalp
        (0.005, 0.005),  # 0.5% TP, 0.5% SL (1:1) needs high WR
        (0.01, 0.01),    # 1% TP, 1% SL (1:1)
        (0.02, 0.008),   # 2% TP, 0.8% SL (2.5:1)
        (0.03, 0.01),    # 3% TP, 1% SL (3:1)
        (0.05, 0.02),    # 5% TP, 2% SL (2.5:1)
        (0.04, 0.015),   # 4% TP, 1.5% SL (2.67:1)
    ]
    
    results = []
    total = 0
    
    for sig_name, sig_fn in signals:
        for rsi_os in [20, 25, 30]:
            for rsi_ob in [70, 75, 80]:
                for thr in [0.01, 0.02, 0.03]:
                    for risk in risk_levels:
                        for lev in leverage_levels:
                            for tp_p, sl_p in tp_sl:
                                total += 1
                                try:
                                    r = run_backtest(candles, sig_fn, tp_p, sl_p, risk, lev,
                                        rsi_os=rsi_os, rsi_ob=rsi_ob, threshold=thr)
                                    r["sig"] = sig_name
                                    r["params"] = {"tp": tp_p, "sl": sl_p, "risk": risk, "lev": lev,
                                        "rsi_os": rsi_os, "rsi_ob": rsi_ob, "threshold": thr}
                                    results.append(r)
                                except:
                                    pass
    
    print(f"Ran {total} backtests\n")
    results.sort(key=lambda r: r["final"], reverse=True)
    
    print("=" * 130)
    print(f"{'#':<4} {'Signal':<15} {'Final':>14} {'x':>8} {'Trades':>7} {'WR':>6} {'MaxDD':>7} {'$1M':>4} {'Risk%':>6} {'Lev':>4} {'TP%':>6} {'SL%':>6}")
    print("=" * 130)
    
    for i, r in enumerate(results[:40]):
        ret = r["final"] / 200
        print(f"{i+1:<4} {r['sig']:<15} ${r['final']:>12,.2f} {ret:>7.1f}x {r['trades']:>7} {r['wr']:>5.1f}% {r['max_dd']:>6.1f}% {'Y' if r['reached_1m'] else 'N':>4} {r['params']['risk']*100:>5.0f}% {r['params']['lev']:>3}x {r['params']['tp']*100:>5.2f}% {r['params']['sl']*100:>5.2f}%")
    
    m = [r for r in results if r["reached_1m"]]
    if m:
        print(f"\n*** {len(m)} combos reached $1,000,000! ***")
        for r in m[:20]:
            print(f"  {r['sig']}: ${r['final']:,.0f} | {r['trades']}T | {r['wr']:.1f}% WR | risk={r['params']['risk']*100:.0f}% lev={r['params']['lev']}x tp={r['params']['tp']*100:.2f}% sl={r['params']['sl']*100:.2f}%")
    else:
        print(f"\nNo combos reached $1,000,000")
        b = results[0]
        print(f"Best: {b['sig']} -> ${b['final']:,.2f} ({b['final']/200:.1f}x)")
        # Show what risk/leverage would be needed
        print("\n--- What would it take? ---")
        print(f"$200 -> $1M = 5,000x return in 60 days")
        print(f"That's ~14% compounding per day for 60 days")
        print(f"Or ~20 winning trades at 2:1 R:R with 50% risk per trade")

if __name__ == "__main__":
    main()
