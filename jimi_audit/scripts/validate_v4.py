#!/usr/bin/env python3
"""
Liquidity Grab + Whale Watch — Threshold Validation V4
Works from the 17 ACTUAL scanner trades (whale_pair_analysis.json).
Post-hoc sweep magnitude and FR filters on existing signals.

Priority 1: Sweep magnitude grid (0.05-0.50 ATR)
Priority 2: FR threshold grid
Priority 3: Hold-out validation
"""
import csv, os, sys, json
from datetime import datetime, timedelta
import numpy as np

BASE = "/root/.openclaw/workspace/jimi_audit"
ETH_FILE = os.path.join(BASE, "eth_15m_merged.csv")
DERIV_FILE = os.path.join(BASE, "data", "derivatives_history", "derivatives_collected.csv")
TRADES_FILE = os.path.join(BASE, "reports", "whale_pair_analysis.json")
REPORT_DIR = os.path.join(BASE, "reports")

# ============================================================
# LOAD THE 17 ACTUAL TRADES
# ============================================================

def load_original_trades():
    """Load the 17 liquidity_grab + whale trades from the JSON."""
    with open(TRADES_FILE) as f:
        data = json.load(f)
    
    lg = data['results']['liquidity_grab']
    config = lg['config']
    trades = lg['trades']
    
    print(f"  Config: ls_hi={config['ls_hi']}, ls_lo={config['ls_lo']}, "
          f"cd={config['cd']}, tp={config['tp']}x ATR, sl={config['slm']}x ATR, hold={config['hb']} bars")
    print(f"  Stats: {config}")
    print(f"  Total trades: {len(trades)}")
    print(f"  WR: {lg['stats']['wr']:.1f}%, PF: {lg['stats']['pf']:.2f}, PnL: {lg['stats']['pnl']:+.2f}%")
    
    return trades, config

# ============================================================
# LOAD ETH DATA
# ============================================================

def load_eth_data():
    """Load full ETH 15m data."""
    bars = {}
    with open(ETH_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt_str = row['Open time']
            bars[dt_str] = {
                'dt': dt_str,
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': float(row['Volume']),
            }
    return bars

# ============================================================
# COMPUTE SWEEP MAGNITUDE FOR EACH TRADE
# ============================================================

def compute_sweep_magnitude(trades, eth_bars, lookback=20):
    """
    For each trade, find the nearest swing high/low and compute
    how far price swept past it at entry time.
    
    For SHORT trades: sweep = how far high went above nearest swing high
    For LONG trades: sweep = how far low went below nearest swing low
    """
    results = []
    sorted_times = sorted(eth_bars.keys())
    
    for trade in trades:
        entry_time = trade['time']
        direction = trade['dir']
        entry_price = trade['entry']
        
        # Find this bar in ETH data
        if entry_time not in eth_bars:
            print(f"  WARNING: {entry_time} not in ETH data, skipping")
            continue
        
        # Get lookback bars before entry
        entry_idx = sorted_times.index(entry_time)
        if entry_idx < lookback:
            print(f"  WARNING: not enough lookback for {entry_time}")
            continue
        
        window_times = sorted_times[entry_idx - lookback:entry_idx]
        window_bars = [eth_bars[t] for t in window_times]
        
        swing_high = max(b['high'] for b in window_bars)
        swing_low = min(b['low'] for b in window_bars)
        
        # Compute ATR from lookback window
        trs = []
        for i in range(1, len(window_bars)):
            h = window_bars[i]['high']
            l = window_bars[i]['low']
            pc = window_bars[i-1]['close']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = np.mean(trs) if trs else 0
        
        # Compute sweep magnitude
        entry_bar = eth_bars[entry_time]
        if direction == 'SHORT':
            # SHORT: swept above swing high
            sweep_raw = entry_bar['high'] - swing_high
            sweep_atr = sweep_raw / atr if atr > 0 else 0
        else:
            # LONG: swept below swing low
            sweep_raw = swing_low - entry_bar['low']
            sweep_atr = sweep_raw / atr if atr > 0 else 0
        
        results.append({
            **trade,
            'swing_high': swing_high,
            'swing_low': swing_low,
            'atr': atr,
            'sweep_raw': sweep_raw,
            'sweep_atr': sweep_atr,
        })
    
    return results

# ============================================================
# LOAD DERIVATIVES AND COMPUTE FR FOR EACH TRADE
# ============================================================

def load_derivatives():
    """Load derivatives data."""
    deriv = {}
    with open(DERIV_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row['timestamp']
            dt = datetime.fromisoformat(ts)
            dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
            deriv[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
                'ls_ratio': float(row['ls_ratio']),
                'funding_rate': float(row['funding_rate']),
            }
    return deriv

def find_nearest_deriv(deriv_map, time_str, max_hours=2):
    """Find nearest derivative snapshot."""
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    for offset_min in range(0, max_hours * 60 + 1, 1):
        for check_dt in [dt - timedelta(minutes=offset_min), dt + timedelta(minutes=offset_min)]:
            check_str = check_dt.strftime('%Y-%m-%d %H:%M:%S')
            if check_str in deriv_map:
                return deriv_map[check_str]
    return None

def add_deriv_data(trades_with_sweep, deriv_map):
    """Add FR and LS data to each trade."""
    for t in trades_with_sweep:
        deriv = find_nearest_deriv(deriv_map, t['time'])
        if deriv:
            t['funding_rate'] = deriv['funding_rate']
            t['ls_ratio_deriv'] = deriv['ls_ratio']
        else:
            t['funding_rate'] = None
            t['ls_ratio_deriv'] = None
    return trades_with_sweep

# ============================================================
# FILTER AND EVALUATE
# ============================================================

def evaluate_trades(trades, sweep_min=None, fr_threshold=None, period=None):
    """Filter trades by sweep, FR, and/or period, then compute metrics."""
    filtered = []
    for t in trades:
        # Sweep filter
        if sweep_min is not None and t.get('sweep_atr', 0) < sweep_min:
            continue
        
        # FR filter
        if fr_threshold is not None:
            fr = t.get('funding_rate')
            if fr is None:
                continue
            if t['dir'] == 'SHORT' and fr < fr_threshold:
                continue
            if t['dir'] == 'LONG' and fr > -fr_threshold:
                continue
        
        # Period filter
        if period is not None:
            trade_dt = datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S')
            if period == 'P1' and trade_dt >= datetime(2026, 6, 15):
                continue
            if period == 'P2' and trade_dt < datetime(2026, 6, 15):
                continue
        
        filtered.append(t)
    
    return compute_metrics(filtered)

def compute_metrics(trades):
    """Compute WR, PF, PnL from trade list."""
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0}
    
    wins = [t for t in trades if t['outcome'] == 'W']
    losses = [t for t in trades if t['outcome'] == 'L']
    # T = timeout (counted based on pnl sign)
    timeouts = [t for t in trades if t['outcome'] == 'T']
    for t in timeouts:
        if t['pnl'] > 0:
            wins.append(t)
        else:
            losses.append(t)
    
    total_win = sum(t['pnl'] for t in wins)
    total_loss = sum(abs(t['pnl']) for t in losses)
    
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    wr = len(wins) / len(trades) * 100
    total_pnl = sum(t['pnl'] for t in trades)
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(wr, 1),
        'pf': round(pf, 2),
        'pnl': round(total_pnl, 4),
    }

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("LIQUIDITY GRAB + WHALE WATCH — THRESHOLD VALIDATION V4")
    print("Working from the 17 ACTUAL scanner trades")
    print("=" * 70)
    
    print("\n[1] Loading original trades...")
    trades_raw, config = load_original_trades()
    
    print("\n[2] Loading ETH data...")
    eth_bars = load_eth_data()
    print(f"  {len(eth_bars)} bars loaded")
    
    print("\n[3] Computing sweep magnitude for each trade...")
    trades_with_sweep = compute_sweep_magnitude(trades_raw, eth_bars, lookback=20)
    
    print("\n[4] Loading derivatives...")
    deriv_map = load_derivatives()
    print(f"  {len(deriv_map)} snapshots")
    
    print("\n[5] Adding FR data to trades...")
    trades_with_sweep = add_deriv_data(trades_with_sweep, deriv_map)
    
    # Print each trade with sweep magnitude
    print("\n" + "=" * 70)
    print("TRADE DETAILS WITH SWEEP MAGNITUDE")
    print("=" * 70)
    print(f"  {'Time':<20s} {'Dir':>5s} {'Outcome':>3s} {'PnL':>7s} {'LS':>6s} {'FR':>10s} {'SweepATR':>9s} {'SwingH':>9s} {'SwingL':>9s}")
    print("  " + "-" * 90)
    for t in trades_with_sweep:
        fr_str = f"{t['funding_rate']:.5f}" if t.get('funding_rate') is not None else "N/A"
        print(f"  {t['time']:<20s} {t['dir']:>5s} {t['outcome']:>3s} {t['pnl']:>+7.4f} {t.get('ls', t.get('ls_ratio_deriv', 0)):>6.3f} {fr_str:>10s} {t['sweep_atr']:>9.4f} {t['swing_high']:>9.2f} {t['swing_low']:>9.2f}")
    
    # ============================================================
    # PRIORITY 1: SWEEP MAGNITUDE GRID
    # ============================================================
    print("\n" + "=" * 70)
    print("PRIORITY 1: SWEEP MAGNITUDE GRID")
    print("Filter the 17 trades by minimum sweep magnitude")
    print("=" * 70)
    
    sweep_thresholds = [0.0, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    print(f"\n  {'Sweep':>6s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s} | {'Note'}")
    print("  " + "-" * 70)
    
    for thr in sweep_thresholds:
        m = evaluate_trades(trades_with_sweep, sweep_min=thr)
        note = ""
        if thr == 0.0:
            note = "← baseline (all 17)"
        elif m['trades'] == 0:
            note = "← no trades"
        elif m['pf'] >= 2.0 and m['wr'] >= 75:
            note = " *** TARGET ***"
        print(f"  {thr:>6.2f} | {m['trades']:>6d} | {m['wins']:>3d} {m['losses']:>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}% | {note}")
    
    # ============================================================
    # PRIORITY 2: FR THRESHOLD GRID
    # ============================================================
    print("\n" + "=" * 70)
    print("PRIORITY 2: FUNDING RATE THRESHOLD GRID")
    print("Filter the 17 trades by minimum |FR| at entry")
    print("=" * 70)
    
    fr_thresholds = [0.0, 0.00001, 0.00003, 0.00005, 0.00008, 0.00010, 0.00015, 0.00020]
    print(f"\n  {'FR >':>8s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s} | {'Note'}")
    print("  " + "-" * 70)
    
    for fr_thr in fr_thresholds:
        m = evaluate_trades(trades_with_sweep, fr_threshold=fr_thr)
        note = ""
        if fr_thr == 0.0:
            note = "← baseline (all 17)"
        elif m['trades'] == 0:
            note = "← no trades"
        elif m['pf'] >= 2.0 and m['wr'] >= 75:
            note = " *** TARGET ***"
        print(f"  {fr_thr:>8.5f} | {m['trades']:>6d} | {m['wins']:>3d} {m['losses']:>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}% | {note}")
    
    # ============================================================
    # PRIORITY 3: HOLD-OUT VALIDATION
    # ============================================================
    print("\n" + "=" * 70)
    print("PRIORITY 3: HOLD-OUT VALIDATION")
    print("P1: before Jun 15 | P2: Jun 15+")
    print("=" * 70)
    
    # Show period distribution
    p1_trades = [t for t in trades_with_sweep if datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S') < datetime(2026, 6, 15)]
    p2_trades = [t for t in trades_with_sweep if datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S') >= datetime(2026, 6, 15)]
    
    print(f"\n  P1 trades: {len(p1_trades)} ({p1_trades[0]['time'] if p1_trades else 'N/A'} → {p1_trades[-1]['time'] if p1_trades else 'N/A'})")
    print(f"  P2 trades: {len(p2_trades)} ({p2_trades[0]['time'] if p2_trades else 'N/A'} → {p2_trades[-1]['time'] if p2_trades else 'N/A'})")
    
    configs = [
        {'sweep': None, 'fr': None, 'label': 'baseline'},
        {'sweep': 0.05, 'fr': None, 'label': 'sweep>=0.05'},
        {'sweep': 0.10, 'fr': None, 'label': 'sweep>=0.10'},
        {'sweep': 0.15, 'fr': None, 'label': 'sweep>=0.15'},
        {'sweep': 0.20, 'fr': None, 'label': 'sweep>=0.20'},
        {'sweep': None, 'fr': 0.00003, 'label': 'FR>0.00003'},
        {'sweep': None, 'fr': 0.00005, 'label': 'FR>0.00005'},
        {'sweep': 0.10, 'fr': 0.00003, 'label': 'sweep>=0.10+FR>3e-5'},
    ]
    
    print(f"\n  {'Config':<25s} | {'P1':>3s} {'P1_WR':>6s} {'P1_PF':>6s} | {'P2':>3s} {'P2_WR':>6s} {'P2_PF':>6s} | {'Delta':>6s}")
    print("  " + "-" * 80)
    
    for cfg in configs:
        m1 = evaluate_trades(trades_with_sweep, sweep_min=cfg['sweep'], fr_threshold=cfg['fr'], period='P1')
        m2 = evaluate_trades(trades_with_sweep, sweep_min=cfg['sweep'], fr_threshold=cfg['fr'], period='P2')
        
        if m1['pf'] > 0 and m2['pf'] > 0:
            delta = f"{m2['pf'] - m1['pf']:+.2f}"
        else:
            delta = "N/A"
        
        print(f"  {cfg['label']:<25s} | {m1['trades']:>3d} {m1['wr']:>5.1f}% {m1['pf']:>6.2f} | {m2['trades']:>3d} {m2['wr']:>5.1f}% {m2['pf']:>6.2f} | {delta:>6s}")
    
    # ============================================================
    # COMBINED GRID: SWEEP x FR
    # ============================================================
    print("\n" + "=" * 70)
    print("COMBINED GRID: SWEEP x FR")
    print("=" * 70)
    
    sweep_vals = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25]
    fr_vals = [0.0, 0.00003, 0.00005, 0.00008]
    
    print(f"\n  {'Sweep':>6s} / {'FR':>8s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s}")
    print("  " + "-" * 55)
    
    for sw in sweep_vals:
        for fr in fr_vals:
            m = evaluate_trades(trades_with_sweep, sweep_min=sw if sw > 0 else None, fr_threshold=fr if fr > 0 else None)
            if m['trades'] > 0:
                hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
                print(f"  {sw:>6.2f} / {fr:>8.5f} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}%{hit}")
    
    print("\n✅ Done")
