import sys
import os
import numpy as np

# Ensure workspace root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.sl_tp import calc_limit_entry, calc_trade_levels
from src.scanner_core import run_full_scan

def simulate_long_scenario():
    print("📡 Fetching current market data for Long Scenario simulation...")
    results = run_full_scan()
    if not results:
        print("❌ No data available.")
        return

    current_price = results.get('current_price', 0)
    atr = results.get('atr', 10.0)
    magnets = results.get('magnets', [])
    sr_levels = results.get('sr_levels', [])
    liq_levels = results.get('liq_levels', {})

    print(f"\n--- MARKET STATE ---")
    print(f"Current Price: ${current_price:.2f}")
    print(f"Volume Magnets: {[f'${m:.2f}' for m in magnets]}")
    print(f"ATR (1h): {atr:.2f}")
    print(f"-------------------\n")

    # Force a LONG direction for the simulation
    trade_dir = "LONG"
    
    # 1. Calculate Limit Entry
    entry_res = calc_limit_entry(current_price, trade_dir, magnets, sr_levels, atr_1h=atr)
    entry_price = entry_res['entry_price']
    
    # 2. Calculate TP/SL
    levels = calc_trade_levels(
        entry_price, trade_dir, atr, 1.0, 
        magnets, sr_levels, liq_levels
    )
    
    print(f"🎯 LONG RECOVERY PLAN (Scenario: Bottomed/Failed Breakout)")
    print(f"Entry: ${entry_price:.2f} ({entry_res['entry_source']})")
    print(f"Reason: {entry_res['reason']}")
    print(f"Stop Loss: ${levels['sl']:.2f} ({levels['sl_source']})")
    print(f"TP1: ${levels['tp1']:.2f} ({levels['tp1_source']})")
    print(f"TP2: ${levels['tp2']:.2f}")
    print(f"TP3: ${levels['tp3']:.2f}")
    print(f"--------------------------------------------------------")

if __name__ == "__main__":
    simulate_long_scenario()
