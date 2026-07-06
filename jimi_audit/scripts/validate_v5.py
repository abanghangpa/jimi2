#!/usr/bin/env python3
"""
Liquidity Grab + Whale Watch — Threshold Validation V5
Proper approach: work from the 17 actual scanner trades.
For each trade, find the actual sweep event (price pierced swing level)
within the lookback window, then measure sweep depth.
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
# LOAD DATA
# ============================================================

def load_eth_bars():
    bars = []
    with open(ETH_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                'dt': row['Open time'],
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
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
            deriv[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
                'ls_ratio': float(row['ls_ratio']),
                'funding_rate': float(row['funding_rate']),
            }
    return deriv

def load_trades():
    with open(TRADES_FILE) as f:
        data = json.load(f)
    return data['results']['liquidity_grab']['trades'], data['results']['liquidity_grab']['config']

# ============================================================
# FIND SWEEP EVENT FOR EACH TRADE
# ============================================================

def find_sweep_for_trade(bars, bar_index, direction, lookback=20):
    """
    For a given trade entry bar, look back to find where price swept
    past a swing level. Returns sweep depth in ATR units.
    
    For SHORT: find where high swept above a recent swing high
    For LONG: find where low swept below a recent swing low
    """
    if bar_index < lookback + 1:
        return None
    
    # Get the swing levels from before the lookback window
    # (the levels that existed when the sweep happened)
    closes = [bars[i]['close'] for i in range(bar_index - lookback, bar_index)]
    highs = [bars[i]['high'] for i in range(bar_index - lookback, bar_index)]
    lows = [bars[i]['low'] for i in range(bar_index - lookback, bar_index)]
    
    # Compute ATR from the lookback window
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = np.mean(trs) if trs else 0
    if atr <= 0:
        return None
    
    # Find swing levels from the 10 bars before the lookback window
    if bar_index < lookback + 10:
        return None
    pre_window_highs = [bars[i]['high'] for i in range(bar_index - lookback - 10, bar_index - lookback)]
    pre_window_lows = [bars[i]['low'] for i in range(bar_index - lookback - 10, bar_index - lookback)]
    
    swing_high = max(pre_window_highs)
    swing_low = min(pre_window_lows)
    
    # Now look through the lookback window for the sweep event
    best_sweep = None
    
    for i in range(bar_index - lookback, bar_index):
        bar = bars[i]
        
        if direction == 'SHORT':
            # Sweep above swing high
            if bar['high'] > swing_high:
                sweep_depth = (bar['high'] - swing_high) / atr
                if best_sweep is None or sweep_depth > best_sweep['depth_atr']:
                    best_sweep = {
                        'bar_idx': i,
                        'dt': bar['dt'],
                        'sweep_price': bar['high'],
                        'level': swing_high,
                        'depth_raw': bar['high'] - swing_high,
                        'depth_atr': sweep_depth,
                        'closed_back': bar['close'] < swing_high,
                    }
        else:
            # Sweep below swing low
            if bar['low'] < swing_low:
                sweep_depth = (swing_low - bar['low']) / atr
                if best_sweep is None or sweep_depth > best_sweep['depth_atr']:
                    best_sweep = {
                        'bar_idx': i,
                        'dt': bar['dt'],
                        'sweep_price': bar['low'],
                        'level': swing_low,
                        'depth_raw': swing_low - bar['low'],
                        'depth_atr': sweep_depth,
                        'closed_back': bar['close'] > swing_low,
                    }
    
    if best_sweep:
        best_sweep['atr'] = atr
    return best_sweep

# ============================================================
# FIND NEAREST DERIV
# ============================================================

def find_nearest_deriv(deriv_map, time_str, max_hours=2):
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    for offset_min in range(0, max_hours * 60 + 1, 1):
        for check_dt in [dt - timedelta(minutes=offset_min), dt + timedelta(minutes=offset_min)]:
            check_str = check_dt.strftime('%Y-%m-%d %H:%M:%S')
            if check_str in deriv_map:
                return deriv_map[check_str]
    return None

# ============================================================
# METRICS
# ============================================================

def compute_metrics(trades):
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_consec_loss': 0}
    wins = [t for t in trades if t['outcome'] in ('W', 'T') and t['pnl'] > 0]
    losses = [t for t in trades if t['outcome'] in ('L', 'T') and t['pnl'] <= 0]
    # Handle T (timeout) based on pnl sign
    for t in trades:
        if t['outcome'] == 'T':
            if t['pnl'] > 0 and t not in wins:
                wins.append(t)
            elif t['pnl'] <= 0 and t not in losses:
                losses.append(t)
    if not wins and not losses:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_consec_loss': 0}
    
    total_win = sum(t['pnl'] for t in wins)
    total_loss = sum(abs(t['pnl']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    wr = len(wins) / len(trades) * 100
    total_pnl = sum(t['pnl'] for t in trades)
    
    # Max consecutive losses
    max_consec = 0; cur = 0
    for t in sorted(trades, key=lambda x: x['time']):
        if t['pnl'] <= 0: cur += 1; max_consec = max(max_consec, cur)
        else: cur = 0
    
    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(wr, 1), 'pf': round(pf, 2), 'pnl': round(total_pnl, 4),
        'max_consec_loss': max_consec,
    }

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("LIQUIDITY GRAB + WHALE WATCH — THRESHOLD VALIDATION V5")
    print("Working from 17 ACTUAL scanner trades")
    print("=" * 70)
    
    print("\n[1] Loading data...")
    bars = load_eth_bars()
    bar_map = {b['dt']: i for i, b in enumerate(bars)}
    print(f"  ETH: {len(bars)} bars")
    
    deriv_map = load_derivatives()
    print(f"  Derivatives: {len(deriv_map)} snapshots")
    
    trades_raw, config = load_trades()
    print(f"  Trades: {len(trades_raw)} | Config: ls_hi={config['ls_hi']}, ls_lo={config['ls_lo']}, tp={config['tp']}x, sl={config['slm']}x, hold={config['hb']}bars")
    
    # ============================================================
    # ENRICH TRADES WITH SWEEP DATA
    # ============================================================
    print("\n[2] Finding sweep events for each trade...")
    
    enriched = []
    for t in trades_raw:
        entry_time = t['time']
        if entry_time not in bar_map:
            print(f"  SKIP: {entry_time} not in ETH data")
            continue
        
        bar_idx = bar_map[entry_time]
        sweep = find_sweep_for_trade(bars, bar_idx, t['dir'], lookback=20)
        deriv = find_nearest_deriv(deriv_map, entry_time)
        
        enriched_t = {
            **t,
            'sweep_depth_atr': sweep['depth_atr'] if sweep else None,
            'sweep_depth_raw': sweep['depth_raw'] if sweep else None,
            'sweep_dt': sweep['dt'] if sweep else None,
            'sweep_level': sweep['level'] if sweep else None,
            'sweep_closed_back': sweep['closed_back'] if sweep else None,
            'funding_rate': deriv['funding_rate'] if deriv else None,
            'ls_ratio_deriv': deriv['ls_ratio'] if deriv else None,
        }
        enriched.append(enriched_t)
    
    # Print enriched data
    print(f"\n  {'Time':<20s} {'Dir':>5s} {'Out':>3s} {'PnL':>8s} {'SweepATR':>9s} {'SweepDt':<20s} {'FR':>10s} {'ClosedBack':>10s}")
    print("  " + "-" * 95)
    for t in enriched:
        sw = f"{t['sweep_depth_atr']:.4f}" if t['sweep_depth_atr'] is not None else "N/A"
        sd = t.get('sweep_dt', 'N/A') or 'N/A'
        fr = f"{t['funding_rate']:.5f}" if t.get('funding_rate') is not None else "N/A"
        cb = str(t.get('sweep_closed_back', ''))
        print(f"  {t['time']:<20s} {t['dir']:>5s} {t['outcome']:>3s} {t['pnl']:>+8.4f} {sw:>9s} {sd:<20s} {fr:>10s} {cb:>10s}")
    
    # ============================================================
    # PRIORITY 1: SWEEP MAGNITUDE GRID
    # ============================================================
    print("\n" + "=" * 70)
    print("PRIORITY 1: SWEEP MAGNITUDE GRID")
    print("Filter trades by minimum sweep depth (ATR)")
    print("=" * 70)
    
    thresholds = [0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.50]
    print(f"\n  {'MinSweep':>8s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s} | Note")
    print("  " + "-" * 70)
    
    for thr in thresholds:
        if thr == 0:
            filtered = enriched
        else:
            filtered = [t for t in enriched if t['sweep_depth_atr'] is not None and t['sweep_depth_atr'] >= thr]
        
        m = compute_metrics(filtered)
        note = ""
        if thr == 0: note = "baseline (all)"
        elif m['trades'] == 0: note = "no trades"
        print(f"  {thr:>8.4f} | {m['trades']:>6d} | {m['wins']:>3d} {m['losses']:>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}% | {note}")
    
    # ============================================================
    # PRIORITY 2: FR THRESHOLD GRID
    # ============================================================
    print("\n" + "=" * 70)
    print("PRIORITY 2: FUNDING RATE THRESHOLD GRID")
    print("Filter trades by minimum |FR| at entry")
    print("=" * 70)
    
    fr_thresholds = [0.0, 0.00001, 0.00002, 0.00003, 0.00005, 0.00008, 0.00010]
    print(f"\n  {'Min|FR|':>8s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s} | Note")
    print("  " + "-" * 70)
    
    for fr_thr in fr_thresholds:
        if fr_thr == 0:
            filtered = enriched
        else:
            filtered = [t for t in enriched if t.get('funding_rate') is not None and abs(t['funding_rate']) >= fr_thr]
        
        m = compute_metrics(filtered)
        note = ""
        if fr_thr == 0: note = "baseline (all)"
        elif m['trades'] == 0: note = "no trades"
        print(f"  {fr_thr:>8.5f} | {m['trades']:>6d} | {m['wins']:>3d} {m['losses']:>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}% | {note}")
    
    # ============================================================
    # PRIORITY 3: HOLD-OUT VALIDATION
    # ============================================================
    print("\n" + "=" * 70)
    print("PRIORITY 3: HOLD-OUT VALIDATION")
    print("=" * 70)
    
    p1 = [t for t in enriched if datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S') < datetime(2026, 6, 15)]
    p2 = [t for t in enriched if datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S') >= datetime(2026, 6, 15)]
    
    m_all = compute_metrics(enriched)
    m_p1 = compute_metrics(p1)
    m_p2 = compute_metrics(p2)
    
    print(f"\n  All: {m_all['trades']} trades, WR={m_all['wr']}%, PF={m_all['pf']}")
    print(f"  P1 (before Jun 15): {m_p1['trades']} trades, WR={m_p1['wr']}%, PF={m_p1['pf']}")
    print(f"  P2 (Jun 15+): {m_p2['trades']} trades, WR={m_p2['wr']}%, PF={m_p2['pf']}")
    
    # Sweep-filtered hold-out
    for sw_thr in [0.0, 0.05, 0.10]:
        if sw_thr == 0:
            subset = enriched
        else:
            subset = [t for t in enriched if t['sweep_depth_atr'] is not None and t['sweep_depth_atr'] >= sw_thr]
        
        s_p1 = [t for t in subset if datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S') < datetime(2026, 6, 15)]
        s_p2 = [t for t in subset if datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S') >= datetime(2026, 6, 15)]
        
        ms1 = compute_metrics(s_p1)
        ms2 = compute_metrics(s_p2)
        
        print(f"\n  Sweep >= {sw_thr}:")
        print(f"    P1: {ms1['trades']} trades, WR={ms1['wr']}%, PF={ms1['pf']}")
        print(f"    P2: {ms2['trades']} trades, WR={ms2['wr']}%, PF={ms2['pf']}")
    
    # ============================================================
    # COMBINED: SWEEP + FR
    # ============================================================
    print("\n" + "=" * 70)
    print("COMBINED: SWEEP x FR GRID")
    print("=" * 70)
    
    sweep_vals = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20]
    fr_vals = [0.0, 0.00002, 0.00005, 0.00008]
    
    print(f"\n  {'Sweep':>6s} / {'FR':>8s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s}")
    print("  " + "-" * 55)
    
    for sw in sweep_vals:
        for fr in fr_vals:
            filtered = enriched
            if sw > 0:
                filtered = [t for t in filtered if t['sweep_depth_atr'] is not None and t['sweep_depth_atr'] >= sw]
            if fr > 0:
                filtered = [t for t in filtered if t.get('funding_rate') is not None and abs(t['funding_rate']) >= fr]
            
            m = compute_metrics(filtered)
            if m['trades'] > 0:
                print(f"  {sw:>6.3f} / {fr:>8.5f} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}%")
    
    print("\n✅ Done")
