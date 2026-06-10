import pandas as pd
import numpy as np
from src.modules.m4_cvd import calc_cvd_15m, detect_cvd_divergence_15m
from src.modules.m12_orderbook import score_m12_orderbook
from src.modules.taker_tracker import get_taker_summary

def analyze_tape_flow(df_15m, current_price, magnets, direction="NEUTRAL"):
    """
    Unifies CVD, Orderbook Imbalances, and Taker Flow into a single 
    Tape Flow analysis to detect Healthy Trends vs Absorption.
    """
    
    # 1. Taker Flow (Aggression)
    taker_summary = get_taker_summary(df_15m)
    taker_ratio = taker_summary.get('taker_ratio', 0.5)
    
    # 2. CVD Divergence (Convergence/Divergence)
    # We check if price is making higher highs while CVD makes lower highs (Bearish Divergence)
    cvd_div_series = detect_cvd_divergence_15m(df_15m, 20, 5)
    cvd_div = cvd_div_series.iloc[-1] if hasattr(cvd_div_series, 'iloc') else cvd_div_series
    
    # 3. Orderbook Imbalance (Depth)
    # Using M12 to see if there is a wall of liquidity
    status, ob_score, ob_details = score_m12_orderbook(direction)
    
    # 4. Absorption Logic
    # Absorption = Price at Magnet + High Aggressive Volume in Dir + Price NOT breaking
    absorption = "NONE"
    for mag in magnets:
        # If price is within 0.1% of a magnet
        if abs(current_price - mag) / mag < 0.001:
            # If we see high aggression but price is stalled
            if (taker_ratio > 0.7 and cvd_div == "BEARISH") or (taker_ratio < 0.3 and cvd_div == "BULLISH"):
                absorption = "DETECTED"
                break

    # 5. Final Tape State
    if absorption == "DETECTED":
        tape_state = "ABSORPTION (Potential Reversal)"
        conviction = "LOW"
    elif (taker_ratio > 0.7 and cvd_div != "BEARISH") or (taker_ratio < 0.3 and cvd_div != "BULLISH"):
        tape_state = "HEALTHY AGGRESSION"
        conviction = "HIGH"
    else:
        tape_state = "LOW VOLUME DRIFT"
        conviction = "NEUTRAL"

    return {
        'state': tape_state,
        'conviction': conviction,
        'taker_ratio': taker_ratio,
        'cvd_div': cvd_div,
        'absorption': absorption
    }
