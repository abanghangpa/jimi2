"""
Cross-Asset Historical Loader — loads DXY, VIX, Gold, WTI, USDJPY from CSV.
Usage:
    from src.modules.cross_asset_loader import get_cross_asset_at
    data = get_cross_asset_at("2026-06-22 12:00")
"""
import csv, os
from datetime import datetime, timedelta

_cache = {}
_cache_loaded = False

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'data', 'cross_asset')

def _load_csv(name, filename):
    """Load a CSV file into cache dict keyed by timestamp."""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return
    try:
        import pandas as pd
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        for ts, row in df.iterrows():
            ts_str = str(ts)[:16]
            if ts_str not in _cache:
                _cache[ts_str] = {}
            close_val = float(row.get('Close', row.get('close', 0)))
            if close_val > 0:
                _cache[ts_str][f'{name}_close'] = close_val
                high_val = float(row.get('High', row.get('high', close_val)))
                low_val = float(row.get('Low', row.get('low', close_val)))
                _cache[ts_str][f'{name}_high'] = high_val
                _cache[ts_str][f'{name}_low'] = low_val
    except Exception:
        pass

def _load_all():
    global _cache_loaded
    if _cache_loaded:
        return
    _load_csv('dxy', 'dxy.csv')
    _load_csv('vix', 'vix.csv')
    _load_csv('gold', 'gold.csv')
    _load_csv('wti', 'wti.csv')
    _load_csv('usdjpy', 'usdjpy.csv')
    _load_csv('us10y', 'us10y.csv')
    _load_csv('dxy_d', 'dxy_daily.csv')
    _load_csv('gold_d', 'gold_daily.csv')
    _load_csv('wti_d', 'wti_daily.csv')
    _load_csv('usdjpy_d', 'usdjpy_daily.csv')
    _cache_loaded = True

def get_cross_asset_at(timestamp_str):
    """Get cross-asset data at a given timestamp. Returns dict or empty dict."""
    _load_all()
    ts = str(timestamp_str)[:16]

    # Exact match
    if ts in _cache:
        return _cache[ts]

    # Try nearby timestamps (within 2h for intraday, 24h for daily)
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        for offset_min in [15, -15, 30, -30, 60, -60, 120, -120]:
            k = (dt + timedelta(minutes=offset_min)).strftime("%Y-%m-%d %H:%M")
            if k in _cache:
                return _cache[k]
        # Try daily (different time)
        for offset_hr in [0, 6, 12, 18]:
            k = dt.replace(hour=offset_hr).strftime("%Y-%m-%d %H:%M")
            if k in _cache:
                return _cache[k]
    except Exception:
        pass

    return {}
