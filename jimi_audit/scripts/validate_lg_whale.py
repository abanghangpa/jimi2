#!/usr/bin/env python3
"""
Liquidity Grab + Whale Watch — Threshold Validation
Priority 1: Sweep magnitude grid (0.05–0.25 ATR)
Priority 2: Funding rate threshold grid
Priority 3: Hold-out validation (fit Period 1, validate Period 2)
"""
import csv, os, sys, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import numpy as np

BASE = "/root/.openclaw/workspace/jimi_audit"
ETH_FILE = os.path.join(BASE, "eth_15m_merged.csv")
DERIV_FILE = os.path.join(BASE, "data", "derivatives_history", "derivatives_collected.csv")
REPORT_DIR = os.path.join(BASE, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)

# ============================================================
# DATA LOADING
# ============================================================

def load_eth_data(start_date=None, end_date=None):
    """Load ETH 15m OHLCV data, optionally filter by date range."""
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
                'dt': dt,
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': float(row['Volume']),
            })
    return bars

def load_derivatives():
    """Load derivatives data, return dict keyed by rounded 15m timestamp."""
    deriv = {}
    with open(DERIV_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row['timestamp']
            dt = datetime.fromisoformat(ts)
            # Round to 15m floor
            dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
            deriv[dt_floor] = {
                'ls_ratio': float(row['ls_ratio']),
                'funding_rate': float(row['funding_rate']),
                'oi': float(row['oi']),
            }
    return deriv

def get_nearest_deriv(deriv_map, dt, max_hours=2):
    """Find nearest derivative snapshot within max_hours."""
    for offset_min in range(0, max_hours * 60 + 1, 1):
        check = dt - timedelta(minutes=offset_min)
        if check in deriv_map:
            return deriv_map[check]
        check2 = dt + timedelta(minutes=offset_min)
        if check2 in deriv_map:
            return deriv_map[check2]
    return None

# ============================================================
# ATR COMPUTATION
# ============================================================

def compute_atr(bars, period=14):
    """Compute ATR for each bar."""
    trs = []
    atrs = [0.0] * len(bars)
    for i in range(1, len(bars)):
        h = bars[i]['high']
        l = bars[i]['low']
        pc = bars[i-1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # Simple moving average for ATR
    for i in range(period, len(bars)):
        atrs[i] = np.mean(trs[i-period:i])
    return atrs

# ============================================================
# LIQUIDITY GRAB DETECTION (standalone, no scanner dependency)
# ============================================================

def find_swing_highs_lows(bars, lookback=20):
    """Find swing high/low for each bar using lookback window."""
    swing_highs = [None] * len(bars)
    swing_lows = [None] * len(bars)
    for i in range(lookback, len(bars)):
        window = bars[i-lookback:i]
        swing_highs[i] = max(b['high'] for b in window)
        swing_lows[i] = min(b['low'] for b in window)
    return swing_highs, swing_lows

def detect_liquidity_grabs(bars, atrs, swing_highs, swing_lows, sweep_atr_mult=0.1, ema_period=200):
    """
    Detect liquidity grab events:
    - Price sweeps past swing high/low by sweep_atr_mult * ATR
    - Closes back inside (bearish close for high sweep, bullish for low sweep)
    - EMA200 trend filter
    """
    # Compute EMA200
    closes = [b['close'] for b in bars]
    ema200 = [0.0] * len(bars)
    if len(closes) > ema_period:
        k = 2.0 / (ema_period + 1)
        ema200[ema_period] = np.mean(closes[:ema_period])
        for i in range(ema_period + 1, len(closes)):
            ema200[i] = closes[i] * k + ema200[i-1] * (1 - k)

    signals = []
    for i in range(max(ema_period, 20), len(bars)):
        if atrs[i] <= 0:
            continue
        b = bars[i]
        sh = swing_highs[i]
        sl = swing_lows[i]
        if sh is None or sl is None:
            continue

        sweep_threshold = sweep_atr_mult * atrs[i]

        # Bearish liquidity grab: swept above swing high, closed below
        if b['high'] > sh + sweep_threshold and b['close'] < sh:
            # EMA200 filter: only SHORT if above EMA (overextended)
            if ema200[i] > 0 and b['close'] > ema200[i]:
                signals.append({
                    'idx': i,
                    'dt': b['dt'],
                    'direction': 'SHORT',
                    'entry': b['close'],
                    'sweep_high': sh,
                    'sweep_depth': b['high'] - sh,
                    'atr': atrs[i],
                    'sweep_depth_atr': (b['high'] - sh) / atrs[i],
                })

        # Bullish liquidity grab: swept below swing low, closed above
        if b['low'] < sl - sweep_threshold and b['close'] > sl:
            if ema200[i] > 0 and b['close'] < ema200[i]:
                signals.append({
                    'idx': i,
                    'dt': b['dt'],
                    'direction': 'LONG',
                    'entry': b['close'],
                    'sweep_low': sl,
                    'sweep_depth': sl - b['low'],
                    'atr': atrs[i],
                    'sweep_depth_atr': (sl - b['low']) / atrs[i],
                })

    return signals

# ============================================================
# WHALE WATCH CONDITIONING
# ============================================================

def apply_whale_filter(signals, deriv_map, ls_long=1.7, ls_short=2.1, fr_threshold=None, mode='wgated'):
    """
    Apply whale conditioning to signals.
    mode='wgated': event triggers, whale filters (can't disagree)
    mode='both': both must agree
    """
    filtered = []
    for sig in signals:
        deriv = get_nearest_deriv(deriv_map, sig['dt'])
        if deriv is None:
            continue

        ls = deriv['ls_ratio']
        fr = deriv['funding_rate']

        whale_agrees = False
        if sig['direction'] == 'SHORT' and ls > ls_short:
            whale_agrees = True
        elif sig['direction'] == 'LONG' and ls < ls_long:
            whale_agrees = True

        if mode == 'wgated':
            # In wgated mode: signal fires, whale must not disagree
            # For SHORT: whale must be bearish (ls > 1.0, not opposing)
            # For LONG: whale must be bullish (ls < 1.0, not opposing)
            if sig['direction'] == 'SHORT' and ls > 1.0:
                whale_agrees = True
            elif sig['direction'] == 'LONG' and ls < 1.0:
                whale_agrees = True

        if not whale_agrees:
            continue

        # Funding rate filter
        if fr_threshold is not None:
            if sig['direction'] == 'SHORT' and fr < fr_threshold:
                continue
            if sig['direction'] == 'LONG' and fr > -fr_threshold:
                continue

        sig_copy = dict(sig)
        sig_copy['ls_ratio'] = ls
        sig_copy['funding_rate'] = fr
        filtered.append(sig_copy)

    return filtered

# ============================================================
# BACKTEST ENGINE
# ============================================================

def backtest_signals(bars, signals, tp_mult=3.0, sl_mult=0.6, hold_bars=48):
    """Backtest signals with ATR-based TP/SL and max hold."""
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

        # Simulate forward
        outcome = None
        exit_price = None
        exit_idx = None
        for j in range(i + 1, min(i + hold_bars + 1, len(bars))):
            if direction == 'LONG':
                if bars[j]['high'] >= tp:
                    outcome = 'WIN'
                    exit_price = tp
                    exit_idx = j
                    break
                if bars[j]['low'] <= sl:
                    outcome = 'LOSS'
                    exit_price = sl
                    exit_idx = j
                    break
            else:
                if bars[j]['low'] <= tp:
                    outcome = 'WIN'
                    exit_price = tp
                    exit_idx = j
                    break
                if bars[j]['high'] >= sl:
                    outcome = 'LOSS'
                    exit_price = sl
                    exit_idx = j
                    break

        # If neither TP nor SL hit, exit at close of hold period
        if outcome is None:
            exit_idx = min(i + hold_bars, len(bars) - 1)
            exit_price = bars[exit_idx]['close']
            if direction == 'LONG':
                outcome = 'WIN' if exit_price > entry else 'LOSS'
            else:
                outcome = 'WIN' if exit_price < entry else 'LOSS'

        pnl_pct = ((exit_price - entry) / entry * 100) if direction == 'LONG' else ((entry - exit_price) / entry * 100)

        trades.append({
            'entry_dt': sig['dt'],
            'exit_dt': bars[exit_idx]['dt'],
            'direction': direction,
            'entry': entry,
            'exit_price': exit_price,
            'tp': tp,
            'sl': sl,
            'atr': atr,
            'pnl_pct': pnl_pct,
            'outcome': outcome,
            'ls_ratio': sig.get('ls_ratio', 0),
            'funding_rate': sig.get('funding_rate', 0),
            'sweep_depth_atr': sig.get('sweep_depth_atr', 0),
        })

    return trades

def compute_metrics(trades):
    """Compute WR, PF, PnL, etc."""
    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'avg_win': 0, 'avg_loss': 0, 'max_consec_loss': 0}

    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']

    total_win_pnl = sum(t['pnl_pct'] for t in wins)
    total_loss_pnl = sum(abs(t['pnl_pct']) for t in losses)

    pf = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else float('inf')
    wr = len(wins) / len(trades) * 100 if trades else 0
    total_pnl = sum(t['pnl_pct'] for t in trades)

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for t in trades:
        if t['outcome'] == 'LOSS':
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(wr, 1),
        'pf': round(pf, 2),
        'pnl': round(total_pnl, 2),
        'avg_win': round(total_win_pnl / len(wins), 2) if wins else 0,
        'avg_loss': round(total_loss_pnl / len(losses), 2) if losses else 0,
        'max_consec_loss': max_consec,
    }

# ============================================================
# MAIN VALIDATION
# ============================================================

def run_sweep_magnitude_grid(bars, atrs, swing_highs, swing_lows, deriv_map):
    """Priority 1: Test sweep magnitude thresholds."""
    print("\n" + "="*70)
    print("PRIORITY 1: SWEEP MAGNITUDE GRID")
    print("="*70)

    thresholds = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    results = []

    for thr in thresholds:
        signals = detect_liquidity_grabs(bars, atrs, swing_highs, swing_lows, sweep_atr_mult=thr)
        filtered = apply_whale_filter(signals, deriv_map, ls_long=1.7, ls_short=2.1, fr_threshold=None, mode='wgated')
        trades = backtest_signals(bars, filtered, tp_mult=3.0, sl_mult=0.6, hold_bars=48)
        m = compute_metrics(trades)
        m['sweep_atr'] = thr
        m['raw_signals'] = len(signals)
        m['filtered_signals'] = len(filtered)
        results.append(m)
        print(f"  sweep={thr:.2f} ATR | raw={len(signals):3d} | filtered={len(filtered):3d} | trades={m['trades']:3d} | WR={m['wr']:5.1f}% | PF={m['pf']:6.2f} | PnL={m['pnl']:+7.2f}%")

    return results

def run_fr_threshold_grid(bars, atrs, swing_highs, swing_lows, deriv_map):
    """Priority 2: Test funding rate thresholds."""
    print("\n" + "="*70)
    print("PRIORITY 2: FUNDING RATE THRESHOLD GRID")
    print("="*70)

    fr_thresholds = [0.00003, 0.00005, 0.00008, 0.00010, 0.00015, 0.00020, 0.00030]
    results = []

    # Use sweep=0.10 as baseline
    signals = detect_liquidity_grabs(bars, atrs, swing_highs, swing_lows, sweep_atr_mult=0.10)
    print(f"  Base signals (sweep=0.10 ATR): {len(signals)}")

    for fr_thr in fr_thresholds:
        filtered = apply_whale_filter(signals, deriv_map, ls_long=1.7, ls_short=2.1, fr_threshold=fr_thr, mode='wgated')
        trades = backtest_signals(bars, filtered, tp_mult=3.0, sl_mult=0.6, hold_bars=48)
        m = compute_metrics(trades)
        m['fr_threshold'] = fr_thr
        m['filtered_signals'] = len(filtered)
        results.append(m)
        print(f"  FR>{fr_thr:.5f} | filtered={len(filtered):3d} | trades={m['trades']:3d} | WR={m['wr']:5.1f}% | PF={m['pf']:6.2f} | PnL={m['pnl']:+7.2f}%")

    return results

def run_fr_no_filter(bars, atrs, swing_highs, swing_lows, deriv_map):
    """Test FR as primary filter (no ls filter)."""
    print("\n" + "="*70)
    print("PRIORITY 2b: FR AS PRIMARY FILTER (NO LS)")
    print("="*70)

    fr_thresholds = [0.00005, 0.00008, 0.00010, 0.00015, 0.00020]
    signals = detect_liquidity_grabs(bars, atrs, swing_highs, swing_lows, sweep_atr_mult=0.10)

    for fr_thr in fr_thresholds:
        # Use FR only, no ls filter
        filtered = []
        for sig in signals:
            deriv = get_nearest_deriv(deriv_map, sig['dt'])
            if deriv is None:
                continue
            fr = deriv['funding_rate']
            if sig['direction'] == 'SHORT' and fr < fr_thr:
                continue
            if sig['direction'] == 'LONG' and fr > -fr_thr:
                continue
            sig_copy = dict(sig)
            sig_copy['ls_ratio'] = deriv['ls_ratio']
            sig_copy['funding_rate'] = fr
            filtered.append(sig_copy)

        trades = backtest_signals(bars, filtered, tp_mult=3.0, sl_mult=0.6, hold_bars=48)
        m = compute_metrics(trades)
        print(f"  FR>{fr_thr:.5f} (no ls) | filtered={len(filtered):3d} | trades={m['trades']:3d} | WR={m['wr']:5.1f}% | PF={m['pf']:6.2f} | PnL={m['pnl']:+7.2f}%")

def run_holdout_validation(bars_all, atrs_all, swing_highs_all, swing_lows_all, deriv_map):
    """Priority 3: Hold-out validation."""
    print("\n" + "="*70)
    print("PRIORITY 3: HOLD-OUT VALIDATION")
    print("="*70)

    # Period 1: May 13 - Jun 15 (fit)
    # Period 2: Jun 16 - Jul 6 (validate)
    cutoff = datetime(2026, 6, 15)

    # Find cutoff index
    cutoff_idx = None
    for i, b in enumerate(bars_all):
        if b['dt'] >= cutoff:
            cutoff_idx = i
            break

    if cutoff_idx is None:
        print("  ERROR: cutoff date not found in data")
        return

    print(f"  Period 1 (fit):     {bars_all[0]['dt'].strftime('%Y-%m-%d')} → {bars_all[cutoff_idx-1]['dt'].strftime('%Y-%m-%d')} ({cutoff_idx} bars)")
    print(f"  Period 2 (validate): {bars_all[cutoff_idx]['dt'].strftime('%Y-%m-%d')} → {bars_all[-1]['dt'].strftime('%Y-%m-%d')} ({len(bars_all)-cutoff_idx} bars)")

    configs = [
        {'sweep': 0.05, 'fr': None, 'label': 'sweep=0.05, no FR'},
        {'sweep': 0.10, 'fr': None, 'label': 'sweep=0.10, no FR'},
        {'sweep': 0.15, 'fr': None, 'label': 'sweep=0.15, no FR'},
        {'sweep': 0.10, 'fr': 0.00005, 'label': 'sweep=0.10, FR>0.00005'},
        {'sweep': 0.10, 'fr': 0.00008, 'label': 'sweep=0.10, FR>0.00008'},
        {'sweep': 0.10, 'fr': 0.00010, 'label': 'sweep=0.10, FR>0.00010'},
    ]

    print(f"\n  {'Config':<30s} | {'P1 Trades':>9s} | {'P1 WR':>6s} | {'P1 PF':>6s} | {'P2 Trades':>9s} | {'P2 WR':>6s} | {'P2 PF':>6s} | {'Delta':>6s}")
    print("  " + "-"*105)

    for cfg in configs:
        # Period 1
        signals_p1 = detect_liquidity_grabs(bars_all[:cutoff_idx], atrs_all[:cutoff_idx],
                                             swing_highs_all[:cutoff_idx], swing_lows_all[:cutoff_idx],
                                             sweep_atr_mult=cfg['sweep'])
        filtered_p1 = apply_whale_filter(signals_p1, deriv_map, fr_threshold=cfg['fr'], mode='wgated')
        trades_p1 = backtest_signals(bars_all[:cutoff_idx], filtered_p1, tp_mult=3.0, sl_mult=0.6, hold_bars=48)
        m1 = compute_metrics(trades_p1)

        # Period 2
        signals_p2 = detect_liquidity_grabs(bars_all[cutoff_idx:], atrs_all[cutoff_idx:],
                                             swing_highs_all[cutoff_idx:], swing_lows_all[cutoff_idx:],
                                             sweep_atr_mult=cfg['sweep'])
        # Re-index signals to full bar array
        for s in signals_p2:
            s['idx'] = s['idx'] + cutoff_idx
        filtered_p2 = apply_whale_filter(signals_p2, deriv_map, fr_threshold=cfg['fr'], mode='wgated')
        trades_p2 = backtest_signals(bars_all, filtered_p2, tp_mult=3.0, sl_mult=0.6, hold_bars=48)
        m2 = compute_metrics(trades_p2)

        pf_delta = round(m2['pf'] - m1['pf'], 2) if m1['pf'] > 0 and m2['pf'] > 0 else 'N/A'
        print(f"  {cfg['label']:<30s} | {m1['trades']:>9d} | {m1['wr']:>5.1f}% | {m1['pf']:>6.2f} | {m2['trades']:>9d} | {m2['wr']:>5.1f}% | {m2['pf']:>6.2f} | {str(pf_delta):>6s}")

# ============================================================
# TP/SL SENSITIVITY
# ============================================================

def run_tp_sl_grid(bars, atrs, swing_highs, swing_lows, deriv_map):
    """Test different TP/SL multiplier combinations."""
    print("\n" + "="*70)
    print("TP/SL MULTIPLIER GRID (sweep=0.10, FR=None)")
    print("="*70)

    signals = detect_liquidity_grabs(bars, atrs, swing_highs, swing_lows, sweep_atr_mult=0.10)
    filtered = apply_whale_filter(signals, deriv_map, ls_long=1.7, ls_short=2.1, fr_threshold=None, mode='wgated')
    print(f"  Signals after whale filter: {len(filtered)}")

    tp_mults = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
    sl_mults = [0.4, 0.5, 0.6, 0.8, 1.0]

    print(f"\n  {'TP':>4s} / {'SL':>4s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s}")
    print("  " + "-"*50)

    for tp in tp_mults:
        for sl in sl_mults:
            trades = backtest_signals(bars, filtered, tp_mult=tp, sl_mult=sl, hold_bars=48)
            m = compute_metrics(trades)
            marker = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
            if m['trades'] >= 5:  # Only show configs with meaningful sample
                print(f"  {tp:>4.1f} / {sl:>4.1f} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.2f}%{marker}")

# ============================================================
# ENTRY
# ============================================================

if __name__ == '__main__':
    print("Loading ETH 15m data...")
    # Full period: Feb 1 - Jul 6 2026
    start = datetime(2026, 2, 1)
    end = datetime(2026, 7, 7)
    bars = load_eth_data(start, end)
    print(f"  Loaded {len(bars)} bars ({bars[0]['dt']} → {bars[-1]['dt']})")

    print("Computing ATR...")
    atrs = compute_atr(bars)

    print("Finding swing highs/lows...")
    swing_highs, swing_lows = find_swing_highs_lows(bars, lookback=20)

    print("Loading derivatives...")
    deriv_map = load_derivatives()
    print(f"  Loaded {len(deriv_map)} derivative snapshots")

    # Run all validations
    sweep_results = run_sweep_magnitude_grid(bars, atrs, swing_highs, swing_lows, deriv_map)
    fr_results = run_fr_threshold_grid(bars, atrs, swing_highs, swing_lows, deriv_map)
    run_fr_no_filter(bars, atrs, swing_highs, swing_lows, deriv_map)
    run_tp_sl_grid(bars, atrs, swing_highs, swing_lows, deriv_map)
    run_holdout_validation(bars, atrs, swing_highs, swing_lows, deriv_map)

    # Save report
    report = {
        'date': '2026-07-06',
        'sweep_magnitude_grid': sweep_results,
        'fr_threshold_grid': fr_results,
    }
    report_path = os.path.join(REPORT_DIR, 'lg_whale_threshold_validation.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n✅ Report saved to {report_path}")
