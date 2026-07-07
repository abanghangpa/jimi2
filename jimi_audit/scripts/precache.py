#!/usr/bin/env python3
"""Phase 1: Pre-cache all external data for backtest period."""
import sys, os, json, time, pickle
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

CACHE_DIR = "/root/.openclaw/workspace/jimi_audit/data/backtest_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

t0 = time.time()
print("=== PHASE 1: PRE-CACHING ===")

# 1. TradFi data (DXY, 10Y, VIX, Gold, WTI, USD/JPY)
print("1. Fetching TradFi data...")
try:
    from scripts.scanner import fetch_all_tradfi_data
    tradfi = fetch_all_tradfi_data()
    with open(os.path.join(CACHE_DIR, "tradfi.pkl"), "wb") as f:
        pickle.dump(tradfi, f)
    for k, v in tradfi.items():
        bars = len(v) if v is not None else 0
        print(f"   {k}: {bars} bars")
except Exception as e:
    print(f"   ERROR: {e}")

# 2. BTC daily + ETH/BTC daily
print("2. Fetching BTC/ETH daily...")
try:
    import requests
    # BTC daily
    r = requests.get("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=200", timeout=15)
    btc_daily = r.json()
    with open(os.path.join(CACHE_DIR, "btc_daily.json"), "w") as f:
        json.dump(btc_daily, f)
    print(f"   BTC daily: {len(btc_daily)} bars")
    
    # ETH/BTC daily
    r = requests.get("https://api.binance.com/api/v3/klines?symbol=ETHBTC&interval=1d&limit=200", timeout=15)
    ethbtc_daily = r.json()
    with open(os.path.join(CACHE_DIR, "ethbtc_daily.json"), "w") as f:
        json.dump(ethbtc_daily, f)
    print(f"   ETH/BTC daily: {len(ethbtc_daily)} bars")
except Exception as e:
    print(f"   ERROR: {e}")

# 3. Macro data (NBS PMI, Caixin, etc.)
print("3. Fetching macro data...")
try:
    from src.utils.macro_fetch import fetch_nbs_pmi, fetch_caixin_pmi, fetch_china_cpi
    from src.utils.macro_fetch import fetch_adp_employment, fetch_ez_cpi, fetch_uk_wages
    from src.utils.macro_fetch import fetch_ums, fetch_china_gdp, fetch_us_pce
    from src.utils.macro_fetch import fetch_germany_cpi, fetch_uk_gdp_monthly, fetch_ism_svc_pmi
    from src.utils.macro_fetch import fetch_uk_cpi, fetch_us_durables, fetch_us_housing_starts
    from src.utils.macro_fetch import fetch_jp_cpi, fetch_rba_rate, fetch_ifo, fetch_au_cpi
    from src.utils.macro_fetch import fetch_us_gdp, fetch_us_retail_sales, fetch_nfp
    from src.utils.macro_fetch import fetch_pboc_lpr, fetch_ism_pmi, fetch_treasury_auction
    from src.utils.macro_fetch import fetch_ez_gdp, fetch_cb_consumer_confidence, fetch_jolts
    
    macro_fns = [
        fetch_nbs_pmi, fetch_caixin_pmi, fetch_china_cpi, fetch_adp_employment,
        fetch_ez_cpi, fetch_uk_wages, fetch_ums, fetch_china_gdp, fetch_us_pce,
        fetch_germany_cpi, fetch_uk_gdp_monthly, fetch_ism_svc_pmi, fetch_uk_cpi,
        fetch_us_durables, fetch_us_housing_starts, fetch_jp_cpi, fetch_rba_rate,
        fetch_ifo, fetch_au_cpi, fetch_us_gdp, fetch_us_retail_sales, fetch_nfp,
        fetch_pboc_lpr, fetch_ism_pmi, fetch_treasury_auction, fetch_ez_gdp,
        fetch_cb_consumer_confidence, fetch_jolts,
    ]
    macro_results = {}
    for fn in macro_fns:
        try:
            result = fn()
            macro_results[fn.__name__] = result
        except Exception as e:
            macro_results[fn.__name__] = {"error": str(e)}
    with open(os.path.join(CACHE_DIR, "macro.json"), "w") as f:
        json.dump(macro_results, f, default=str)
    print(f"   Fetched {len(macro_results)} macro indicators")
except Exception as e:
    print(f"   ERROR: {e}")

# 4. FRED data (claims, etc.)
print("4. Fetching FRED data...")
try:
    from scripts.scanner import _load_fred_for_cascades, _load_claims_for_cascades
    fred = _load_fred_for_cascades()
    claims = _load_claims_for_cascades()
    with open(os.path.join(CACHE_DIR, "fred.json"), "w") as f:
        json.dump({"fred": fred, "claims": claims}, f, default=str)
    print(f"   FRED: {'loaded' if fred else 'empty'} | Claims: {'loaded' if claims else 'empty'}")
except Exception as e:
    print(f"   ERROR: {e}")

# 5. BTC 15m data
print("5. Fetching BTC 15m...")
try:
    from src.utils.data_handler import fetch_btc_15m
    btc_15m = fetch_btc_15m(bars=3000)
    if btc_15m is not None:
        with open(os.path.join(CACHE_DIR, "btc_15m.pkl"), "wb") as f:
            pickle.dump(btc_15m, f)
        print(f"   BTC 15m: {len(btc_15m)} bars")
    else:
        print("   BTC 15m: None")
except Exception as e:
    print(f"   ERROR: {e}")

# 6. Exchange data (one sample)
print("6. Fetching exchange data...")
try:
    from src.modules.m16_exchange_activity import fetch_all_exchange_data
    exch = fetch_all_exchange_data()
    with open(os.path.join(CACHE_DIR, "exchange.json"), "w") as f:
        json.dump(exch, f, default=str)
    print(f"   Exchange: {len(exch)} keys")
except Exception as e:
    print(f"   ERROR: {e}")

print(f"\nPre-caching done in {time.time()-t0:.0f}s")
print(f"Cache dir: {CACHE_DIR}")
