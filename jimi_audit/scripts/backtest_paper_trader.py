#!/usr/bin/env python3
"""
Paper Trader Backtest — Scanner + Momentum Hybrid
Capital: $200 | Risk: 5% | Leverage: 10x | Compounding
TP: 0.30% | SL: 0.20% | Hold: 8h
HTX fees: 0.02% maker/side | Slippage: 0.1% | Order delay: 1 candle (1h)
Random start window to avoid bias
"""
import json, random, sys
from datetime import datetime, timezone, timedelta
import os

BASE = "/root/.openclaw/workspace/jimi_audit"
DATA_FILE = os.path.join(BASE, "data", "eth_full_1h.json")

# === PARAMETERS (matching paper_trader.py) ===
INITIAL_CAPITAL = 200.0
RISK_PCT = 0.05      # 5% of capital per trade
LEVERAGE = 20        # 10x
TP_PCT = 0.003       # 0.30%
SL_PCT = 0.002       # 0.20%
HOLD_HOURS = 8       # 8 hour hold
MOM_PERIOD = 12      # 12h momentum lookback
MOM_THRESHOLD = 0.03 # 3% momentum threshold
FEE_RATE = 0.0002    # HTX maker fee 0.02% per side
SLIPPAGE = 0.001     # 0.1% slippage
ORDER_DELAY = 1      # 1 candle delay (1h) for order execution
DD_STOP = 0.50       # 50% drawdown circuit breaker
DD_COOLDOWN = 24     # 24h cooldown after DD trigger
MIN_PHASE0 = 0.15    # Minimum phase0 for scanner signal
RANDOM_SEEDS = [42, 137, 256, 404, 777, 1024, 2048, 3141, 4096, 8080]

def load_data():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    # Convert to OHLCV dicts
    candles = []
    for c in raw:
        candles.append({
            'ts': c[0],
            'o': float(c[1]),
            'h': float(c[2]),
            'l': float(c[3]),
            'c': float(c[4]),
            'v': float(c[5]) if len(c) > 5 else 0,
        })
    return candles

def ema(closes, period):
    e = [0.0] * len(closes)
    e[0] = closes[0]
    k = 2 / (period + 1)
    for i in range(1, len(closes)):
        e[i] = closes[i] * k + e[i-1] * (1 - k)
    return e

def rsi(closes, period):
    r = [None] * len(closes)
    if len(closes) < period + 1:
        return r
    gs = sum(max(closes[i] - closes[i-1], 0) for i in range(1, period + 1))
    ls = sum(max(closes[i-1] - closes[i], 0) for i in range(1, period + 1))
    if ls > 0:
        r[period] = 100 - (100 / (1 + gs / ls))
    else:
        r[period] = 100
    for i in range(period + 1, len(closes)):
        g = max(closes[i] - closes[i-1], 0)
        l = max(closes[i-1] - closes[i], 0)
        gs = (gs * (period - 1) + g) / period
        ls = (ls * (period - 1) + l) / period
        if ls > 0:
            r[i] = 100 - (100 / (1 + gs / ls))
        else:
            r[i] = 100
    return r

def atr(highs, lows, closes, period=14):
    a = [None] * len(closes)
    if len(closes) < period + 1:
        return a
    tr_sum = 0
    for i in range(1, period + 1):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_sum += tr
    a[period] = tr_sum / period
    for i in range(period + 1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        a[i] = (a[i-1] * (period - 1) + tr) / period
    return a

def compute_indicators(candles):
    closes = [c['c'] for c in candles]
    highs = [c['h'] for c in candles]
    lows = [c['l'] for c in candles]
    
    # EMAs for trend
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    
    # RSI
    r14 = rsi(closes, 14)
    
    # ATR for volatility
    a14 = atr(highs, lows, closes, 14)
    
    # Volume MA (20-period)
    vols = [c['v'] for c in candles]
    vol_ma = [None] * len(vols)
    for i in range(19, len(vols)):
        vol_ma[i] = sum(vols[i-19:i+1]) / 20
    
    return e9, e21, e50, e200, r14, a14, vol_ma

def get_scanner_signal(i, candles, e9, e21, e50, e200, r14, a14, vol_ma):
    """
    Simulate scanner.py multi-factor direction.
    Combines: EMA trend, RSI, volume, ATR regime, momentum structure.
    Returns: direction ('LONG'/'SHORT'/None), phase0 (0-1), swing, trend
    """
    if i < 200 or e200[i] is None or r14[i] is None or a14[i] is None:
        return None, 0, '', ''
    
    c = candles[i]['c']
    
    # === TREND (EMA stack) ===
    ema_bull = e9[i] > e21[i] > e50[i]
    ema_bear = e9[i] < e21[i] < e50[i]
    above_200 = c > e200[i]
    below_200 = c < e200[i]
    
    # === MOMENTUM (RSI + price structure) ===
    rsi_val = r14[i]
    rsi_bull = rsi_val > 50
    rsi_bear = rsi_val < 50
    
    # === VOLATILITY REGIME ===
    atr_val = a14[i]
    atr_pct = atr_val / c if c > 0 else 0
    vol_ok = atr_pct > 0.005  # Min 0.5% ATR for volatility
    
    # === VOLUME ===
    vol_ratio = 0
    if vol_ma[i] and vol_ma[i] > 0:
        vol_ratio = candles[i]['v'] / vol_ma[i]
    vol_high = vol_ratio > 1.0
    
    # === SWING STRUCTURE (higher highs/lows or lower highs/lows) ===
    swing = 'NEUTRAL'
    if i >= 20:
        recent_h = max(candles[j]['h'] for j in range(i-20, i))
        recent_l = min(candles[j]['l'] for j in range(i-20, i))
        if c > recent_h * 0.998:
            swing = 'BULLISH'
        elif c < recent_l * 1.002:
            swing = 'BEARISH'
    
    # === PHASE0 (macro context proxy — using trend consistency) ===
    # Count how many of last 20 candles were in trend direction
    if ema_bull:
        up_count = sum(1 for j in range(max(0,i-20), i) if candles[j]['c'] > e21[j] and e21[j] is not None)
        phase0 = up_count / 20
    elif ema_bear:
        dn_count = sum(1 for j in range(max(0,i-20), i) if candles[j]['c'] < e21[j] and e21[j] is not None)
        phase0 = dn_count / 20
    else:
        phase0 = 0.3  # Neutral
    
    # === SIGNAL LOGIC ===
    direction = None
    trend = 'NEUTRAL'
    
    # Score system
    bull_score = 0
    bear_score = 0
    
    if ema_bull:
        bull_score += 2
        trend = 'UP'
    elif ema_bear:
        bear_score += 2
        trend = 'DOWN'
    
    if above_200:
        bull_score += 1
    elif below_200:
        bear_score += 1
    
    if rsi_bull:
        bull_score += 1
    elif rsi_bear:
        bear_score += 1
    
    if swing == 'BULLISH':
        bull_score += 1
    elif swing == 'BEARISH':
        bear_score += 1
    
    if vol_high:
        if bull_score > bear_score:
            bull_score += 1
        elif bear_score > bull_score:
            bear_score += 1
    
    # Need clear edge
    if bull_score >= 4 and phase0 >= MIN_PHASE0:
        direction = 'LONG'
    elif bear_score >= 4 and phase0 >= MIN_PHASE0:
        direction = 'SHORT'
    
    return direction, phase0, swing, trend

def get_momentum(i, candles):
    """12h momentum direction."""
    if i < MOM_PERIOD + 1:
        return None, 0
    
    current = candles[i]['c']
    past = candles[i - MOM_PERIOD]['c']
    
    if past == 0:
        return None, 0
    
    mom = (current - past) / past
    
    if mom > MOM_THRESHOLD:
        return 'LONG', mom
    elif mom < -MOM_THRESHOLD:
        return 'SHORT', mom
    return None, mom

def run_backtest(candles, seed, start_idx=None):
    """Run single backtest from a given start point."""
    random.seed(seed)
    
    N = len(candles)
    e9, e21, e50, e200, r14, a14, vol_ma = compute_indicators(candles)
    
    # Random start between 2018-01-01 and 2020-01-01 (need 200 bars warmup)
    # Find index for 2018-01-01
    start_2018 = None
    start_2020 = None
    for idx, c in enumerate(candles):
        dt = datetime.fromtimestamp(c['ts']/1000, tz=timezone.utc)
        if dt.year >= 2018 and start_2018 is None:
            start_2018 = idx
        if dt.year >= 2020 and start_2020 is None:
            start_2020 = idx
            break
    
    if start_2018 is None:
        start_2018 = 200
    if start_2020 is None:
        start_2020 = N - 1000
    
    if start_idx is None:
        start_idx = random.randint(start_2018, start_2020)
    
    # State
    capital = INITIAL_CAPITAL
    peak_capital = capital
    position = None
    pending_order = None  # For order delay
    dd_cooldown_until = None
    dd_triggered = 0
    trades = []
    equity_curve = []
    
    i = start_idx
    while i < N:
        c = candles[i]
        dt = datetime.fromtimestamp(c['ts']/1000, tz=timezone.utc)
        
        # === DRAWDOWN CHECK ===
        if capital > peak_capital:
            peak_capital = capital
        
        if dd_cooldown_until and dt < dd_cooldown_until:
            i += 1
            continue
        elif dd_cooldown_until:
            dd_cooldown_until = None
        
        dd_pct = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
        if dd_pct >= DD_STOP:
            dd_cooldown_until = dt + timedelta(hours=DD_COOLDOWN)
            dd_triggered += 1
            i += 1
            continue
        
        # === PROCESS PENDING ORDER (delay execution) ===
        if pending_order and position is None:
            entry_price = c['c'] * (1 + SLIPPAGE) if pending_order == 'LONG' else c['c'] * (1 - SLIPPAGE)
            
            if pending_order == 'LONG':
                tp = entry_price * (1 + TP_PCT)
                sl = entry_price * (1 - SL_PCT)
            else:
                tp = entry_price * (1 - TP_PCT)
                sl = entry_price * (1 + SL_PCT)
            
            sl_dist = abs(entry_price - sl)
            if sl_dist > 0:
                risk_amount = capital * RISK_PCT
                size = risk_amount / sl_dist
                max_size = (capital * LEVERAGE) / entry_price
                size = min(size, max_size)
                
                if size > 0:
                    position = {
                        'direction': pending_order,
                        'entry': entry_price,
                        'tp': tp,
                        'sl': sl,
                        'size': size,
                        'opened_at': dt,
                        'capital_at_entry': capital,
                    }
            pending_order = None
        
        # === CHECK EXISTING POSITION ===
        if position:
            pos = position
            outcome = None
            exit_price = None
            
            # Check TP/SL using high/low
            if pos['direction'] == 'LONG':
                if c['h'] >= pos['tp']:
                    outcome = 'WIN'
                    exit_price = pos['tp']
                elif c['l'] <= pos['sl']:
                    outcome = 'LOSS'
                    exit_price = pos['sl']
            else:
                if c['l'] <= pos['tp']:
                    outcome = 'WIN'
                    exit_price = pos['tp']
                elif c['h'] >= pos['sl']:
                    outcome = 'LOSS'
                    exit_price = pos['sl']
            
            # Time-based close at 8h
            if outcome is None:
                age = dt - pos['opened_at']
                if age >= timedelta(hours=HOLD_HOURS):
                    exit_price = c['c']
                    if pos['direction'] == 'LONG':
                        outcome = 'WIN' if exit_price > pos['entry'] else 'LOSS'
                    else:
                        outcome = 'WIN' if exit_price < pos['entry'] else 'LOSS'
            
            if outcome:
                # Calculate P&L
                if pos['direction'] == 'LONG':
                    pnl_raw = (exit_price - pos['entry']) * pos['size']
                else:
                    pnl_raw = (pos['entry'] - exit_price) * pos['size']
                
                fee_cost = pos['entry'] * pos['size'] * FEE_RATE * 2
                pnl = pnl_raw - fee_cost
                capital += pnl
                
                trades.append({
                    'direction': pos['direction'],
                    'entry': pos['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'outcome': outcome,
                    'opened_at': pos['opened_at'],
                    'closed_at': dt,
                    'capital_after': capital,
                })
                
                position = None
        
        # === GENERATE SIGNAL (if no position) ===
        if position is None and pending_order is None:
            scan_dir, phase0, swing, trend = get_scanner_signal(i, candles, e9, e21, e50, e200, r14, a14, vol_ma)
            mom_dir, mom_val = get_momentum(i, candles)
            
            signal = None
            if scan_dir in ('LONG', 'SHORT') and phase0 >= MIN_PHASE0:
                if mom_dir == scan_dir:
                    signal = scan_dir  # Both agree
                elif mom_dir is None:
                    signal = scan_dir  # Scanner only, momentum neutral
                # Conflict: skip
            elif mom_dir and abs(mom_val) > 0.05:
                signal = mom_dir  # Strong momentum alone
            
            if signal:
                pending_order = signal  # Queue for next candle (delay)
        
        # Track equity
        equity_curve.append({
            'ts': c['ts'],
            'equity': capital,
            'dt': dt,
        })
        
        i += 1
    
    return {
        'seed': seed,
        'start_idx': start_idx,
        'start_date': datetime.fromtimestamp(candles[start_idx]['ts']/1000, tz=timezone.utc).isoformat(),
        'end_date': datetime.fromtimestamp(candles[-1]['ts']/1000, tz=timezone.utc).isoformat(),
        'initial_capital': INITIAL_CAPITAL,
        'final_capital': round(capital, 2),
        'return_x': round(capital / INITIAL_CAPITAL, 2),
        'total_pnl': round(capital - INITIAL_CAPITAL, 2),
        'trades': len(trades),
        'wins': sum(1 for t in trades if t['outcome'] == 'WIN'),
        'losses': sum(1 for t in trades if t['outcome'] == 'LOSS'),
        'win_rate': round(sum(1 for t in trades if t['outcome'] == 'WIN') / len(trades) * 100, 1) if trades else 0,
        'max_drawdown': round(max((peak - eq) / peak * 100 for peak, eq in 
            [(max(e['equity'] for e in equity_curve[:j+1]), equity_curve[j]['equity']) 
             for j in range(len(equity_curve))] ) if equity_curve else 0, 1),
        'dd_triggers': dd_triggered,
        'avg_pnl_per_trade': round(sum(t['pnl'] for t in trades) / len(trades), 2) if trades else 0,
        'largest_win': round(max((t['pnl'] for t in trades), default=0), 2),
        'largest_loss': round(min((t['pnl'] for t in trades), default=0), 2),
        'trades_list': trades[-10:],  # Last 10 trades for review
    }

def main():
    print("Loading ETH 1H data...")
    candles = load_data()
    print(f"Loaded {len(candles)} candles")
    
    results = []
    print(f"\nRunning {len(RANDOM_SEEDS)} backtests with random starts...")
    print("=" * 80)
    
    for seed in RANDOM_SEEDS:
        result = run_backtest(candles, seed)
        results.append(result)
        print(f"Seed {seed:5d} | Start: {result['start_date'][:10]} | "
              f"Final: ${result['final_capital']:>10,.2f} | "
              f"Return: {result['return_x']:>6.2f}x | "
              f"Trades: {result['trades']:>4} | "
              f"WR: {result['win_rate']:>5.1f}% | "
              f"MaxDD: {result['max_drawdown']:>5.1f}% | "
              f"DD: {result['dd_triggers']}")
    
    print("=" * 80)
    
    # Summary stats
    finals = [r['final_capital'] for r in results]
    returns = [r['return_x'] for r in results]
    trade_counts = [r['trades'] for r in results]
    win_rates = [r['win_rate'] for r in results if r['trades'] > 0]
    max_dds = [r['max_drawdown'] for r in results]
    
    print(f"\n{'='*80}")
    print(f"SUMMARY ({len(results)} runs)")
    print(f"{'='*80}")
    print(f"Initial Capital:    ${INITIAL_CAPITAL:,.2f}")
    print(f"Risk per Trade:     {RISK_PCT*100:.0f}%")
    print(f"Leverage:           {LEVERAGE}x")
    print(f"TP / SL:            {TP_PCT*100:.2f}% / {SL_PCT*100:.2f}%")
    print(f"Hold:               {HOLD_HOURS}h")
    print(f"Order Delay:        {ORDER_DELAY} candle ({ORDER_DELAY}h)")
    print(f"Slippage:           {SLIPPAGE*100:.1f}%")
    print(f"HTX Fee:            {FEE_RATE*100:.2f}% per side")
    print(f"DD Circuit Breaker: {DD_STOP*100:.0f}% stop, {DD_COOLDOWN}h cooldown")
    print(f"{'='*80}")
    print(f"Final Capital:")
    print(f"  Mean:   ${sum(finals)/len(finals):>10,.2f}")
    print(f"  Median: ${sorted(finals)[len(finals)//2]:>10,.2f}")
    print(f"  Best:   ${max(finals):>10,.2f}")
    print(f"  Worst:  ${min(finals):>10,.2f}")
    print(f"Return Multiple:")
    print(f"  Mean:   {sum(returns)/len(returns):>6.2f}x")
    print(f"  Median: {sorted(returns)[len(returns)//2]:>6.2f}x")
    print(f"  Best:   {max(returns):>6.2f}x")
    print(f"  Worst:  {min(returns):>6.2f}x")
    print(f"Trades per Run:")
    print(f"  Mean:   {sum(trade_counts)/len(trade_counts):>6.0f}")
    print(f"  Total:  {sum(trade_counts):>6}")
    print(f"Win Rate (avg):     {sum(win_rates)/len(win_rates):.1f}%" if win_rates else "Win Rate: N/A")
    print(f"Max Drawdown (avg): {sum(max_dds)/len(max_dds):.1f}%")
    print(f"DD Triggers (total):{sum(r['dd_triggers'] for r in results)}")
    
    # Profitable runs
    profitable = sum(1 for f in finals if f > INITIAL_CAPITAL)
    print(f"\nProfitable runs: {profitable}/{len(results)} ({profitable/len(results)*100:.0f}%)")
    
    # Million dollar runs
    million = sum(1 for f in finals if f >= 1_000_000)
    print(f"Reached $1M: {million}/{len(results)}")
    
    # Best run details
    best = max(results, key=lambda r: r['final_capital'])
    print(f"\n{'='*80}")
    print(f"BEST RUN (Seed {best['seed']})")
    print(f"{'='*80}")
    print(f"Period: {best['start_date'][:10]} to {best['end_date'][:10]}")
    print(f"Capital: ${INITIAL_CAPITAL:,.2f} -> ${best['final_capital']:,.2f} ({best['return_x']}x)")
    print(f"Trades: {best['trades']} ({best['wins']}W/{best['losses']}L) WR: {best['win_rate']}%")
    print(f"Max DD: {best['max_drawdown']}%")
    print(f"Avg PnL/trade: ${best['avg_pnl_per_trade']:.2f}")
    print(f"Largest Win: ${best['largest_win']:.2f}")
    print(f"Largest Loss: ${best['largest_loss']:.2f}")
    
    # Save results
    output_file = os.path.join(BASE, "data", "backtest_paper_trader_results.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")

if __name__ == '__main__':
    main()
