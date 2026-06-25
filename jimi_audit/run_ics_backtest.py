#!/usr/bin/env python3
"""
Full backtest: measure ICS contribution of M66-M73 modules.
Uses existing eth_15m_merged.csv and engine's run_backtest().
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np

from src.engine import run_backtest
from src.config import CONFIG

CSV_PATH = os.path.join(os.path.dirname(__file__), 'eth_15m_merged.csv')


def run_single_backtest(config, label=""):
    """Run a single backtest and return stats."""
    print(f"\n{'='*70}")
    print(f"  BACKTEST: {label}")
    print(f"{'='*70}")
    
    try:
        trades, stats, df_result = run_backtest(CSV_PATH, config=config)
        
        return {
            'label': label,
            'total_trades': stats.get('total_trades', 0),
            'win_rate': stats.get('win_rate', 0),
            'total_pnl': stats.get('total_pnl', 0),
            'max_drawdown': stats.get('max_drawdown', 0),
            'sharpe': stats.get('sharpe', 0),
            'profit_factor': stats.get('profit_factor', 0),
            'm66_pass': stats.get('m66_pass', 0),
            'm67_pass': stats.get('m67_pass', 0),
            'm68_pass': stats.get('m68_pass', 0),
            'm69_pass': stats.get('m69_pass', 0),
            'm70_pass': stats.get('m70_pass', 0),
            'm71_pass': stats.get('m71_pass', 0),
            'm72_pass': stats.get('m72_pass', 0),
            'm73_pass': stats.get('m73_pass', 0),
            'stats': stats,
        }
    except Exception as e:
        print(f"  ❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("=" * 70)
    print("  M66-M73 ICS Contribution Backtest")
    print("=" * 70)
    
    if not os.path.exists(CSV_PATH):
        print(f"❌ {CSV_PATH} not found")
        return 1
    
    print(f"Data: {CSV_PATH}")
    df_check = pd.read_csv(CSV_PATH, nrows=1)
    print(f"Columns: {list(df_check.columns[:5])}...")
    total_rows = sum(1 for _ in open(CSV_PATH)) - 1
    print(f"Total rows: {total_rows:,}")
    
    # Run baseline (M66-M73 disabled)
    baseline_config = CONFIG.copy()
    baseline_config['M66_ENABLED'] = False
    baseline_config['M67_ENABLED'] = False
    baseline_config['M68_ENABLED'] = False
    baseline_config['M69_ENABLED'] = False
    baseline_config['M70_ENABLED'] = False
    baseline_config['M71_ENABLED'] = False
    baseline_config['M72_ENABLED'] = False
    baseline_config['M73_ENABLED'] = False
    
    baseline = run_single_backtest(baseline_config, "BASELINE (M66-M73 disabled)")
    
    # Run with M66-M73 enabled (current CONFIG)
    enabled = run_single_backtest(CONFIG, "ENABLED (M66-M73 active)")
    
    # Compare results
    if baseline and enabled:
        print(f"\n{'='*70}")
        print(f"  COMPARISON: Baseline vs M66-M73 Enabled")
        print(f"{'='*70}")
        
        print(f"\n{'Metric':<25} {'Baseline':>15} {'Enabled':>15} {'Delta':>15}")
        print("-" * 70)
        
        for metric in ['total_trades', 'win_rate', 'total_pnl', 'max_drawdown', 'sharpe', 'profit_factor']:
            b_val = baseline.get(metric, 0)
            e_val = enabled.get(metric, 0)
            delta = e_val - b_val
            print(f"{metric:<25} {b_val:>15.4f} {e_val:>15.4f} {delta:>+15.4f}")
        
        print(f"\n  M66-M73 Module Pass Counts:")
        for m in ['m66_pass', 'm67_pass', 'm68_pass', 'm69_pass', 'm70_pass', 'm71_pass', 'm72_pass', 'm73_pass']:
            e_val = enabled.get(m, 0)
            print(f"    {m:<15} {e_val:>10,}")
        
        total_pass = sum(enabled.get(m, 0) for m in ['m66_pass', 'm67_pass', 'm68_pass', 'm69_pass', 'm70_pass', 'm71_pass', 'm72_pass', 'm73_pass'])
        total_trades = enabled.get('total_trades', 1)
        print(f"\n  Total M66-M73 PASS signals: {total_pass:,}")
        print(f"  Total trades: {total_trades:,}")
        if total_trades > 0:
            print(f"  M66-M73 contribution rate: {total_pass/total_trades*100:.1f}%")
    
    print(f"\n{'='*70}")
    print("✅ Backtest complete")
    return 0


if __name__ == '__main__':
    sys.exit(main())
