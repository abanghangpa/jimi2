#!/usr/bin/env python3
"""
Run threshold validation across ALL synthetic derivative scenarios.
Tests robustness: strategy must work in extreme_bull, extreme_bear, etc.
"""
import csv, os, sys, json, shutil
from datetime import datetime, timedelta
import numpy as np

BASE = "/root/.openclaw/workspace/jimi_audit"
ETH_FILE = os.path.join(BASE, "eth_15m_merged.csv")
REAL_DERIV = os.path.join(BASE, "data", "derivatives_history", "derivatives_collected.csv")
SYNTH_DIR = os.path.join(BASE, "data", "derivatives_synthetic")
TRADES_FILE = os.path.join(BASE, "reports", "whale_pair_analysis.json")

# ============================================================
# REUSE FUNCTIONS FROM validate_v5.py
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

def load_derivatives(path):
    deriv = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row['timestamp']
            try:
                dt = datetime.fromisoformat(ts)
            except:
                continue
            dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
            deriv[dt_floor.strftime('%Y-%m-%d %H:%M:%S')] = {
                'ls_ratio': float(row['ls_ratio']),
                'funding_rate': float(row['funding_rate']),
            }
    return deriv

def load_trades():
    with open(TRADES_FILE) as f:
        data = json.load(f)
    return data['results']['liquidity_grab']['trades']

def find_nearest_deriv(deriv_map, time_str, max_hours=2):
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    for offset_min in range(0, max_hours * 60 + 1, 1):
        for check_dt in [dt - timedelta(minutes=offset_min), dt + timedelta(minutes=offset_min)]:
            check_str = check_dt.strftime('%Y-%m-%d %H:%M:%S')
            if check_str in deriv_map:
                return deriv_map[check_str]
    return None

def find_sweep_for_trade(bars, bar_index, direction, lookback=20):
    if bar_index < lookback + 10:
        return None
    closes = [bars[i]['close'] for i in range(bar_index - lookback, bar_index)]
    highs = [bars[i]['high'] for i in range(bar_index - lookback, bar_index)]
    lows = [bars[i]['low'] for i in range(bar_index - lookback, bar_index)]
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    atr = np.mean(trs) if trs else 0
    if atr <= 0:
        return None
    pre_highs = [bars[i]['high'] for i in range(bar_index - lookback - 10, bar_index - lookback)]
    pre_lows = [bars[i]['low'] for i in range(bar_index - lookback - 10, bar_index - lookback)]
    swing_high = max(pre_highs)
    swing_low = min(pre_lows)
    best = None
    for i in range(bar_index - lookback, bar_index):
        bar = bars[i]
        if direction == 'SHORT' and bar['high'] > swing_high:
            d = (bar['high'] - swing_high) / atr
            if best is None or d > best['depth_atr']:
                best = {'depth_atr': d, 'closed_back': bar['close'] < swing_high}
        elif direction == 'LONG' and bar['low'] < swing_low:
            d = (swing_low - bar['low']) / atr
            if best is None or d > best['depth_atr']:
                best = {'depth_atr': d, 'closed_back': bar['close'] > swing_low}
    return best

def compute_metrics(trades):
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0}
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_win = sum(t['pnl'] for t in wins)
    total_loss = sum(abs(t['pnl']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(len(wins)/len(trades)*100, 1),
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl'] for t in trades), 4),
    }

# ============================================================
# RUN TESTS
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("SCENARIO ROBUSTNESS TEST")
    print("17 actual trades × 10 synthetic derivative scenarios")
    print("=" * 70)
    
    bars = load_eth_bars()
    bar_map = {b['dt']: i for i, b in enumerate(bars)}
    trades_raw = load_trades()
    
    # Compute sweep data once (doesn't depend on derivatives)
    enriched_base = []
    for t in trades_raw:
        if t['time'] not in bar_map:
            continue
        bar_idx = bar_map[t['time']]
        sweep = find_sweep_for_trade(bars, bar_idx, t['dir'])
        enriched_base.append({
            **t,
            'sweep_depth_atr': sweep['depth_atr'] if sweep else None,
        })
    
    # Get scenario files
    scenario_files = sorted([f for f in os.listdir(SYNTH_DIR) if f.endswith('_merged.csv')])
    
    # Also test with real data as baseline
    all_scenarios = [('real_data', REAL_DERIV)] + [
        (f.replace('derivatives_', '').replace('_merged.csv', ''), os.path.join(SYNTH_DIR, f))
        for f in scenario_files
    ]
    
    # Test configs
    configs = [
        {'sweep': None, 'fr': None, 'label': 'baseline'},
        {'sweep': 0.05, 'fr': None, 'label': 'sweep>=0.05'},
        {'sweep': 0.08, 'fr': None, 'label': 'sweep>=0.08'},
        {'sweep': None, 'fr': 0.00005, 'label': 'FR>=5e-5'},
        {'sweep': None, 'fr': 0.00008, 'label': 'FR>=8e-5'},
        {'sweep': 0.05, 'fr': 0.00005, 'label': 'sw>=0.05+FR>=5e-5'},
    ]
    
    # Results table
    print(f"\n{'Scenario':<22s} | {'Config':<20s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL':>8s}")
    print("-" * 85)
    
    all_results = []
    
    for scenario_name, deriv_path in all_scenarios:
        deriv_map = load_derivatives(deriv_path)
        
        # Enrich trades with derivatives from this scenario
        enriched = []
        for t in enriched_base:
            deriv = find_nearest_deriv(deriv_map, t['time'])
            enriched.append({
                **t,
                'funding_rate': deriv['funding_rate'] if deriv else None,
                'ls_ratio_deriv': deriv['ls_ratio'] if deriv else None,
            })
        
        for cfg in configs:
            filtered = enriched
            if cfg['sweep'] is not None:
                filtered = [t for t in filtered if t['sweep_depth_atr'] is not None and t['sweep_depth_atr'] >= cfg['sweep']]
            if cfg['fr'] is not None:
                filtered = [t for t in filtered if t.get('funding_rate') is not None and abs(t['funding_rate']) >= cfg['fr']]
            
            m = compute_metrics(filtered)
            
            row = {
                'scenario': scenario_name,
                'config': cfg['label'],
                **m,
            }
            all_results.append(row)
            
            # Only print if non-zero trades
            if m['trades'] > 0:
                print(f"  {scenario_name:<22s} | {cfg['label']:<20s} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}%")
            else:
                print(f"  {scenario_name:<22s} | {cfg['label']:<20s} | {m['trades']:>6d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | {m['pnl']:>+7.4f}%")
        
        print()  # blank line between scenarios
    
    # ============================================================
    # SUMMARY: Consistency across scenarios
    # ============================================================
    print("=" * 70)
    print("CONSISTENCY SUMMARY — Does the edge survive all scenarios?")
    print("=" * 70)
    
    for cfg in configs:
        cfg_results = [r for r in all_results if r['config'] == cfg['label'] and r['trades'] > 0]
        if not cfg_results:
            continue
        
        wrs = [r['wr'] for r in cfg_results]
        pfs = [r['pf'] for r in cfg_results]
        trades = [r['trades'] for r in cfg_results]
        
        min_wr = min(wrs)
        max_wr = max(wrs)
        min_pf = min(pfs)
        max_pf = max(pfs)
        avg_wr = np.mean(wrs)
        avg_pf = np.mean(pfs)
        
        # Count scenarios where PF >= 2.0
        pf_above_2 = sum(1 for pf in pfs if pf >= 2.0)
        # Count scenarios where WR >= 75%
        wr_above_75 = sum(1 for wr in wrs if wr >= 75)
        
        print(f"\n  {cfg['label']:<20s}: {len(cfg_results)} scenarios with trades")
        print(f"    WR: min={min_wr:.1f}% avg={avg_wr:.1f}% max={max_wr:.1f}%")
        print(f"    PF: min={min_pf:.2f} avg={avg_pf:.2f} max={max_pf:.2f}")
        print(f"    PF>=2.0: {pf_above_2}/{len(cfg_results)} scenarios")
        print(f"    WR>=75%: {wr_above_75}/{len(cfg_results)} scenarios")
    
    # Save results
    report_path = os.path.join(BASE, "reports", "scenario_robustness_test.json")
    with open(report_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n✅ Results saved to {report_path}")
