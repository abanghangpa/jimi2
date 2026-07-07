#!/usr/bin/env python3
"""Fast backtest v3: Uses main pipeline signals when strategy signals unavailable."""
import sys, os, json, time, pickle
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

t0 = time.time()

print("Loading 2026 data...")
from src.utils.data_handler import load_data
df_all = load_data("eth_15m_merged.csv")
df_all['Open time'] = pd.to_datetime(df_all['Open time'])
df_2026 = df_all[df_all['Open time'] >= '2026-01-01'].copy().reset_index(drop=True)
print(f"  2026 bars: {len(df_2026)}")

# Patch API calls
import requests
class MockR:
    def __init__(self, d=None): self._d = d or []; self.status_code = 200
    def json(self): return self._d
    def raise_for_status(self): pass

with open("data/backtest_cache/tradfi.pkl","rb") as f: TRADFI = pickle.load(f)
with open("data/backtest_cache/btc_daily.json") as f: BTC_D = json.load(f)
with open("data/backtest_cache/ethbtc_daily.json") as f: ETHBTC_D = json.load(f)
with open("data/backtest_cache/exchange.json") as f: EXCH = json.load(f)

def _mget(url, **kw):
    if "BTCUSDT" in url and "1d" in url: return MockR(BTC_D)
    if "ETHBTC" in url and "1d" in url: return MockR(ETHBTC_D)
    if "ticker/price" in url: return MockR({"price":"0"})
    return MockR([])
requests.get = _mget

import yfinance; yfinance.Ticker = lambda *a,**k: type("T",(),{"history":lambda s,**kw: pd.DataFrame()})()
import src.modules.m16_exchange_activity as ex; ex.fetch_all_exchange_data = lambda: EXCH; ex.get_exchange_summary = lambda *a,**k: {}
import src.modules.intrabar_cvd as ic; ic.get_intrabar_cvd_summary = lambda *a,**k: (None,{})
import src.utils.macro_fetch as mf
for a in dir(mf):
    if a.startswith("fetch_"): setattr(mf, a, lambda *a,**k: None)
import src.utils.order_flow as of
of.fetch_multi_exchange_ob = lambda *a,**k: {}; of.fetch_recent_trades = lambda *a,**k: []
of.fetch_liquidations = lambda *a,**k: {}; of.fetch_funding_rates = lambda *a,**k: {}
import scripts.scanner as sm; sm.fetch_all_tradfi_data = lambda **k: TRADFI

# Suppress prints
import builtins
_bp = builtins.print
_skip = ["Fetching","fetch","📡","📊","⚠️","[DEBUG]","[SPOOF]","1m bars","intrabar","TradFi",
    "BTC/USDT","ETH/BTC","macro_cache","claims_cache","FRED","DXY:","10Y:","VIX:","WTI:","Gold:",
    "USD/JPY:","M20","Signal","confirmed","expired","pending","BTC data","DXY fetch","10Y fetch",
    "VIX fetch","WTI fetch","Gold fetch","USD/JPY","yfinance","nbs","caixin","claims","pce","ifo",
    "gdp","ism","jolts","adp","nfp","pboc","treasury","retail","housing","durables","wages",
    "consumer","rba","china","uk","germany","japan","eurozone","australia","michigan","cpi",">> ",".. "]
def _fp(*a,**kw):
    m = str(a[0]) if a else ""
    if any(x in m for x in _skip): return
    _bp(*a,**kw)
builtins.print = _fp

from src.config import CONFIG
from scripts.scanner import scan_signal, compute_indicators

print("Computing indicators...")
cfg = CONFIG
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_2026.copy(), config=cfg)
builtins.print = _bp
print(f"  Indicators done in {time.time()-t0:.0f}s")

START = "2026-05-13"; END = "2026-06-06"
mask = (df_15m['Open time'] >= START) & (df_15m['Open time'] <= END)
idxs = df_15m[mask].index.tolist()
si = max(idxs[0], 500); ei = idxs[-1]
print(f"  Period: {df_15m['Open time'].iloc[si]} to {df_15m['Open time'].iloc[ei]} ({ei-si+1} bars)")

INIT = 200.0; LEV = 25; RISK = 0.10; FEE = 0.001; STEP = 8
trades = []; cap = INIT; peak = INIT; mdd = 0; ops = []; sigs = 0; scans = 0; errs = 0

builtins.print = _fp
print("Running backtest...")
builtins.print = _bp

for i in range(si, ei+1, STEP):
    if time.time()-t0 > 570:
        print(f"TIMEOUT bar {i}"); break
    if (i-si) % 500 == 0:
        p = (i-si)/(ei-si)*100; e = time.time()-t0
        print(f"  {p:.0f}% | bar {i} | trades={len(trades)} | cap=${cap:.2f} | sigs={sigs} | {e:.0f}s")
    
    r = df_15m.iloc[i]; ts = r['Open time']; px = float(r['Close'])
    hi = float(r['High']); lo = float(r['Low'])
    
    cl = []
    for p in ops:
        bh = i-p['ei']; mb = p['hh']*4
        if p['d'] == 'LONG':
            if hi >= p['tp']:
                pnl = p['sz']*(p['tp']-p['e'])/p['e']-p['f']; cap += pnl
                trades.append({**p,'x':p['tp'],'pnl':pnl,'o':'WIN','bh':bh}); cl.append(p)
            elif lo <= p['sl']:
                pnl = p['sz']*(p['sl']-p['e'])/p['e']-p['f']; cap += pnl
                trades.append({**p,'x':p['sl'],'pnl':pnl,'o':'LOSS','bh':bh}); cl.append(p)
            elif bh >= mb:
                pnl = p['sz']*(px-p['e'])/p['e']-p['f']; cap += pnl
                trades.append({**p,'x':px,'pnl':pnl,'o':'WIN' if pnl>0 else 'LOSS','bh':bh}); cl.append(p)
        else:
            if lo <= p['tp']:
                pnl = p['sz']*(p['e']-p['tp'])/p['e']-p['f']; cap += pnl
                trades.append({**p,'x':p['tp'],'pnl':pnl,'o':'WIN','bh':bh}); cl.append(p)
            elif hi >= p['sl']:
                pnl = p['sz']*(p['e']-p['sl'])/p['e']-p['f']; cap += pnl
                trades.append({**p,'x':p['sl'],'pnl':pnl,'o':'LOSS','bh':bh}); cl.append(p)
            elif bh >= mb:
                pnl = p['sz']*(p['e']-px)/p['e']-p['f']; cap += pnl
                trades.append({**p,'x':px,'pnl':pnl,'o':'WIN' if pnl>0 else 'LOSS','bh':bh}); cl.append(p)
    for x in cl: ops.remove(x)
    
    if cap > peak: peak = cap
    dd = (peak-cap)/peak*100 if peak>0 else 0
    if dd > mdd: mdd = dd
    if len(ops) >= 3 or cap <= 0: continue
    
    ds = df_15m.iloc[:i+1].copy()
    d1h = df_1h[df_1h['Open time'] <= ts].copy()
    d2h = df_2h[df_2h['Open time'] <= ts].copy()
    d4h = df_4h[df_4h['Open time'] <= ts].copy()
    d1d = df_1d[df_1d['Open time'] <= ts].copy()
    if len(d1h) < 20 or len(d1d) < 2: continue
    
    try:
        res = scan_signal(ds, d1h, d2h, d4h, d1d, config=cfg); scans += 1
    except: errs += 1; continue
    if not res: continue
    
    # CRITICAL: Run strategy runner (strategies are NOT called by scan_signal)
    try:
        from src.strategies import create_runner as create_strategy_runner
        _sr = create_strategy_runner(config=cfg)
        _sr_result = _sr.summary(res, df_15m=ds, idx=len(ds)-1)
        res['multi_strategy'] = _sr_result
    except Exception:
        pass
    
    # Check main pipeline signal
    status = res.get('status', '')
    source = res.get('source', '')
    
    if status == 'SIGNAL' and source in ('main_pipeline', 'm20_direct'):
        sigs += 1
        direction = res.get('direction', 'LONG')
        entry = float(res.get('market_entry', px))
        sl = float(res.get('sl', entry * 0.99))
        tp = float(res.get('tp1', entry * 1.03))
        
        # Use a default strategy name based on source
        strat = 'main_pipeline'
        
        # Check no duplicate
        if any(x['sn'] == strat for x in ops): continue
        
        sl_dist = abs(entry - sl)
        if sl_dist == 0: continue
        sz = min(cap*RISK/sl_dist, cap*LEV/entry)
        if sz <= 0: continue
        f = sz*entry*FEE
        ops.append({
            'sn': strat, 'd': direction, 'e': round(entry,2),
            'tp': round(tp,2), 'sl': round(sl,2),
            'sz': round(sz,6), 'f': f, 'hh': 8,
            'ei': i, 'cv': 0.7, 'ts': str(ts),
        })
        continue
    
    # Also check multi_strategy signals
    ms = res.get('multi_strategy', {})
    if isinstance(ms, dict):
        for s in ms.get('all_signals', []):
            if not isinstance(s, dict): continue
            sn = s.get('strategy', '')
            d = s.get('direction'); cv = s.get('conviction', 0)
            if not d: continue
            if any(x['sn'] == sn for x in ops): continue
            sigs += 1
            tp_p = 2.0/100; sl_p = 1.5/100
            if d == 'LONG':
                e = px*1.001; t = e*(1+tp_p); sl_p2 = e*(1-sl_p)
            else:
                e = px*0.999; t = e*(1-sl_p); sl_p2 = e*(1+tp_p)
            sd = abs(e-sl_p2)
            if sd == 0: continue
            sz = min(cap*RISK/sd, cap*LEV/e)
            if sz <= 0: continue
            f = sz*e*FEE
            ops.append({
                'sn': sn, 'd': d, 'e': round(e,2), 'tp': round(t,2), 'sl': round(sl_p2,2),
                'sz': round(sz,6), 'f': f, 'hh': 8, 'ei': i, 'cv': cv, 'ts': str(ts),
            })
            break

# Close remaining
for p in ops:
    px = float(df_15m['Close'].iloc[ei])
    if p['d'] == 'LONG': pnl = p['sz']*(px-p['e'])/p['e']-p['f']
    else: pnl = p['sz']*(p['e']-px)/p['e']-p['f']
    cap += pnl
    trades.append({**p, 'x': px, 'pnl': pnl, 'o': 'WIN' if pnl>0 else 'LOSS', 'bh': ei-p['ei']})

elapsed = time.time()-t0

print(f"\n{'='*80}")
print(f"BACKTEST: {START} to {END}")
print(f"{'='*80}")
print(f"Scanner calls: {scans} | Signals: {sigs} | Errors: {errs}")
print(f"Capital: ${INIT:.2f} -> ${cap:.2f} ({(cap-INIT)/INIT*100:+.1f}%)")
nt = len(trades); nw = len([t for t in trades if t['o']=='WIN']); nl = nt-nw
if nt > 0:
    print(f"Trades: {nt} | W: {nw} | L: {nl} | WR: {nw/nt*100:.1f}%")
else:
    print(f"Trades: 0")
gp = sum(t['pnl'] for t in trades if t['pnl']>0)
gl = abs(sum(t['pnl'] for t in trades if t['pnl']<0))
pf = gp/gl if gl>0 else float('inf')
print(f"PF: {pf:.2f} | MaxDD: {mdd:.1f}% | Fees: ${sum(t.get('f',0) for t in trades):.2f}")
print(f"Time: {elapsed:.0f}s")

if trades:
    print(f"\nPER-STRATEGY:")
    ss = defaultdict(lambda: {'n':0,'w':0,'pnl':0})
    for t in trades:
        ss[t['sn']]['n'] += 1; ss[t['sn']]['pnl'] += t['pnl']
        if t['o'] == 'WIN': ss[t['sn']]['w'] += 1
    for s, v in sorted(ss.items(), key=lambda x: x[1]['pnl'], reverse=True):
        ws = v['w']/v['n']*100 if v['n']>0 else 0
        gp2 = sum(t['pnl'] for t in trades if t['sn']==s and t['pnl']>0)
        gl2 = abs(sum(t['pnl'] for t in trades if t['sn']==s and t['pnl']<0))
        pf2 = gp2/gl2 if gl2>0 else float('inf')
        tag = "PASS" if pf2>=2.0 and ws>=70 else "FAIL"
        print(f"  [{tag}] {s:25s} n={v['n']:4d} WR={ws:5.1f}% PF={pf2:5.2f} PnL=${v['pnl']:+8.2f}")

    print(f"\nMONTHLY:")
    ml = defaultdict(lambda: {'n':0,'w':0,'pnl':0})
    for t in trades:
        m = t['ts'][:7]; ml[m]['n'] += 1; ml[m]['pnl'] += t['pnl']
        if t['o'] == 'WIN': ml[m]['w'] += 1
    for m in sorted(ml):
        v = ml[m]; wm = v['w']/v['n']*100 if v['n']>0 else 0
        print(f"  {m} n={v['n']:4d} WR={wm:5.1f}% PnL=${v['pnl']:+8.2f}")

# Save trades
with open("data/backtest_trades.json", "w") as f:
    json.dump(trades, f, indent=2, default=str)
print(f"\nTrades saved to data/backtest_trades.json")
print("Done.")
