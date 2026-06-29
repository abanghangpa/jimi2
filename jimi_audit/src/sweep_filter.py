
"""
Sweep-Against Filter - blocks signals where price recently swept against direction.
Data proof: signals where price sweeps against direction have 29.7% WR (n=236).
"""
import numpy as np

def check_sweep_against(df_15m, idx, direction, lookback=12):
    """Check if price recently swept against the signal direction.
    Returns: dict with 'blocked', 'sweep_type', 'sweep_details'
    """
    if idx < lookback:
        return {"blocked": False, "sweep_type": "NONE", "sweep_details": {}}
    
    closes = df_15m["Close"].values
    highs = df_15m["High"].values
    lows = df_15m["Low"].values
    current = closes[idx]
    start = max(0, idx - lookback)
    
    if direction == "LONG":
        recent_lows = lows[start:idx+1]
        min_low = np.min(recent_lows)
        min_idx = start + np.argmin(recent_lows)
        if min_idx > start and min_idx < idx:
            bar_range = highs[min_idx] - lows[min_idx]
            if bar_range > 0:
                wick = (closes[min_idx] - lows[min_idx]) / bar_range
                if wick < 0.40 and lows[min_idx] < current * 0.995:
                    return {"blocked": True, "sweep_type": "DOWN_SWEEP_AGAINST",
                            "sweep_details": {"sweep_price": float(min_low), "sweep_idx": int(min_idx),
                                              "wick_ratio": float(wick), "dist_pct": float((current - min_low) / current * 100)}}
    
    elif direction == "SHORT":
        recent_highs = highs[start:idx+1]
        max_high = np.max(recent_highs)
        max_idx = start + np.argmax(recent_highs)
        if max_idx > start and max_idx < idx:
            bar_range = highs[max_idx] - lows[max_idx]
            if bar_range > 0:
                wick = (highs[max_idx] - closes[max_idx]) / bar_range
                if wick < 0.40 and highs[max_idx] > current * 1.005:
                    return {"blocked": True, "sweep_type": "UP_SWEEP_AGAINST",
                            "sweep_details": {"sweep_price": float(max_high), "sweep_idx": int(max_idx),
                                              "wick_ratio": float(wick), "dist_pct": float((max_high - current) / current * 100)}}
    
    return {"blocked": False, "sweep_type": "NONE", "sweep_details": {}}
