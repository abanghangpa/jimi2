#!/usr/bin/env python3
"""
Strategy Runner Backtest — tests all strategies through the StrategyRunner.
Includes vol gate (Option A) + BB+mom6 strategy (Option B).

Usage:
    python scripts/backtest_strategies.py eth_15m_merged.csv
    python scripts/backtest_strategies.py eth_15m_merged.csv --start 2026-01-01
    python scripts/backtest_strategies.py eth_15m_merged.csv --no-vol-gate  (for comparison)
"""
import sys, os, argparse, json, time
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config import CONFIG
from src.utils.data_handler import load_data, resample_ohlcv
from src.utils.indicators import calc_atr, calc_vol_ratio, calc_ema, calc_rsi
from src.strategies import create_runner
try:
    from src.strategies.runner import check_volatility_gate
except ImportError:
    def check_volatility_gate(*a, **kw):
        return True, 0, "no_gate"

def prepare_data(df_15m, cfg):
    """Compute indicators needed by strategies."""
    df_15m['atr'] = calc_atr(df_15m['High'], df_15m['Low'], df_15m['Close'], cfg.get('ATR_PERIOD', 14))
    df_15m['vol_ratio'] = calc_vol_ratio(df_15m['Volume'])
    df_15m['ema_200'] = calc_ema(df_15m['Close'], 200)
    df_15m['rsi'] = calc_rsi(df_15m['Close'], 14)
    df_1h = resample_ohlcv(df_15m, '1H')
    return df_15m, df_1h

def get_candles_1h_up_to(df_1h, ts, max_bars=120):
    """Get 1h candles up to timestamp ts."""
    mask = df_1h['Open time'] <= ts
    subset = df_1h[mask].tail(max_bars)
    if len(subset) == 0:
        return []
    return [[row['Open time'].timestamp() * 1000,
             float(row['Open']), float(row['High']),
             float(row['Low']), float(row['Close']),
             float(row['Volume'])] for _, row in subset.iterrows()]

def check_outcome(df_15m, bar_idx, direction, entry, sl, tp1, lookforward=200):
    """Check outcome of a signal over next N bars."""
    end_idx = min(bar_idx + lookforward, len(df_15m))
    for j in range(bar_idx + 1, end_idx):
        high = float(df_15m['High'].iloc[j])
        low = float(df_15m['Low'].iloc[j])
        if direction == 'LONG':
            if high >= tp1:
                return 'WIN', j - bar_idx
            if low <= sl:
                return 'LOSS', j - bar_idx
        else:
            if low <= tp1:
                return 'WIN', j - bar_idx
            if high >= sl:
                return 'LOSS', j - bar_idx
    return 'TIMEOUT', lookforward

def main():
    parser = argparse.ArgumentParser(description='Strategy Runner Backtest')
    parser.add_argument('csv', help='Path to 15m OHLCV CSV')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--step', type=int, default=4, help='Evaluate every Nth bar (default=4 = 1h)')
    parser.add_argument('--lookforward', type=int, default=200, help='Bars to look forward (default=200)')
    parser.add_argument('--no-vol-gate', action='store_true', help='Disable vol gate for comparison')
    parser.add_argument('--export', help='Export results to JSON')
    args = parser.parse_args()

    cfg = dict(CONFIG)
    if args.no_vol_gate:
        cfg['VOL_GATE_ENABLED'] = False
        print("=== VOL GATE: DISABLED ===")
    else:
        cfg['VOL_GATE_ENABLED'] = True
        print("=== VOL GATE: ENABLED (48h, 2.5%) ===")

    print("Loading data...")
    df_15m = load_data(args.csv)
    print(f"  Loaded {len(df_15m):,} bars")

    if args.start:
        df_15m = df_15m[df_15m['Open time'] >= args.start].reset_index(drop=True)
    if args.end:
        df_15m = df_15m[df_15m['Open time'] <= args.end].reset_index(drop=True)
    if args.start or args.end:
        print(f"  Filtered to {len(df_15m):,} bars: {df_15m['Open time'].iloc[0]} -> {df_15m['Open time'].iloc[-1]}")

    print("Computing indicators...")
    df_15m, df_1h = prepare_data(df_15m, cfg)

    # Build 1h index map
    df_1h_map = {}
    for _, row in df_1h.iterrows():
        ts = row['Open time']
        df_1h_map[ts] = row

    warmup = 200  # bars for EMA200 warmup
    print(f"\nRunning backtest from bar {warmup} to {len(df_15m)}, step={args.step}...")

    runner = create_runner(config=cfg)
    print(f"Strategies: {[s.name for s in runner.strategies]}")

    results = []
    signals_by_strategy = {}
    total_checked = 0
    position = None  # Active position: {direction, entry, sl, tp1, open_bar, strategy}
    HOLD_BARS = 32  # 8h = 32 bars on 15m

    t0 = time.time()
    for i in range(warmup, len(df_15m), args.step):
        ts = df_15m['Open time'].iloc[i]
        price = float(df_15m['Close'].iloc[i])
        high = float(df_15m['High'].iloc[i])
        low = float(df_15m['Low'].iloc[i])
        atr = float(df_15m['atr'].iloc[i]) if not pd.isna(df_15m['atr'].iloc[i]) else 0
        vol_ratio = float(df_15m['vol_ratio'].iloc[i]) if not pd.isna(df_15m['vol_ratio'].iloc[i]) else 0
        ema_200 = float(df_15m['ema_200'].iloc[i]) if not pd.isna(df_15m['ema_200'].iloc[i]) else 0

        # Check existing position for TP/SL/timeout
        if position:
            bars_held = i - position['open_bar']
            outcome = None
            exit_price = None

            if position['direction'] == 'LONG':
                if high >= position['tp1']:
                    outcome = 'WIN'; exit_price = position['tp1']
                elif low <= position['sl']:
                    outcome = 'LOSS'; exit_price = position['sl']
            else:
                if low <= position['tp1']:
                    outcome = 'WIN'; exit_price = position['tp1']
                elif high >= position['sl']:
                    outcome = 'LOSS'; exit_price = position['sl']

            if not outcome and bars_held >= HOLD_BARS:
                outcome = 'TIMEOUT'; exit_price = price

            if outcome:
                result = {
                    'bar_idx': position['open_bar'],
                    'timestamp': str(position['open_ts']),
                    'strategy': position['strategy'],
                    'direction': position['direction'],
                    'conviction': position['conviction'],
                    'entry': position['entry'],
                    'sl': position['sl'],
                    'tp1': position['tp1'],
                    'sl_pct': position['sl_pct'],
                    'tp1_pct': position['tp1_pct'],
                    'rr1': position['rr1'],
                    'outcome': outcome,
                    'bars_held': bars_held,
                    'reason': position['reason'],
                }
                results.append(result)
                strat = position['strategy']
                if strat not in signals_by_strategy:
                    signals_by_strategy[strat] = {'total': 0, 'wins': 0, 'losses': 0, 'timeout': 0}
                signals_by_strategy[strat]['total'] += 1
                if outcome == 'WIN':
                    signals_by_strategy[strat]['wins'] += 1
                elif outcome == 'LOSS':
                    signals_by_strategy[strat]['losses'] += 1
                else:
                    signals_by_strategy[strat]['timeout'] += 1
                position = None

        # Only look for new signals if no position open
        if not position:
            data = {
                'timestamp': ts,
                'price': price,
                'atr': atr,
                'vol_ratio': vol_ratio,
                'ema_200': ema_200,
            }

            candles_1h = get_candles_1h_up_to(df_1h, ts, max_bars=120)
            kwargs = {'candles_1h': candles_1h}

            signals = runner.run_all(data, df_15m=df_15m, idx=i, **kwargs)
            if signals:
                sig = signals[0]  # best signal
                position = {
                    'direction': sig.direction,
                    'entry': sig.entry,
                    'sl': sig.sl,
                    'tp1': sig.tp1,
                    'open_bar': i,
                    'open_ts': ts,
                    'strategy': sig.strategy_name,
                    'conviction': sig.conviction,
                    'sl_pct': sig.sl_pct,
                    'tp1_pct': sig.tp1_pct,
                    'rr1': sig.rr1,
                    'reason': sig.reason,
                }

        total_checked += 1
        if total_checked % 500 == 0:
            elapsed = time.time() - t0
            total_signals = sum(s['total'] for s in signals_by_strategy.values())
            pos_info = f"POS={position['direction']}@{position['entry']:.0f}" if position else "FLAT"
            print(f"  Bar {i}/{len(df_15m)} ({elapsed:.0f}s) — {total_signals} trades — {pos_info}", flush=True)

    elapsed = time.time() - t0
    print(f"\nBacktest complete in {elapsed:.0f}s")
    print(f"Bars checked: {total_checked}")
    print(f"Total signals: {sum(s['total'] for s in signals_by_strategy.values())}")
    print(f"Vol gate skips: {getattr(runner, 'vol_gate_skips', 0)}")

    # === REPORT ===
    print("\n" + "=" * 80)
    print("STRATEGY PERFORMANCE REPORT")
    print("=" * 80)

    # Overall
    total = len(results)
    wins = sum(1 for r in results if r['outcome'] == 'WIN')
    losses = sum(1 for r in results if r['outcome'] == 'LOSS')
    wr = wins / total * 100 if total > 0 else 0

    # Simulate capital
    capital = 200
    peak = capital
    max_dd = 0
    for r in results:
        if r['outcome'] == 'WIN':
            pnl = capital * 0.05 * r['rr1']  # 5% risk, RR-based profit
        elif r['outcome'] == 'LOSS':
            pnl = -capital * 0.05  # 5% risk
        else:
            pnl = 0
        capital += pnl
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    print(f"\n{'OVERALL':<30} {'Total':>7} {'Win':>7} {'Loss':>7} {'WR':>7} {'Final$':>10} {'MaxDD':>8}")
    print(f"{'─' * 30} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 10} {'─' * 8}")
    print(f"{'All Strategies':<30} {total:>7} {wins:>7} {losses:>7} {wr:>6.1f}% {capital:>10,.0f} {max_dd:>7.1f}%")

    print(f"\n{'BY STRATEGY':<30} {'Total':>7} {'Win':>7} {'Loss':>7} {'WR':>7} {'PF':>7}")
    print(f"{'─' * 30} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7}")

    sorted_strats = sorted(signals_by_strategy.items(), key=lambda x: x[1]['wins'] / max(x[1]['total'], 1), reverse=True)
    for strat, stats in sorted_strats:
        t = stats['total']
        w = stats['wins']
        l = stats['losses']
        to = stats['timeout']
        strat_wr = w / t * 100 if t > 0 else 0
        # Profit factor: sum of wins / sum of losses (approximate)
        pf = w / l if l > 0 else float('inf') if w > 0 else 0
        print(f"{strat:<30} {t:>7} {w:>7} {l:>7} {strat_wr:>6.1f}% {pf:>6.2f}")

    if args.export:
        with open(args.export, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nExported {len(results)} results to {args.export}")

if __name__ == '__main__':
    main()
