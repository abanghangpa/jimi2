"""
Historical Derivatives Loader v3 — loads derivatives data from CSV for backtesting.
Includes computed fields: whale_signal, positioning, oi_roc_1h.
"""
import csv
import os
from datetime import datetime, timedelta

_cache = {}
_cache_loaded = False
_oi_history = {}  # ts -> oi for ROC computation

DERIV_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'derivatives_history', 'derivatives_collected.csv')

def _load_cache():
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if not os.path.exists(DERIV_CSV):
        _cache_loaded = True
        return
    try:
        with open(DERIV_CSV) as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                ts_raw = row.get("timestamp", "")
                ts = ts_raw[:16].replace("T", " ")
                ls = float(row.get("ls_ratio", 0) or 0)
                lp = float(row.get("long_pct", 0) or 0)
                sp = float(row.get("short_pct", 0) or 0)
                tls = float(row.get("top_ls_ratio", 0) or 0)
                tlp = float(row.get("top_long_pct", 0) or 0)
                tsp = float(row.get("top_short_pct", 0) or 0)
                fr = float(row.get("funding_rate", 0) or 0)
                oi = float(row.get("oi", 0) or 0)
                oi_usd = float(row.get("oi_usd", 0) or 0)
                if ls > 0:
                    _cache[ts] = {
                        "ls_ratio": ls, "long_pct": lp, "short_pct": sp,
                        "top_ls_ratio": tls, "top_long_pct": tlp, "top_short_pct": tsp,
                        "funding_rate": fr, "oi": oi, "oi_usd": oi_usd,
                    }
                    _oi_history[ts] = oi
        
        # Compute derived fields for all cached entries
        sorted_ts = sorted(_cache.keys())
        for i, ts in enumerate(sorted_ts):
            d = _cache[ts]
            ls = d["ls_ratio"]
            
            # whale_signal: derive from ls_ratio
            if ls > 2.1:
                d["whale_signal"] = "BEARISH"
            elif ls < 1.9:
                d["whale_signal"] = "BULLISH"
            else:
                d["whale_signal"] = "NEUTRAL"
            
            # positioning: derive from ls_ratio extremes
            if ls > 2.5:
                d["positioning"] = "EXTREME_LONG"
            elif ls > 2.2:
                d["positioning"] = "BULLISH"
            elif ls < 1.5:
                d["positioning"] = "EXTREME_SHORT"
            elif ls < 1.8:
                d["positioning"] = "BEARISH"
            else:
                d["positioning"] = "NEUTRAL"
            
            # oi_roc_1h: compute from OI change over ~1 hour (look back 4 entries at 15min intervals)
            if i >= 4:
                prev_ts = sorted_ts[i-4]
                prev_oi = _oi_history.get(prev_ts, 0)
                if prev_oi > 0:
                    d["oi_roc_1h"] = (d["oi"] - prev_oi) / prev_oi
                else:
                    d["oi_roc_1h"] = 0
            else:
                d["oi_roc_1h"] = 0
                
    except Exception:
        pass
    _cache_loaded = True

def get_historical_derivatives(timestamp_str):
    """Get derivatives data for a given timestamp.
    Returns dict or None. Tries exact match, then +/-15/30min."""
    _load_cache()
    if not _cache:
        return None

    ts = str(timestamp_str)[:16]

    # Exact match
    if ts in _cache:
        return _cache[ts]

    # Try window
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        for offset in [15, -15, 30, -30]:
            dt2 = dt + timedelta(minutes=offset)
            k = dt2.strftime("%Y-%m-%d %H:%M")
            if k in _cache:
                return _cache[k]
    except Exception:
        pass

    return None

