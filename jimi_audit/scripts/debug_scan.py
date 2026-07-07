#!/usr/bin/env python3
"""Debug: check what scan_signal returns."""
import sys, os, json, pickle, pandas as pd
sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

import requests
class M:
    def __init__(self,d=None): self._d=d or []; self.status_code=200
    def json(self): return self._d
    def raise_for_status(self): pass

with open("data/backtest_cache/tradfi.pkl","rb") as f: TRADFI=pickle.load(f)
with open("data/backtest_cache/btc_daily.json") as f: BTC=json.load(f)
with open("data/backtest_cache/ethbtc_daily.json") as f: ETHBTC=json.load(f)
with open("data/backtest_cache/exchange.json") as f: EXCH=json.load(f)

def mg(u,**k):
    if "BTCUSDT" in u and "1d" in u: return M(BTC)
    if "ETHBTC" in u and "1d" in u: return M(ETHBTC)
    if "ticker/price" in u: return M({"price":"0"})
    return M([])
requests.get=mg

import yfinance; yfinance.Ticker=lambda *a,**k: type("T",(),{"history":lambda s,**kw: pd.DataFrame()})()
import src.modules.m16_exchange_activity as ex; ex.fetch_all_exchange_data=lambda: EXCH; ex.get_exchange_summary=lambda *a,**k: {}
import src.modules.intrabar_cvd as ic; ic.get_intrabar_cvd_summary=lambda *a,**k: (None,{})
import src.utils.macro_fetch as mf
for a in dir(mf):
    if a.startswith("fetch_"): setattr(mf,a,lambda *a,**k: None)
import src.utils.order_flow as of
of.fetch_multi_exchange_ob=lambda *a,**k: {}; of.fetch_recent_trades=lambda *a,**k: []
of.fetch_liquidations=lambda *a,**k: {}; of.fetch_funding_rates=lambda *a,**k: {}
import scripts.scanner as sm; sm.fetch_all_tradfi_data=lambda **k: TRADFI

# Suppress prints
import builtins
_bp=builtins.print
_skip=["Fetching","fetch","📡","📊","⚠️","[DEBUG]","[SPOOF]","1m bars","intrabar","TradFi","BTC/USDT","ETH/BTC","macro_cache","claims_cache","FRED","DXY:","10Y:","VIX:","WTI:","Gold:","USD/JPY:","M20","Signal","confirmed","expired","pending","BTC data","DXY fetch","10Y fetch","VIX fetch","WTI fetch","Gold fetch","USD/JPY","yfinance","nbs","caixin","claims","pce","ifo","gdp","ism","jolts","adp","nfp","pboc","treasury","retail","housing","durables","wages","consumer","rba","china","uk","germany","japan","eurozone","australia","michigan","cpi",">> ",".. "]
def _fp(*a,**kw):
    m=str(a[0]) if a else ""
    if any(x in m for x in _skip): return
    _bp(*a,**kw)
builtins.print=_fp

from src.utils.data_handler import load_data
from src.config import CONFIG
from scripts.scanner import scan_signal, compute_indicators

df=load_data("eth_15m_merged.csv")
df["Open time"]=pd.to_datetime(df["Open time"])
df26=df[df["Open time"]>="2026-01-01"].copy().reset_index(drop=True)
cfg=CONFIG
d15,d1h,d2h,d4h,d1d=compute_indicators(df26.copy(),config=cfg)

builtins.print=_bp

# Test scan at a few different points
for test_idx in [1000, 2000, 3000, 3500]:
    ts=d15["Open time"].iloc[test_idx]
    ds=d15.iloc[:test_idx+1].copy()
    d1h_s=d1h[d1h["Open time"]<=ts].copy()
    d2h_s=d2h[d2h["Open time"]<=ts].copy()
    d4h_s=d4h[d4h["Open time"]<=ts].copy()
    d1d_s=d1d[d1d["Open time"]<=ts].copy()
    
    try:
        res=scan_signal(ds,d1h_s,d2h_s,d4h_s,d1d_s,config=cfg)
        print(f"\n=== IDX {test_idx} ===")
        print(f"Keys: {list(res.keys())[:25]}")
        ms=res.get("multi_strategy",{})
        print(f"multi_strategy type: {type(ms)}")
        if isinstance(ms,dict):
            print(f"  total_strategies: {ms.get('total_strategies')}")
            print(f"  signals_fired: {ms.get('signals_fired')}")
            all_sigs=ms.get("all_signals",[])
            print(f"  all_signals count: {len(all_sigs)}")
            for s in all_sigs[:3]:
                print(f"    -> {s.get('strategy')}: {s.get('direction')} conv={s.get('conviction')}")
        ss=res.get("strategy_signal",{})
        print(f"strategy_signal: {ss}")
        print(f"direction: {res.get('direction')}")
        print(f"ics: {res.get('ics')}")
    except Exception as e:
        print(f"ERROR at {test_idx}: {e}")

print("\nDone.")
