#!/usr/bin/env python3
"""
ETH Strategy Backtester - Find what actually compounds $200 -> $1M
Tests multiple strategies with compounding on 60 days of 1h data.
Capital: $200, Risk per trade: 5%, Leverage: 5x
"""
import json, os, sys
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "eth_60d_1h.json")

INITIAL_CAPITAL = 200.0
RISK_PCT = 0.05
LEVERAGE = 5.0

def load_candles():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    candles = []
    for c in raw:
        candles.append({
            "ts": c[0],
            "dt": datetime.fromtimestamp(c[0]/1000, tz=timezone.utc),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        })
    return candles

@dataclass
class Trade:
    direction: str
    entry: float
    size: float
    capital_at_entry: float
    tp: float
    sl: float
    entry_idx: int
    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    outcome: Optional[str] = None

@dataclass
class BacktestResult:
    strategy: str
    params: dict
    initial_capital: float
    final_capital: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown_pct: float
    peak_capital: float
    trades: List[Trade] = field(default_factory=list)
    reached_1m: bool = False
    reached_1m_at: Optional[str] = None

def run_backtest(candles, strategy_name, signal_fn, tp_mult, sl_mult, **kwargs):
    capital = INITIAL_CAPITAL
    peak = capital
    max_dd = 0
    trades = []
    open_trade = None
    reached_1m = False
    reached_1m_at = None
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    
    for i in range(1, len(candles)):
        c = candles[i]
        if open_trade:
            hit_tp = hit_sl = False
            if open_trade.direction == "LONG":
                if highs[i] >= open_trade.tp: hit_tp = True; exit_price = open_trade.tp
                elif lows[i] <= open_trade.sl: hit_sl = True; exit_price = open_trade.sl
            else:
                if lows[i] <= open_trade.tp: hit_tp = True; exit_price = open_trade.tp
                elif highs[i] >= open_trade.sl: hit_sl = True; exit_price = open_trade.sl
            if hit_tp or hit_sl:
                pnl_eth = (exit_price - open_trade.entry) if open_trade.direction == "LONG" else (open_trade.entry - exit_price)
                pnl = pnl_eth * open_trade.size
                open_trade.exit_idx = i; open_trade.exit_price = exit_price
                open_trade.pnl = pnl; open_trade.outcome = "WIN" if hit_tp else "LOSS"
                trades.append(open_trade); capital += pnl
                if capital > peak: peak = capital
                dd = (peak - capital) / peak * 100 if peak > 0 else 0
                if dd > max_dd: max_dd = dd
                if capital <= 0: open_trade = None; break
                if capital >= 1_000_000 and not reached_1m:
                    reached_1m = True; reached_1m_at = c["dt"].isoformat()
                open_trade = None
        
        if not open_trade:
            signal = signal_fn(candles, i, capital, **kwargs)
            if signal and capital > 1:
                entry_price = c["close"]
                tp_dist, sl_dist = calculate_tp_sl(candles, i, tp_mult, sl_mult, **kwargs)
                if signal == "LONG": tp = entry_price + tp_dist; sl = entry_price - sl_dist
                else: tp = entry_price - tp_dist; sl = entry_price + sl_dist
                risk_amount = capital * RISK_PCT
                sl_dist_abs = abs(entry_price - sl)
                if sl_dist_abs > 0:
                    size = risk_amount / sl_dist_abs
                    size = min(size, (capital * LEVERAGE) / entry_price)
                else: size = 0
                if size > 0:
                    open_trade = Trade(direction=signal, entry=entry_price, size=size,
                        capital_at_entry=capital, tp=tp, sl=sl, entry_idx=i)
    
    if open_trade:
        exit_price = candles[-1]["close"]
        pnl_eth = (exit_price - open_trade.entry) if open_trade.direction == "LONG" else (open_trade.entry - exit_price)
        pnl = pnl_eth * open_trade.size
        open_trade.exit_idx = len(candles)-1; open_trade.exit_price = exit_price
        open_trade.pnl = pnl; open_trade.outcome = "WIN" if pnl > 0 else "LOSS"
        trades.append(open_trade); capital += pnl
    
    wins = sum(1 for t in trades if t.outcome == "WIN")
    losses = sum(1 for t in trades if t.outcome == "LOSS")
    return BacktestResult(strategy=strategy_name, params={"tp_mult": tp_mult, "sl_mult": sl_mult, **kwargs},
        initial_capital=INITIAL_CAPITAL, final_capital=capital, total_trades=len(trades),
        wins=wins, losses=losses, win_rate=wins/len(trades)*100 if trades else 0,
        max_drawdown_pct=max_dd, peak_capital=peak, trades=trades,
        reached_1m=reached_1m, reached_1m_at=reached_1m_at)

def calculate_tp_sl(candles, idx, tp_mult, sl_mult, base_type="atr", atr_period=14, **kwargs):
    if base_type == "atr":
        if idx < atr_period: atr = abs(candles[idx]["high"] - candles[idx]["low"])
        else:
            trs = []
            for j in range(idx - atr_period, idx):
                tr = max(candles[j]["high"] - candles[j]["low"],
                    abs(candles[j]["high"] - candles[j-1]["close"]),
                    abs(candles[j]["low"] - candles[j-1]["close"]))
                trs.append(tr)
            atr = sum(trs) / len(trs)
        return atr * tp_mult, atr * sl_mult
    elif base_type == "pct":
        price = candles[idx]["close"]
        return price * tp_mult, price * sl_mult
    return tp_mult, sl_mult

def signal_rsi(candles, idx, capital, rsi_period=14, rsi_oversold=30, rsi_overbought=70, **kw):
    if idx < rsi_period + 1: return None
    closes = [c["close"] for c in candles[:idx+1]]
    gains, losses = [], []
    for i in range(len(closes) - rsi_period, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    avg_gain = sum(gains) / rsi_period; avg_loss = sum(losses) / rsi_period
    if avg_loss == 0: return None
    rs = avg_gain / avg_loss; rsi = 100 - (100 / (1 + rs))
    if rsi < rsi_oversold: return "LONG"
    elif rsi > rsi_overbought: return "SHORT"
    return None

def signal_ema_cross(candles, idx, capital, fast=9, slow=21, **kw):
    if idx < slow + 1: return None
    closes = [c["close"] for c in candles[:idx+1]]
    def ema(data, period):
        k = 2 / (period + 1); e = data[0]
        for p in data[1:]: e = p * k + e * (1 - k)
        return e
    fast_ema = ema(closes[-fast*3:], fast); slow_ema = ema(closes[-slow*3:], slow)
    prev_fast = ema(closes[-fast*3-1:-1], fast); prev_slow = ema(closes[-slow*3-1:-1], slow)
    if prev_fast <= prev_slow and fast_ema > slow_ema: return "LONG"
    elif prev_fast >= prev_slow and fast_ema < slow_ema: return "SHORT"
    return None

def signal_momentum(candles, idx, capital, lookback=12, threshold=0.02, **kw):
    if idx < lookback: return None
    price_now = candles[idx]["close"]; price_then = candles[idx - lookback]["close"]
    change = (price_now - price_then) / price_then
    if change > threshold: return "LONG"
    elif change < -threshold: return "SHORT"
    return None

def signal_breakout(candles, idx, capital, lookback=24, **kw):
    if idx < lookback: return None
    recent = candles[idx-lookback:idx]
    high = max(c["high"] for c in recent); low = min(c["low"] for c in recent)
    price = candles[idx]["close"]
    if price > high: return "LONG"
    elif price < low: return "SHORT"
    return None

def signal_mean_reversion(candles, idx, capital, period=48, std_mult=2.0, **kw):
    if idx < period: return None
    closes = [c["close"] for c in candles[idx-period:idx]]
    mean = sum(closes) / len(closes)
    std = (sum((x - mean)**2 for x in closes) / len(closes)) ** 0.5
    price = candles[idx]["close"]
    if price < mean - std_mult * std: return "LONG"
    elif price > mean + std_mult * std: return "SHORT"
    return None

def signal_trend_follow(candles, idx, capital, ema_fast=9, ema_slow=21, rsi_period=14, **kw):
    if idx < ema_slow + rsi_period: return None
    closes = [c["close"] for c in candles[:idx+1]]
    def ema(data, period):
        k = 2 / (period + 1); e = data[0]
        for p in data[1:]: e = p * k + e * (1 - k)
        return e
    fast = ema(closes[-ema_fast*3:], ema_fast); slow = ema(closes[-ema_slow*3:], ema_slow)
    gains, losses = [], []
    for i in range(len(closes) - rsi_period, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    avg_gain = sum(gains) / rsi_period; avg_loss = sum(losses) / rsi_period
    if avg_loss == 0: rsi = 100
    else: rs = avg_gain / avg_loss; rsi = 100 - (100 / (1 + rs))
    if fast > slow and rsi > 50 and rsi < 70: return "LONG"
    elif fast < slow and rsi < 50 and rsi > 30: return "SHORT"
    return None

def signal_volatility_breakout(candles, idx, capital, atr_period=14, atr_mult=1.5, **kw):
    if idx < atr_period + 1: return None
    trs = []
    for j in range(idx - atr_period, idx):
        tr = max(candles[j]["high"] - candles[j]["low"],
            abs(candles[j]["high"] - candles[j-1]["close"]),
            abs(candles[j]["low"] - candles[j-1]["close"]))
        trs.append(tr)
    atr = sum(trs) / len(trs)
    price = candles[idx]["close"]; prev_close = candles[idx-1]["close"]
    move = price - prev_close
    if move > atr * atr_mult: return "LONG"
    elif move < -atr * atr_mult: return "SHORT"
    return None

def signal_swing(candles, idx, capital, lookback=48, **kw):
    if idx < lookback: return None
    segment = candles[idx-lookback:idx+1]; closes = [c["close"] for c in segment]
    mid = len(closes) // 2
    first_half_avg = sum(closes[:mid]) / mid
    second_half_avg = sum(closes[mid:]) / (len(closes) - mid)
    high = max(closes); low = min(closes); rng = high - low
    if rng == 0: return None
    price = closes[-1]; position = (price - low) / rng
    if second_half_avg > first_half_avg and position < 0.3: return "LONG"
    elif second_half_avg < first_half_avg and position > 0.7: return "SHORT"
    return None

def optimize():
    candles = load_candles()
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0]['close']:.2f} -> ${candles[-1]['close']:.2f}")
    print(f"Range: ${min(c['low'] for c in candles):.2f} - ${max(c['high'] for c in candles):.2f}")
    print()
    
    strategies = [
        ("RSI", signal_rsi, {"rsi_period": [7, 14, 21], "rsi_oversold": [20, 25, 30], "rsi_overbought": [70, 75, 80]}),
        ("EMA_Cross", signal_ema_cross, {"fast": [5, 9, 12], "slow": [21, 34, 50]}),
        ("Momentum", signal_momentum, {"lookback": [6, 12, 24], "threshold": [0.01, 0.02, 0.03]}),
        ("Breakout", signal_breakout, {"lookback": [12, 24, 48]}),
        ("MeanRev", signal_mean_reversion, {"period": [24, 48, 72], "std_mult": [1.5, 2.0, 2.5]}),
        ("TrendFollow", signal_trend_follow, {"ema_fast": [5, 9], "ema_slow": [21, 34]}),
        ("VolBreakout", signal_volatility_breakout, {"atr_period": [7, 14], "atr_mult": [1.0, 1.5, 2.0]}),
        ("Swing", signal_swing, {"lookback": [24, 48, 72]}),
    ]
    
    tp_sl_configs = [
        ("atr", 1.5, 1.0), ("atr", 2.0, 1.0), ("atr", 3.0, 1.0),
        ("atr", 2.5, 1.5), ("atr", 3.0, 1.5), ("atr", 4.0, 1.5),
        ("pct", 0.02, 0.01), ("pct", 0.03, 0.015), ("pct", 0.04, 0.02), ("pct", 0.05, 0.02),
    ]
    
    results = []
    total_tests = 0
    
    for strat_name, signal_fn, param_grid in strategies:
        keys = list(param_grid.keys()); values = list(param_grid.values())
        def gen_combos(vals, idx=0, current={}):
            if idx == len(vals): yield dict(current); return
            for v in vals[idx]:
                current[keys[idx]] = v
                yield from gen_combos(vals, idx + 1, current)
        for params in gen_combos(values):
            for base_type, tp_m, sl_m in tp_sl_configs:
                total_tests += 1
                try:
                    result = run_backtest(candles, strat_name, signal_fn,
                        tp_mult=tp_m, sl_mult=sl_m, base_type=base_type, **params)
                    results.append(result)
                except: pass
    
    print(f"Ran {total_tests} backtests\n")
    results.sort(key=lambda r: r.final_capital, reverse=True)
    
    print("=" * 120)
    print(f"{'Rank':<5} {'Strategy':<15} {'Final Capital':>15} {'Return':>10} {'Trades':>8} {'WinRate':>8} {'MaxDD':>8} {'$1M':>5} {'Params'}")
    print("=" * 120)
    
    for i, r in enumerate(results[:30]):
        ret = r.final_capital / r.initial_capital
        print(f"{i+1:<5} {r.strategy:<15} ${r.final_capital:>13,.2f} {ret:>9.1f}x {r.total_trades:>8} {r.win_rate:>7.1f}% {r.max_drawdown_pct:>7.1f}% {'Y' if r.reached_1m else 'N':>5} {r.params}")
    
    millionaires = [r for r in results if r.reached_1m]
    if millionaires:
        print(f"\n*** {len(millionaires)} strategies reached $1,000,000! ***")
        for r in millionaires[:10]:
            print(f"  {r.strategy}: ${r.final_capital:,.2f} | {r.total_trades} trades | {r.win_rate:.1f}% WR | Hit $1M at {r.reached_1m_at}")
            print(f"    Params: {r.params}")
    else:
        print(f"\nNo strategies reached $1,000,000")
        best = results[0]
        print(f"   Best: {best.strategy} -> ${best.final_capital:,.2f} ({best.final_capital/best.initial_capital:.1f}x)")
    
    summary = []
    for r in results[:50]:
        summary.append({
            "strategy": r.strategy, "params": r.params,
            "final_capital": round(r.final_capital, 2),
            "return_x": round(r.final_capital / r.initial_capital, 2),
            "trades": r.total_trades, "wins": r.wins, "losses": r.losses,
            "win_rate": round(r.win_rate, 1), "max_drawdown": round(r.max_drawdown_pct, 1),
            "reached_1m": r.reached_1m, "reached_1m_at": r.reached_1m_at,
        })
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "backtest_results.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\nTop 50 results saved to data/backtest_results.json")

if __name__ == "__main__":
    optimize()
