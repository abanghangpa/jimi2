
#!/usr/bin/env python3
"""
Backtest 8 proven strategies: Feb 2 - June 6, 2026
"""
import sys, os, json, time
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data, resample_ohlcv
from src.utils.indicators import calc_atr, calc_vol_ratio, calc_ema, calc_rsi
from src.strategies import create_runner

START_DATE = "2026-02-02"
END_DATE = "2026-06-06"
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.001  # 0.10% round trip

# Only test the 8 proven strategies
ENABLED_STRATEGIES = [
    "whale_watch", "funding_arb", "orderbook_imbalance", "failed_breakout",
    "positioning_fade", "trade_flow", "structural_break", "regime_switch"
]

# Strategy-specific configs (from optimization)
STRAT_CONFIGS = {
    "whale_watch": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 8, "min_conv": 0.5},
    "funding_arb": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12, "min_conv": 0.5},
    "orderbook_imbalance": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5},
    "failed_breakout": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.7},
    "positioning_fade": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5},
    "trade_flow": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5},
    "structural_break": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.5},
    "regime_switch": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5},
}

t0 = time.time()
print(f"Loading ETH 15m data...")
df = load_data("/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv")

# Filter date range
df['Open time'] = pd.to_datetime(df['Open time'])
mask = (df['Open time'] >= START_DATE) & (df['Open time'] <= END_DATE)
df = df[mask].reset_index(drop=True)
print(f"  Period: {df['Open time'].iloc[0]} to {df['Open time'].iloc[-1]}")
print(f"  Bars: {len(df)}")

# Compute indicators
cfg = CONFIG
df['atr'] = calc_atr(df['High'], df['Low'], df['Close'], cfg.get('ATR_PERIOD', 14))
df['vol_ratio'] = calc_vol_ratio(df['Volume'])
df['ema_200'] = calc_ema(df['Close'], 200)
df['rsi'] = calc_rsi(df['Close'], 14)

# Resample to 1h
df_1h = resample_ohlcv(df, '1H')
df_1h['atr'] = calc_atr(df_1h['High'], df_1h['Low'], df_1h['Close'], cfg.get('ATR_PERIOD', 14))
df_1h['ema_200'] = calc_ema(df_1h['Close'], 200)

# Create strategy runner
runner = create_runner(config=cfg)

# Filter to only enabled strategies
runner.strategies = [s for s in runner.strategies if s.name in ENABLED_STRATEGIES]
print(f"  Strategies: {[s.name for s in runner.strategies]}")

# Backtest
print(f"\nRunning backtest...")
trades = []
capital = INITIAL_CAPITAL
peak_capital = INITIAL_CAPITAL
max_dd = 0
open_positions = []

for i in range(200, len(df)):
    row = df.iloc[i]
    ts = row['Open time']
    price = float(row['Close'])
    high = float(row['High'])
    low = float(row['Low'])
    atr = float(row['atr']) if not pd.isna(row['atr']) else 0
    vol_ratio = float(row['vol_ratio']) if not pd.isna(row['vol_ratio']) else 0
    ema_200 = float(row['ema_200']) if not pd.isna(row['ema_200']) else 0
    rsi = float(row['rsi']) if not pd.isna(row['rsi']) else 50

    # Check open positions for TP/SL
    closed = []
    for pos in open_positions:
        bars_held = i - pos['entry_idx']
        max_bars = pos['hold_hours'] * 4  # 15m bars
        
        if pos['direction'] == 'LONG':
            if high >= pos['tp']:
                pnl = pos['size'] * (pos['tp'] - pos['entry']) / pos['entry'] - pos['fee']
                capital += pnl
                trades.append({**pos, 'exit': pos['tp'], 'pnl': pnl, 'outcome': 'WIN', 'bars': bars_held})
                closed.append(pos)
            elif low <= pos['sl']:
                pnl = pos['size'] * (pos['sl'] - pos['entry']) / pos['entry'] - pos['fee']
                capital += pnl
                trades.append({**pos, 'exit': pos['sl'], 'pnl': pnl, 'outcome': 'LOSS', 'bars': bars_held})
                closed.append(pos)
            elif bars_held >= max_bars:
                pnl = pos['size'] * (price - pos['entry']) / pos['entry'] - pos['fee']
                capital += pnl
                outcome = 'WIN' if pnl > 0 else 'LOSS'
                trades.append({**pos, 'exit': price, 'pnl': pnl, 'outcome': outcome, 'bars': bars_held})
                closed.append(pos)
        else:  # SHORT
            if low <= pos['tp']:
                pnl = pos['size'] * (pos['entry'] - pos['tp']) / pos['entry'] - pos['fee']
                capital += pnl
                trades.append({**pos, 'exit': pos['tp'], 'pnl': pnl, 'outcome': 'WIN', 'bars': bars_held})
                closed.append(pos)
            elif high >= pos['sl']:
                pnl = pos['size'] * (pos['entry'] - pos['sl']) / pos['entry'] - pos['fee']
                capital += pnl
                trades.append({**pos, 'exit': pos['sl'], 'pnl': pnl, 'outcome': 'LOSS', 'bars': bars_held})
                closed.append(pos)
            elif bars_held >= max_bars:
                pnl = pos['size'] * (pos['entry'] - price) / pos['entry'] - pos['fee']
                capital += pnl
                outcome = 'WIN' if pnl > 0 else 'LOSS'
                trades.append({**pos, 'exit': price, 'pnl': pnl, 'outcome': outcome, 'bars': bars_held})
                closed.append(pos)
    
    for p in closed:
        open_positions.remove(p)
    
    # Update peak/dd
    if capital > peak_capital:
        peak_capital = capital
    dd = (peak_capital - capital) / peak_capital * 100 if peak_capital > 0 else 0
    if dd > max_dd:
        max_dd = dd
    
    # Skip if too many open positions
    if len(open_positions) >= 3:
        continue
    
    # Build data dict for strategies
    data = {
        'price': price, 'high': high, 'low': low, 'close': price,
        'atr': atr, 'vol_ratio': vol_ratio, 'ema_200': ema_200, 'rsi': rsi,
        'timestamp': ts,
        'direction': 'NEUTRAL',
    }
    
    # Get 1h candles for strategies that need them
    candles_1h = []
    mask_1h = df_1h['Open time'] <= ts
    subset = df_1h[mask_1h].tail(60)
    if len(subset) > 0:
        def _to_ms(v):
            if hasattr(v, 'timestamp'):
                return v.timestamp() * 1000
            return float(v)
        candles_1h = [[_to_ms(r['Open time']), float(r['Open']), float(r['High']), 
                        float(r['Low']), float(r['Close']), float(r['Volume'])] 
                       for _, r in subset.iterrows()]
    
    # Run strategies
    signals = runner.run_all(data, df_15m=df, idx=i, candles_1h=candles_1h)
    
    # Take best signal that meets conviction threshold
    for sig in signals:
        if sig is None:
            continue
        
        strat_name = sig.strategy_name
        if strat_name not in ENABLED_STRATEGIES:
            continue
        
        cfg_strat = STRAT_CONFIGS.get(strat_name, {})
        min_conv = cfg_strat.get('min_conv', 0.5)
        
        if sig.conviction < min_conv:
            continue
        
        # Check direction filter
        dir_filter = cfg_strat.get('direction')
        if dir_filter and sig.direction != dir_filter:
            continue
        
        # Calculate TP/SL from strategy config
        tp_pct = cfg_strat.get('tp_pct', 1.0) / 100
        sl_pct = cfg_strat.get('sl_pct', 1.0) / 100
        
        if sig.direction == 'LONG':
            entry = price * 1.001  # slippage
            tp = entry * (1 + tp_pct)
            sl = entry * (1 - sl_pct)
        else:
            entry = price * 0.999
            tp = entry * (1 - tp_pct)
            sl = entry * (1 + sl_pct)
        
        # Position size
        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            continue
        size = min(capital * RISK_PCT / sl_dist, capital * LEVERAGE / entry)
        if size <= 0:
            continue
        
        fee = size * entry * FEE_RATE
        
        pos = {
            'strategy': strat_name,
            'direction': sig.direction,
            'entry': round(entry, 2),
            'tp': round(tp, 2),
            'sl': round(sl, 2),
            'size': round(size, 6),
            'fee': fee,
            'hold_hours': cfg_strat.get('hold_hours', 8),
            'entry_idx': i,
            'conviction': sig.conviction,
            'ts': str(ts),
        }
        open_positions.append(pos)
        break  # Only one trade per bar

# Close remaining positions at last price
for pos in open_positions:
    price = float(df['Close'].iloc[-1])
    if pos['direction'] == 'LONG':
        pnl = pos['size'] * (price - pos['entry']) / pos['entry'] - pos['fee']
    else:
        pnl = pos['size'] * (pos['entry'] - price) / pos['entry'] - pos['fee']
    capital += pnl
    outcome = 'WIN' if pnl > 0 else 'LOSS'
    trades.append({**pos, 'exit': price, 'pnl': pnl, 'outcome': outcome, 'bars': len(df) - pos['entry_idx']})

# Print results
print(f"\n{'='*80}")
print(f"BACKTEST RESULTS: {START_DATE} to {END_DATE}")
print(f"{'='*80}")
print(f"Initial Capital: ${INITIAL_CAPITAL:.2f}")
print(f"Final Capital: ${capital:.2f}")
print(f"Return: {((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100):.1f}%")
print(f"Total Trades: {len(trades)}")
wins = [t for t in trades if t['outcome'] == 'WIN']
losses = [t for t in trades if t['outcome'] == 'LOSS']
print(f"Wins: {len(wins)} | Losses: {len(losses)}")
wr = len(wins) / len(trades) * 100 if trades else 0
print(f"Win Rate: {wr:.1f}%")
gross_profit = sum(t['pnl'] for t in wins) if wins else 0
gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0
pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
print(f"Profit Factor: {pf:.2f}")
print(f"Max Drawdown: {max_dd:.1f}%")
print(f"Gross Profit: ${gross_profit:.2f}")
print(f"Gross Loss: ${gross_loss:.2f}")
print(f"Fees Paid: ${sum(t['fee'] for t in trades):.2f}")

# Per-strategy breakdown
print(f"\n{'='*80}")
print(f"PER-STRATEGY BREAKDOWN")
print(f"{'='*80}")
from collections import defaultdict
strat_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0})
for t in trades:
    s = t['strategy']
    strat_stats[s]['trades'] += 1
    strat_stats[s]['pnl'] += t['pnl']
    if t['outcome'] == 'WIN':
        strat_stats[s]['wins'] += 1
    else:
        strat_stats[s]['losses'] += 1

for s, v in sorted(strat_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
    wr_s = v['wins'] / v['trades'] * 100 if v['trades'] > 0 else 0
    g_profit = sum(t['pnl'] for t in trades if t['strategy'] == s and t['pnl'] > 0)
    g_loss = abs(sum(t['pnl'] for t in trades if t['strategy'] == s and t['pnl'] < 0))
    pf_s = g_profit / g_loss if g_loss > 0 else float('inf')
    status = "✅" if pf_s >= 2.0 and wr_s >= 70 else "❌"
    print(f"{status} {s:25s} | Trades: {v['trades']:4d} | WR: {wr_s:5.1f}% | PF: {pf_s:5.2f} | PnL: ${v['pnl']:+8.2f}")

# Monthly breakdown
print(f"\n{'='*80}")
print(f"MONTHLY BREAKDOWN")
print(f"{'='*80}")
monthly = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
for t in trades:
    month = t['ts'][:7]
    monthly[month]['trades'] += 1
    monthly[month]['pnl'] += t['pnl']
    if t['outcome'] == 'WIN':
        monthly[month]['wins'] += 1

for month in sorted(monthly.keys()):
    v = monthly[month]
    wr_m = v['wins'] / v['trades'] * 100 if v['trades'] > 0 else 0
    print(f"  {month} | Trades: {v['trades']:4d} | WR: {wr_m:5.1f}% | PnL: ${v['pnl']:+8.2f}")

print(f"\nDone in {time.time() - t0:.1f}s")


