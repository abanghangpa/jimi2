#!/usr/bin/env python3
"""
Event-Based Strategies + Whale Conditioning
Test failed_breakout, structural_break, squeeze_breakout, judas_sweep, positioning_fade
Each paired with whale_watch as state filter.
Target: PF >= 2.0 AND WR >= 75%
"""
import csv, os, sys, json
from datetime import datetime, timedelta
import numpy as np

BASE = "/root/.openclaw/workspace/jimi_audit"
ETH_FILE = os.path.join(BASE, "eth_15m_merged.csv")
DERIV_FILE = os.path.join(BASE, "data", "derivatives_history", "derivatives_collected.csv")
REPORT_DIR = os.path.join(BASE, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)

def load_eth_data(start_date=None, end_date=None):
    bars = []
    with open(ETH_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row['Open time'], '%Y-%m-%d %H:%M:%S')
            if start_date and dt < start_date:
                continue
            if end_date and dt >= end_date:
                continue
            bars.append({
                'dt': dt, 'open': float(row['Open']), 'high': float(row['High']),
                'low': float(row['Low']), 'close': float(row['Close']),
                'volume': float(row['Volume']),
            })
    return bars

def load_derivatives():
    deriv = {}
    with open(DERIV_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.fromisoformat(row['timestamp'])
            dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
            deriv[dt_floor] = {
                'ls_ratio': float(row['ls_ratio']),
                'funding_rate': float(row['funding_rate']),
            }
    return deriv

def get_nearest_deriv(deriv_map, dt, max_hours=2):
    for offset_min in range(0, max_hours * 60 + 1, 1):
        for check in [dt - timedelta(minutes=offset_min), dt + timedelta(minutes=offset_min)]:
            if check in deriv_map:
                return deriv_map[check]
    return None

def compute_atr(bars, period=14):
    trs = []
    atrs = [0.0] * len(bars)
    for i in range(1, len(bars)):
        tr = max(bars[i]['high'] - bars[i]['low'],
                 abs(bars[i]['high'] - bars[i-1]['close']),
                 abs(bars[i]['low'] - bars[i-1]['close']))
        trs.append(tr)
    for i in range(period, len(bars)):
        atrs[i] = np.mean(trs[i-period:i])
    return atrs

def compute_ema(closes, period):
    ema = [0.0] * len(closes)
    if len(closes) <= period:
        return ema
    k = 2.0 / (period + 1)
    ema[period] = np.mean(closes[:period])
    for i in range(period + 1, len(closes)):
        ema[i] = closes[i] * k + ema[i-1] * (1 - k)
    return ema

def compute_bb(closes, period=20, std_mult=2.0):
    """Bollinger Bands."""
    upper = [0.0] * len(closes)
    lower = [0.0] * len(closes)
    middle = [0.0] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i-period+1:i+1]
        sma = np.mean(window)
        std = np.std(window)
        middle[i] = sma
        upper[i] = sma + std_mult * std
        lower[i] = sma - std_mult * std
    return upper, middle, lower

# ============================================================
# STRATEGY IMPLEMENTATIONS
# ============================================================

def detect_failed_breakout(bars, atrs, bb_upper, bb_lower, ema200):
    """
    S01: Failed Breakout
    Price breaks above BB upper (or below lower) then closes back inside.
    This is a discrete event: breach + snap back.
    """
    signals = []
    for i in range(21, len(bars)):
        if atrs[i] <= 0 or bb_upper[i] <= 0:
            continue
        b = bars[i]
        prev = bars[i-1]

        # Bearish: broke above BB upper, closed back inside
        if prev['high'] > bb_upper[i-1] and b['close'] < bb_upper[i]:
            if ema200[i] > 0 and b['close'] > ema200[i]:  # Above EMA = overextended
                signals.append({
                    'idx': i, 'dt': b['dt'], 'direction': 'SHORT',
                    'entry': b['close'], 'atr': atrs[i],
                    'reason': f"Failed breakout above BB ${bb_upper[i]:.2f}",
                })

        # Bullish: broke below BB lower, closed back inside
        if prev['low'] < bb_lower[i-1] and b['close'] > bb_lower[i]:
            if ema200[i] > 0 and b['close'] < ema200[i]:  # Below EMA = overextended
                signals.append({
                    'idx': i, 'dt': b['dt'], 'direction': 'LONG',
                    'entry': b['close'], 'atr': atrs[i],
                    'reason': f"Failed breakout below BB ${bb_lower[i]:.2f}",
                })

    return signals

def detect_structural_break(bars, atrs, lookback=20):
    """
    S10: Structural Break
    Price breaks above 20-bar high or below 20-bar low with momentum close.
    """
    signals = []
    for i in range(lookback + 1, len(bars)):
        if atrs[i] <= 0:
            continue
        b = bars[i]
        window = bars[i-lookback:i]
        swing_high = max(x['high'] for x in window)
        swing_low = min(x['low'] for x in window)

        # Bullish break: close above swing high
        if b['close'] > swing_high and bars[i-1]['close'] <= swing_high:
            signals.append({
                'idx': i, 'dt': b['dt'], 'direction': 'LONG',
                'entry': b['close'], 'atr': atrs[i],
                'reason': f"Structural break above ${swing_high:.2f}",
            })

        # Bearish break: close below swing low
        if b['close'] < swing_low and bars[i-1]['close'] >= swing_low:
            signals.append({
                'idx': i, 'dt': b['dt'], 'direction': 'SHORT',
                'entry': b['close'], 'atr': atrs[i],
                'reason': f"Structural break below ${swing_low:.2f}",
            })

    return signals

def detect_squeeze_breakout(bars, atrs, bb_upper, bb_lower, atr_period=14):
    """
    S02: Squeeze Breakout
    ATR compression (ATR < 50th percentile of recent ATR) followed by expansion.
    Enter in direction of breakout.
    """
    signals = []
    lookback = 48  # 12 hours of 15m bars for ATR percentile

    for i in range(lookback + atr_period + 1, len(bars)):
        if atrs[i] <= 0:
            continue
        b = bars[i]

        # Check if ATR was compressed recently
        recent_atrs = [atrs[j] for j in range(i-lookback, i) if atrs[j] > 0]
        if not recent_atrs:
            continue
        atr_median = np.median(recent_atrs)

        # Squeeze: previous ATR was below median, current ATR expanding
        if atrs[i-1] >= atr_median * 0.7:
            continue  # Not in squeeze
        if atrs[i] < atr_median * 0.8:
            continue  # Not expanding enough

        # Direction from close vs open
        if b['close'] > b['open']:  # Bullish breakout
            signals.append({
                'idx': i, 'dt': b['dt'], 'direction': 'LONG',
                'entry': b['close'], 'atr': atrs[i],
                'reason': f"Squeeze breakout LONG ATR={atrs[i]:.2f} (median={atr_median:.2f})",
            })
        elif b['close'] < b['open']:  # Bearish breakout
            signals.append({
                'idx': i, 'dt': b['dt'], 'direction': 'SHORT',
                'entry': b['close'], 'atr': atrs[i],
                'reason': f"Squeeze breakout SHORT ATR={atrs[i]:.2f} (median={atr_median:.2f})",
            })

    return signals

def detect_judas_sweep(bars, atrs, lookback=20):
    """
    S22: Judas Sweep
    Price sweeps past swing high/low then closes back inside.
    Similar to liquidity_grab but using fractal swings.
    """
    signals = []
    for i in range(lookback + 1, len(bars)):
        if atrs[i] <= 0:
            continue
        b = bars[i]
        window = bars[i-lookback:i]
        swing_high = max(x['high'] for x in window)
        swing_low = min(x['low'] for x in window)

        # Bearish judas: swept above high, closed below
        if b['high'] > swing_high and b['close'] < swing_high:
            signals.append({
                'idx': i, 'dt': b['dt'], 'direction': 'SHORT',
                'entry': b['close'], 'atr': atrs[i],
                'reason': f"Judas sweep above ${swing_high:.2f}",
            })

        # Bullish judas: swept below low, closed above
        if b['low'] < swing_low and b['close'] > swing_low:
            signals.append({
                'idx': i, 'dt': b['dt'], 'direction': 'LONG',
                'entry': b['close'], 'atr': atrs[i],
                'reason': f"Judas sweep below ${swing_low:.2f}",
            })

    return signals

def detect_positioning_fade(bars, atrs, deriv_map, ls_extreme_high=2.5, ls_extreme_low=1.5):
    """
    S04: Positioning Fade
    Extreme L/S ratio + price moving against the crowd.
    """
    signals = []
    for i in range(20, len(bars)):
        if atrs[i] <= 0:
            continue
        b = bars[i]
        deriv = get_nearest_deriv(deriv_map, b['dt'])
        if deriv is None:
            continue

        ls = deriv['ls_ratio']

        # Extreme short positioning → LONG (fade the crowd)
        if ls < ls_extreme_low:
            if b['close'] > b['open']:  # Price already moving up
                signals.append({
                    'idx': i, 'dt': b['dt'], 'direction': 'LONG',
                    'entry': b['close'], 'atr': atrs[i], 'ls_ratio': ls,
                    'reason': f"Positioning fade LONG ls={ls:.3f}",
                })

        # Extreme long positioning → SHORT
        if ls > ls_extreme_high:
            if b['close'] < b['open']:
                signals.append({
                    'idx': i, 'dt': b['dt'], 'direction': 'SHORT',
                    'entry': b['close'], 'atr': atrs[i], 'ls_ratio': ls,
                    'reason': f"Positioning fade SHORT ls={ls:.3f}",
                })

    return signals

# ============================================================
# WHALE FILTER
# ============================================================

def apply_whale_filter(signals, deriv_map, ls_long=1.7, ls_short=2.1, mode='wgated'):
    """Apply whale conditioning. In wgated mode: whale must not disagree."""
    filtered = []
    for sig in signals:
        deriv = get_nearest_deriv(deriv_map, sig['dt'])
        if deriv is None:
            continue
        ls = deriv['ls_ratio']

        if mode == 'wgated':
            if sig['direction'] == 'SHORT' and ls <= 1.0:
                continue  # Whale is long, disagrees with short
            if sig['direction'] == 'LONG' and ls >= 1.0:
                continue  # Whale is short, disagrees with long
        elif mode == 'strict':
            if sig['direction'] == 'SHORT' and ls <= ls_short:
                continue
            if sig['direction'] == 'LONG' and ls >= ls_long:
                continue

        sig_copy = dict(sig)
        sig_copy['ls_ratio'] = ls
        sig_copy['funding_rate'] = deriv['funding_rate']
        filtered.append(sig_copy)

    return filtered

# ============================================================
# BACKTEST
# ============================================================

def backtest_signals(bars, signals, tp_mult=2.0, sl_mult=1.0, hold_bars=48):
    trades = []
    for sig in signals:
        i = sig['idx']
        entry = sig['entry']
        atr = sig['atr']
        direction = sig['direction']

        if direction == 'LONG':
            tp = entry + tp_mult * atr
            sl = entry - sl_mult * atr
        else:
            tp = entry - tp_mult * atr
            sl = entry + sl_mult * atr

        outcome = None
        exit_price = None
        exit_idx = None
        for j in range(i + 1, min(i + hold_bars + 1, len(bars))):
            if direction == 'LONG':
                if bars[j]['high'] >= tp:
                    outcome = 'WIN'; exit_price = tp; exit_idx = j; break
                if bars[j]['low'] <= sl:
                    outcome = 'LOSS'; exit_price = sl; exit_idx = j; break
            else:
                if bars[j]['low'] <= tp:
                    outcome = 'WIN'; exit_price = tp; exit_idx = j; break
                if bars[j]['high'] >= sl:
                    outcome = 'LOSS'; exit_price = sl; exit_idx = j; break

        if outcome is None:
            exit_idx = min(i + hold_bars, len(bars) - 1)
            exit_price = bars[exit_idx]['close']
            if direction == 'LONG':
                outcome = 'WIN' if exit_price > entry else 'LOSS'
            else:
                outcome = 'WIN' if exit_price < entry else 'LOSS'

        pnl_pct = ((exit_price - entry) / entry * 100) if direction == 'LONG' else ((entry - exit_price) / entry * 100)

        trades.append({
            'entry_dt': sig['dt'], 'direction': direction,
            'entry': entry, 'exit_price': exit_price, 'tp': tp, 'sl': sl,
            'atr': atr, 'pnl_pct': pnl_pct, 'outcome': outcome,
            'ls_ratio': sig.get('ls_ratio', 0), 'reason': sig.get('reason', ''),
        })

    return trades

def compute_metrics(trades):
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'avg_win': 0, 'avg_loss': 0, 'max_consec_loss': 0}
    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    total_win = sum(t['pnl_pct'] for t in wins)
    total_loss = sum(abs(t['pnl_pct']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    wr = len(wins) / len(trades) * 100
    total_pnl = sum(t['pnl_pct'] for t in trades)
    max_consec = 0; cur = 0
    for t in trades:
        if t['outcome'] == 'LOSS': cur += 1; max_consec = max(max_consec, cur)
        else: cur = 0
    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(wr, 1), 'pf': round(pf, 2), 'pnl': round(total_pnl, 2),
        'avg_win': round(total_win / len(wins), 2) if wins else 0,
        'avg_loss': round(total_loss / len(losses), 2) if losses else 0,
        'max_consec_loss': max_consec,
    }

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("Loading data...")
    start = datetime(2026, 5, 13)  # Derivatives start here
    end = datetime(2026, 7, 7)
    bars = load_eth_data(start, end)
    print(f"  {len(bars)} bars ({bars[0]['dt']} → {bars[-1]['dt']})")

    atrs = compute_atr(bars)
    closes = [b['close'] for b in bars]
    ema200 = compute_ema(closes, 200)
    bb_upper, bb_middle, bb_lower = compute_bb(closes, 20, 2.0)

    deriv_map = load_derivatives()
    print(f"  {len(deriv_map)} derivative snapshots")

    # Define strategies to test
    strategies = {
        'failed_breakout': lambda: detect_failed_breakout(bars, atrs, bb_upper, bb_lower, ema200),
        'structural_break': lambda: detect_structural_break(bars, atrs, lookback=20),
        'squeeze_breakout': lambda: detect_squeeze_breakout(bars, atrs, bb_upper, bb_lower),
        'judas_sweep': lambda: detect_judas_sweep(bars, atrs, lookback=20),
        'positioning_fade': lambda: detect_positioning_fade(bars, atrs, deriv_map),
    }

    # TP/SL configs to test
    tp_sl_configs = [
        {'tp': 1.0, 'sl': 1.0, 'hold': 24, 'label': 'TP1.0/SL1.0/H24'},
        {'tp': 1.5, 'sl': 1.0, 'hold': 24, 'label': 'TP1.5/SL1.0/H24'},
        {'tp': 2.0, 'sl': 1.0, 'hold': 24, 'label': 'TP2.0/SL1.0/H24'},
        {'tp': 1.5, 'sl': 1.5, 'hold': 24, 'label': 'TP1.5/SL1.5/H24'},
        {'tp': 2.0, 'sl': 1.0, 'hold': 48, 'label': 'TP2.0/SL1.0/H48'},
        {'tp': 2.0, 'sl': 1.5, 'hold': 48, 'label': 'TP2.0/SL1.5/H48'},
        {'tp': 3.0, 'sl': 0.6, 'hold': 48, 'label': 'TP3.0/SL0.6/H48'},
        {'tp': 3.5, 'sl': 0.4, 'hold': 48, 'label': 'TP3.5/SL0.4/H48'},
    ]

    all_results = []

    for strat_name, strat_fn in strategies.items():
        print(f"\n{'='*70}")
        print(f"STRATEGY: {strat_name}")
        print(f"{'='*70}")

        raw_signals = strat_fn()
        print(f"  Raw signals: {len(raw_signals)}")

        if not raw_signals:
            print("  No signals — skipping")
            continue

        # Test with and without whale filter
        for filter_mode in ['none', 'wgated', 'strict']:
            if filter_mode == 'none':
                signals = raw_signals
                filter_label = 'no filter'
            else:
                signals = apply_whale_filter(raw_signals, deriv_map, mode=filter_mode)
                filter_label = filter_mode

            print(f"\n  Filter: {filter_label} → {len(signals)} signals")

            if len(signals) < 3:
                print("    Too few signals — skipping")
                continue

            for cfg in tp_sl_configs:
                trades = backtest_signals(bars, signals, tp_mult=cfg['tp'], sl_mult=cfg['sl'], hold_bars=cfg['hold'])
                m = compute_metrics(trades)
                hit = "***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
                if m['trades'] >= 3:
                    line = f"    {cfg['label']:>20s} | trades={m['trades']:3d} | WR={m['wr']:5.1f}% | PF={m['pf']:6.2f} | PnL={m['pnl']:+7.2f}% | max_consec_L={m['max_consec_loss']}{hit}"
                    print(line)

                    all_results.append({
                        'strategy': strat_name,
                        'filter': filter_label,
                        'config': cfg['label'],
                        'tp': cfg['tp'], 'sl': cfg['sl'], 'hold': cfg['hold'],
                        **m,
                        'hit_target': bool(m['pf'] >= 2.0 and m['wr'] >= 75),
                    })

    # Save results
    report_path = os.path.join(REPORT_DIR, 'event_strategies_whale_validation.json')
    with open(report_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY — Configs with PF >= 2.0")
    print(f"{'='*70}")
    hits = [r for r in all_results if r['pf'] >= 2.0]
    hits.sort(key=lambda x: (-x['wr'], -x['pf']))
    for r in hits[:30]:
        target = " *** TARGET ***" if r['hit_target'] else ""
        print(f"  {r['strategy']:>20s} | {r['filter']:>8s} | {r['config']:>20s} | trades={r['trades']:3d} | WR={r['wr']:5.1f}% | PF={r['pf']:6.2f} | PnL={r['pnl']:+7.2f}%{target}")

    target_hits = [r for r in all_results if r['hit_target']]
    if target_hits:
        print(f"\n🎯 {len(target_hits)} configs hit PF>=2.0 AND WR>=75%!")
    else:
        print(f"\n❌ No configs hit PF>=2.0 AND WR>=75%")

    print(f"\n✅ Report saved to {report_path}")
