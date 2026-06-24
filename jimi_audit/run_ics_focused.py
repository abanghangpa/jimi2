#!/usr/bin/env python3
"""
Focused M66-M73 ICS test: score all tradfi modules over the dataset.
Measures signal rate and score distribution without full engine overhead.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd
import numpy as np
from src.config import CONFIG

# Load aligned tradfi data
TRADFI_PATH = os.path.join(os.path.dirname(__file__), 'data', 'tradfi', 'aligned.csv')
ETH_PATH = os.path.join(os.path.dirname(__file__), 'eth_15m_merged.csv')

print("Loading data...")
tradfi = pd.read_csv(TRADFI_PATH)
tradfi['_ts'] = pd.to_datetime(tradfi['datetime'])
print(f"Tradfi: {len(tradfi):,} rows")

eth = pd.read_csv(ETH_PATH, low_memory=False)
eth['Open time'] = pd.to_datetime(eth['Open time'])
# Only need last year
cutoff = eth['Open time'].max() - pd.Timedelta(days=365)
eth = eth[eth['Open time'] >= cutoff].copy().reset_index(drop=True)
print(f"ETH (1yr): {len(eth):,} bars")

# Import scoring functions
from src.modules.m66_usdjpy import score_m66_usdjpy
from src.modules.m67_dxy import score_m67_dxy
from src.modules.m68_yield import score_m68_yield
from src.modules.m69_vix import score_m69_vix
from src.modules.m70_wti import score_m70_wti
from src.modules.m71_gold import score_m71_gold

# Score each bar
results = {f'm{i}': {'pass': 0, 'neutral': 0, 'skip': 0, 'scores': []} for i in range(66, 72)}
total_bars = len(eth)

print(f"\nScoring {total_bars:,} bars...")
for idx in range(20, total_bars):
    ts = eth.iloc[idx]['Open time']
    
    # Find tradfi row
    tf_idx = tradfi['_ts'].searchsorted(ts, side='right') - 1
    if tf_idx < 0:
        continue
    tf_row = tradfi.iloc[tf_idx]
    tf_prev = tradfi.iloc[max(0, tf_idx - 1)]
    
    direction = 'LONG'  # test both directions later
    
    # M66: USD/JPY
    if not pd.isna(tf_row.get('usdjpy', float('nan'))):
        start = max(0, tf_idx - 19)
        df_u = tradfi.iloc[start:tf_idx+1][['usdjpy_open','usdjpy_high','usdjpy_low','usdjpy']].copy()
        df_u.columns = ['Open','High','Low','Close']
        df_dxy = pd.DataFrame({'Close':[tf_prev['dxy'],tf_row['dxy']],'Open':[tf_prev['dxy'],tf_row['dxy']],'High':[tf_prev['dxy'],tf_row['dxy']],'Low':[tf_prev['dxy'],tf_row['dxy']]})
        try:
            s, sc, d = score_m66_usdjpy(df_u, df_dxy, direction, config=CONFIG)
            results['m66']['scores'].append(sc)
            if s == 'PASS': results['m66']['pass'] += 1
            elif s == 'NEUTRAL': results['m66']['neutral'] += 1
            else: results['m66']['skip'] += 1
        except: results['m66']['skip'] += 1
    
    # M67: DXY
    if not pd.isna(tf_row.get('dxy', float('nan'))):
        df_d = pd.DataFrame({'Close':[tf_prev['dxy'],tf_row['dxy']],'Open':[tf_prev['dxy'],tf_row['dxy']],'High':[tf_prev['dxy'],tf_row['dxy']],'Low':[tf_prev['dxy'],tf_row['dxy']]})
        try:
            s, sc, d = score_m67_dxy(df_d, float(eth.iloc[idx]['Close']), float(eth.iloc[max(0,idx-1)]['Close']), direction, config=CONFIG)
            results['m67']['scores'].append(sc)
            if s == 'PASS': results['m67']['pass'] += 1
            elif s == 'NEUTRAL': results['m67']['neutral'] += 1
            else: results['m67']['skip'] += 1
        except: results['m67']['skip'] += 1
    
    # M68: Yield
    if not pd.isna(tf_row.get('tnx', float('nan'))):
        df_t = pd.DataFrame({'Close':[tf_prev['tnx'],tf_row['tnx']]})
        try:
            s, sc, d = score_m68_yield(df_t, None, direction, config=CONFIG)
            results['m68']['scores'].append(sc)
            if s == 'PASS': results['m68']['pass'] += 1
            elif s == 'NEUTRAL': results['m68']['neutral'] += 1
            else: results['m68']['skip'] += 1
        except: results['m68']['skip'] += 1
    
    # M69: VIX
    if not pd.isna(tf_row.get('vix', float('nan'))):
        df_v = pd.DataFrame({'Close':[tf_prev['vix'],tf_row['vix']],'Open':[tf_prev['vix'],tf_row['vix']],'High':[tf_prev['vix'],tf_row['vix']],'Low':[tf_prev['vix'],tf_row['vix']]})
        df_d = pd.DataFrame({'Close':[tf_prev['dxy'],tf_row['dxy']],'Open':[tf_prev['dxy'],tf_row['dxy']],'High':[tf_prev['dxy'],tf_row['dxy']],'Low':[tf_prev['dxy'],tf_row['dxy']]})
        try:
            s, sc, d = score_m69_vix(df_v, direction, config=CONFIG, df_dxy=df_d)
            results['m69']['scores'].append(sc)
            if s == 'PASS': results['m69']['pass'] += 1
            elif s == 'NEUTRAL': results['m69']['neutral'] += 1
            else: results['m69']['skip'] += 1
        except: results['m69']['skip'] += 1
    
    # M70: WTI
    if not pd.isna(tf_row.get('wti', float('nan'))):
        df_w = pd.DataFrame({'Close':[tf_prev['wti'],tf_row['wti']],'Open':[tf_prev['wti'],tf_row['wti']],'High':[tf_prev['wti'],tf_row['wti']],'Low':[tf_prev['wti'],tf_row['wti']]})
        df_d = pd.DataFrame({'Close':[tf_prev['dxy'],tf_row['dxy']],'Open':[tf_prev['dxy'],tf_row['dxy']],'High':[tf_prev['dxy'],tf_row['dxy']],'Low':[tf_prev['dxy'],tf_row['dxy']]})
        try:
            s, sc, d = score_m70_wti(df_w, df_d, direction, config=CONFIG)
            results['m70']['scores'].append(sc)
            if s == 'PASS': results['m70']['pass'] += 1
            elif s == 'NEUTRAL': results['m70']['neutral'] += 1
            else: results['m70']['skip'] += 1
        except: results['m70']['skip'] += 1
    
    # M71: Gold
    if not pd.isna(tf_row.get('gold', float('nan'))):
        df_g = pd.DataFrame({'Close':[tf_prev['gold'],tf_row['gold']],'Open':[tf_prev['gold'],tf_row['gold']],'High':[tf_prev['gold'],tf_row['gold']],'Low':[tf_prev['gold'],tf_row['gold']]})
        df_d = pd.DataFrame({'Close':[tf_prev['dxy'],tf_row['dxy']],'Open':[tf_prev['dxy'],tf_row['dxy']],'High':[tf_prev['dxy'],tf_row['dxy']],'Low':[tf_prev['dxy'],tf_row['dxy']]})
        try:
            s, sc, d = score_m71_gold(df_g, df_d, direction, config=CONFIG)
            results['m71']['scores'].append(sc)
            if s == 'PASS': results['m71']['pass'] += 1
            elif s == 'NEUTRAL': results['m71']['neutral'] += 1
            else: results['m71']['skip'] += 1
        except: results['m71']['skip'] += 1

# Print results
print(f"\n{'='*70}")
print(f"  M66-M71 Signal Distribution (1yr, {total_bars:,} bars, LONG direction)")
print(f"{'='*70}")
print(f"\n{'Module':<10} {'PASS':>10} {'NEUTRAL':>10} {'SKIP':>10} {'PASS%':>10} {'Avg Score':>12} {'Std':>10}")
print("-" * 70)

for i in range(66, 72):
    m = f'm{i}'
    r = results[m]
    total = r['pass'] + r['neutral'] + r['skip']
    pass_pct = r['pass'] / total * 100 if total > 0 else 0
    avg_score = np.mean(r['scores']) if r['scores'] else 0.5
    std_score = np.std(r['scores']) if r['scores'] else 0
    print(f"M{i:<8} {r['pass']:>10,} {r['neutral']:>10,} {r['skip']:>10,} {pass_pct:>9.1f}% {avg_score:>12.4f} {std_score:>10.4f}")

# ICS weight contribution
print(f"\n{'='*70}")
print(f"  ICS Weight Contribution (M66-M73)")
print(f"{'='*70}")
weights = {
    'M66': CONFIG.get('M66_WEIGHT', 0.02),
    'M67': CONFIG.get('M67_WEIGHT', 0.02),
    'M68': CONFIG.get('M68_WEIGHT', 0.03),
    'M69': CONFIG.get('M69_WEIGHT', 0.03),
    'M70': CONFIG.get('M70_WEIGHT', 0.02),
    'M71': CONFIG.get('M71_WEIGHT', 0.02),
    'M72': CONFIG.get('M72_WEIGHT', 0.04),
    'M73': CONFIG.get('M73_WEIGHT', 0.02),
}
total_weight = sum(weights.values())
print(f"  Total M66-M73 weight budget: {total_weight:.2f}")
for m, w in weights.items():
    print(f"    {m}: {w:.2f}")
print(f"  Remaining for M1-M5 + others: {1.0 - total_weight:.2f}")

# Score distribution analysis
print(f"\n{'='*70}")
print(f"  Score Distribution (LONG direction)")
print(f"{'='*70}")
for i in range(66, 72):
    m = f'm{i}'
    scores = results[m]['scores']
    if not scores:
        continue
    pcts = np.percentile(scores, [5, 25, 50, 75, 95])
    print(f"  M{i}: p5={pcts[0]:.3f} p25={pcts[1]:.3f} p50={pcts[2]:.3f} p75={pcts[3]:.3f} p95={pcts[4]:.3f}")

print(f"\n✅ Done")
