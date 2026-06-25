#!/usr/bin/env python3
"""
Quick ICS backtest: last 1 year only, baseline vs M66-M73 enabled.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd
import numpy as np
from src.engine import run_backtest
from src.config import CONFIG

CSV_PATH = os.path.join(os.path.dirname(__file__), 'eth_15m_merged.csv')
TMP_CSV = '/tmp/jimi_bt_subset.csv'

# Load and filter to last 1 year
print("Loading data...")
df = pd.read_csv(CSV_PATH, low_memory=False)
df['Open time'] = pd.to_datetime(df['Open time'])
cutoff = df['Open time'].max() - pd.Timedelta(days=365)
df_sub = df[df['Open time'] >= cutoff].copy()
df_sub.to_csv(TMP_CSV, index=False)
print(f"Subset: {len(df_sub):,} bars ({df_sub['Open time'].iloc[0]} → {df_sub['Open time'].iloc[-1]})")

def run_bt(config, label):
    print(f"\n{'='*70}\n  {label}\n{'='*70}")
    try:
        trades, stats, _ = run_backtest(TMP_CSV, config=config)
        return stats
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        import traceback; traceback.print_exc()
        return None

# Baseline
b_cfg = CONFIG.copy()
for k in ['M66_ENABLED','M67_ENABLED','M68_ENABLED','M69_ENABLED','M70_ENABLED','M71_ENABLED','M72_ENABLED','M73_ENABLED']:
    b_cfg[k] = False
baseline = run_bt(b_cfg, "BASELINE (M66-M73 disabled)")

# Enabled
enabled = run_bt(CONFIG, "ENABLED (M66-M73 active)")

# Compare
if baseline and enabled:
    print(f"\n{'='*70}")
    print(f"  COMPARISON (last 1 year)")
    print(f"{'='*70}")
    print(f"\n{'Metric':<25} {'Baseline':>15} {'Enabled':>15} {'Delta':>15}")
    print("-" * 70)
    for m in ['total_trades','win_rate','total_pnl','max_drawdown','sharpe','profit_factor']:
        b, e = baseline.get(m,0), enabled.get(m,0)
        print(f"{m:<25} {b:>15.4f} {e:>15.4f} {e-b:>+15.4f}")
    
    print(f"\n  M66-M73 Module Pass Counts:")
    for m in ['m66_pass','m67_pass','m68_pass','m69_pass','m70_pass','m71_pass','m72_pass','m73_pass']:
        print(f"    {m:<15} {enabled.get(m,0):>10,}")
    
    tp = sum(enabled.get(m,0) for m in ['m66_pass','m67_pass','m68_pass','m69_pass','m70_pass','m71_pass','m72_pass','m73_pass'])
    tt = enabled.get('total_trades',1)
    print(f"\n  Total M66-M73 PASS: {tp:,} / {tt:,} trades ({tp/tt*100:.1f}%)")

print("\n✅ Done")
