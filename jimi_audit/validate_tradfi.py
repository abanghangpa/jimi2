#!/usr/bin/env python3
"""
Quick validation: verify M66-M73 can score against aligned tradfi data.
Tests each module individually with sample data from aligned.csv.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np

# Import scoring functions
from src.modules.m66_usdjpy import score_m66_usdjpy
from src.modules.m67_dxy import score_m67_dxy
from src.modules.m68_yield import score_m68_yield
from src.modules.m69_vix import score_m69_vix
from src.modules.m70_wti import score_m70_wti
from src.modules.m71_gold import score_m71_gold
from src.modules.m72_btcdom import fetch_btcdom, score_m72_btcdom
from src.modules.m73_stablecoin import fetch_stablecoin_mints, score_m73_stablecoin

from src.config import CONFIG


def load_tradfi_data():
    """Load aligned tradfi data."""
    path = os.path.join(os.path.dirname(__file__), 'data', 'tradfi', 'aligned.csv')
    if not os.path.exists(path):
        print(f"❌ {path} not found")
        return None
    df = pd.read_csv(path)
    df['_ts'] = pd.to_datetime(df['datetime'])
    print(f"✅ Loaded {len(df):,} rows from aligned.csv")
    return df


def test_module(name, score_fn, tradfi_df, idx, direction='LONG'):
    """Test a single module at a given index."""
    try:
        row = tradfi_df.iloc[idx]
        prev_idx = max(0, idx - 1)
        prev_row = tradfi_df.iloc[prev_idx]
        
        status, score, details = score_fn(row, prev_row, direction, config=CONFIG)
        return status, score, details
    except Exception as e:
        return 'ERROR', 0.5, {'error': str(e)}


def main():
    print("=" * 60)
    print("M66-M73 Quick Validation")
    print("=" * 60)
    
    # Load data
    tradfi_df = load_tradfi_data()
    if tradfi_df is None:
        return 1
    
    # Test at multiple points (beginning, middle, end)
    test_indices = [100, len(tradfi_df) // 2, len(tradfi_df) - 100]
    
    for direction in ['LONG', 'SHORT']:
        print(f"\n{'='*60}")
        print(f"Direction: {direction}")
        print(f"{'='*60}")
        
        for idx in test_indices:
            ts = tradfi_df.iloc[idx]['datetime']
            print(f"\n--- Index {idx} ({ts}) ---")
            
            # M66: USD/JPY
            row = tradfi_df.iloc[idx]
            prev_row = tradfi_df.iloc[max(0, idx - 1)]
            
            # Build DataFrames for M66 (needs 20 rows)
            start = max(0, idx - 19)
            df_usdjpy = tradfi_df.iloc[start:idx + 1][['usdjpy_open', 'usdjpy_high', 'usdjpy_low', 'usdjpy']].copy()
            df_usdjpy.columns = ['Open', 'High', 'Low', 'Close']
            df_dxy = pd.DataFrame({'Close': [prev_row['dxy'], row['dxy']], 'Open': [prev_row['dxy'], row['dxy']], 'High': [prev_row['dxy'], row['dxy']], 'Low': [prev_row['dxy'], row['dxy']]})
            
            status, score, details = score_m66_usdjpy(df_usdjpy, df_dxy, direction, config=CONFIG)
            print(f"  M66 (USD/JPY): status={status}, score={score:.3f}, class={details.get('classification', 'N/A')}")
            
            # M67: DXY
            df_dxy_m67 = pd.DataFrame({'Close': [prev_row['dxy'], row['dxy']], 'Open': [prev_row['dxy'], row['dxy']], 'High': [prev_row['dxy'], row['dxy']], 'Low': [prev_row['dxy'], row['dxy']]})
            eth_now = 100  # dummy
            eth_prev = 100
            status, score, details = score_m67_dxy(df_dxy_m67, eth_now, eth_prev, direction, config=CONFIG)
            print(f"  M67 (DXY):     status={status}, score={score:.3f}, class={details.get('classification', 'N/A')}")
            
            # M68: Yield
            df_tnx = pd.DataFrame({'Close': [prev_row['tnx'], row['tnx']]})
            status, score, details = score_m68_yield(df_tnx, None, direction, config=CONFIG)
            print(f"  M68 (Yield):   status={status}, score={score:.3f}, class={details.get('classification', 'N/A')}")
            
            # M69: VIX
            df_vix = pd.DataFrame({'Close': [prev_row['vix'], row['vix']], 'Open': [prev_row['vix'], row['vix']], 'High': [prev_row['vix'], row['vix']], 'Low': [prev_row['vix'], row['vix']]})
            status, score, details = score_m69_vix(df_vix, direction, config=CONFIG, df_dxy=df_dxy_m67)
            print(f"  M69 (VIX):     status={status}, score={score:.3f}, class={details.get('classification', 'N/A')}")
            
            # M70: WTI
            df_wti = pd.DataFrame({'Close': [prev_row['wti'], row['wti']], 'Open': [prev_row['wti'], row['wti']], 'High': [prev_row['wti'], row['wti']], 'Low': [prev_row['wti'], row['wti']]})
            status, score, details = score_m70_wti(df_wti, df_dxy_m67, direction, config=CONFIG)
            print(f"  M70 (WTI):     status={status}, score={score:.3f}, class={details.get('classification', 'N/A')}")
            
            # M71: Gold
            df_gold = pd.DataFrame({'Close': [prev_row['gold'], row['gold']], 'Open': [prev_row['gold'], row['gold']], 'High': [prev_row['gold'], row['gold']], 'Low': [prev_row['gold'], row['gold']]})
            status, score, details = score_m71_gold(df_gold, df_dxy_m67, direction, config=CONFIG)
            print(f"  M71 (Gold):    status={status}, score={score:.3f}, class={details.get('classification', 'N/A')}")
    
    # M72: BTC Dominance (API call - test once)
    print(f"\n{'='*60}")
    print("M72 (BTC Dominance) - API test")
    print(f"{'='*60}")
    try:
        btc_d = fetch_btcdom()
        if btc_d is not None:
            status, score, details = score_m72_btcdom(btc_d, 'LONG', config=CONFIG)
            print(f"  BTC.D={btc_d:.1f}%: status={status}, score={score:.3f}")
        else:
            print("  ⚠️  fetch_btcdom returned None (API unavailable)")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # M73: Stablecoin (API call - test once)
    print(f"\n{'='*60}")
    print("M73 (Stablecoin Mints) - API test")
    print(f"{'='*60}")
    try:
        mint_data = fetch_stablecoin_mints()
        if mint_data is not None:
            status, score, details = score_m73_stablecoin(mint_data, 'LONG', config=CONFIG)
            print(f"  Mint data: status={status}, score={score:.3f}, details={details}")
        else:
            print("  ⚠️  fetch_stablecoin_mints returned None (API unavailable)")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    print(f"\n{'='*60}")
    print("✅ Validation complete")
    return 0


if __name__ == '__main__':
    sys.exit(main())
