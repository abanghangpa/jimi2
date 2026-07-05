#!/usr/bin/env python3
"""
Cross-Asset Historical Data Fetcher
Downloads DXY, VIX, Gold, WTI, USDJPY, BTC.D from yfinance.
Saves to data/cross_asset/ as CSVs for backtesting.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'cross_asset')
os.makedirs(DATA_DIR, exist_ok=True)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

ASSETS = {
    "dxy": {"ticker": "DX-Y.NYB", "interval": "15m", "period": "60d"},
    "vix": {"ticker": "^VIX", "interval": "1d", "period": "2y"},
    "gold": {"ticker": "GC=F", "interval": "4h", "period": "60d"},
    "wti": {"ticker": "CL=F", "interval": "4h", "period": "60d"},
    "usdjpy": {"ticker": "JPY=X", "interval": "15m", "period": "60d"},
    "us10y": {"ticker": "^TNX", "interval": "1d", "period": "2y"},
}

# For longer history, use daily data
ASSETS_DAILY = {
    "dxy_daily": {"ticker": "DX-Y.NYB", "interval": "1d", "period": "2y"},
    "gold_daily": {"ticker": "GC=F", "interval": "1d", "period": "2y"},
    "wti_daily": {"ticker": "CL=F", "interval": "1d", "period": "2y"},
    "usdjpy_daily": {"ticker": "JPY=X", "interval": "1d", "period": "2y"},
}

print(f"Fetching cross-asset data to {DATA_DIR}...")

for name, cfg in {**ASSETS, **ASSETS_DAILY}.items():
    outfile = os.path.join(DATA_DIR, f"{name}.csv")
    print(f"  {name} ({cfg['ticker']})...", end=" ", flush=True)
    try:
        df = yf.download(cfg["ticker"], period=cfg["period"], interval=cfg["interval"], progress=False)
        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df.columns = df.columns.droplevel(1)
        if len(df) > 0:
            df.to_csv(outfile)
            print(f"{len(df)} rows -> {outfile}")
        else:
            print("EMPTY")
    except Exception as e:
        print(f"ERROR: {e}")
    time.sleep(1)  # rate limit

# BTC dominance from CoinGecko
print("  BTC dominance...", end=" ", flush=True)
try:
    import requests
    # Get historical BTC dominance (last 365 days)
    r = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                     params={"vs_currency": "usd", "days": "365", "interval": "daily"},
                     timeout=30)
    r.raise_for_status()
    data = r.json()
    # We need total market cap to compute dominance
    # CoinGecko doesn't directly give historical dominance, so we'll use current
    r2 = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
    btc_dom = r2.json()['data']['market_cap_percentage']['btc']
    with open(os.path.join(DATA_DIR, "btcdom_current.txt"), "w") as f:
        f.write(str(btc_dom))
    print(f"current: {btc_dom:.1f}%")
except Exception as e:
    print(f"ERROR: {e}")

print("\nDone! Data saved to:", DATA_DIR)
