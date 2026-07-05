#!/usr/bin/env python3
"""
STRATEGY HUNT: Find strategies that work in LOW-VOL/SIDEWAYS markets
Tested: RSI Mean Rev, Bollinger, RSI+BB, Grid, EMA Pullback, Funding Arb proxy
Data: ETH/USDT 1h, 2021-2026, 48,212 candles
50 seeds each, with and without volatility gate
"""
import json, time, random, sys, math
from datetime import datetime, timezone
from collections import defaultdict

t0 = time.time()

with open('/root/.openclaw/workspace/jimi_audit/data/eth_full_1h.json') as f:
    raw_full = json.load(f)

cutoff_ts = datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
raw = [c for c in raw_full if c[0] >= cutoff_ts]
N = len(raw)
o = [float(c[1]) for c in raw]
hi = [float(c[2]) for c in raw]
lo = [float(c[3]) for c in raw]
cl = [float(c[4]) for c in raw]
vol = [float(c[5]) for c in raw]
ts_arr = [c[0] for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(ts_arr[0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")} to {datetime.fromtimestamp(ts_arr[-1]/1000,tz=timezone.utc).strftime("%Y-%m-%d")}')
print(f'Price: ${cl[0]:.0f} -> ${cl[-1]:.0f}')

# === INDICATORS ===
print("Computing indicators...", end=" "); sys.stdout.flush()
t1 = time.time()

def ema(data, p):
    e = [0.0]*N; e[0] = data[0]; k = 2/(p+1)
    for i in range(1, N): e[i] = data[i]*k + e[i-1]*(1-k)
    return e

def sma(data, p):
    s = [None]*N
    for i in range(p-1, N): s[i] = sum(data[i-p+1:i+1])/p
    return s

def rsi(data, p=14):
    r = [None]*N
    gs = sum(max(data[i]-data[i-1],0) for i in range(1,p+1))
    ls = sum(max(data[i-1]-data[i],0) for i in range(1,p+1))
    r[p] = 100-(100/(1+gs/ls)) if ls>0 else 100
    for i in range(p+1, N):
        g = max(data[i]-data[i-1],0); l = max(data[i-1]-data[i],0)
        gs = (gs*(p-1)+g)/p; ls = (ls*(p-1)+l)/p
        r[i] = 100-(100/(1+gs/ls)) if ls>0 else 100
    return r

def bollinger(data, p=20, mult=2.0):
    mid = sma(data, p)
    upper = [None]*N; lower = [None]*N; width = [None]*N
    for i in range(p-1, N):
        seg = data[i-p+1:i+1]; m = mid[i]
        std = (sum((x-m)**2 for x in seg)/p)**0.5
        upper[i] = m + mult*std
        lower[i] = m - mult*std
        width[i] = (upper[i]-lower[i])/m*100 if m>0 else 0
    return mid, upper, lower, width

def atr(high, low, c, p=14):
    tr = [0.0]*N
    for i in range(1, N): tr[i] = max(high[i]-low[i], abs(high[i]-c[i-1]), abs(low[i]-c[i-1]))
    a = [0.0]*N; a[p] = sum(tr[1:p+1])/p
    for i in range(p+1, N): a[i] = (a[i-1]*(p-1)+tr[i])/p
    return a

def macd(data):
    ef = ema(data,12); es = ema(data,26)
    m = [ef[i]-es[i] for i in range(N)]; s = ema(m,9)
    h = [m[i]-s[i] for i in range(N)]
    return m, s, h

# Compute all indicators
ema9 = ema(cl, 9); ema21 = ema(cl, 21); ema50 = ema(cl, 50); ema200 = ema(cl, 200)
rsi14 = rsi(cl, 14); rsi7 = rsi(cl, 7)
bb_mid, bb_up, bb_lo, bb_w = bollinger(cl, 20, 2.0)
atr14 = atr(hi, lo, cl, 14)
atr_pct = [atr14[i]/cl[i]*100 if cl[i]>0 else 0 for i in range(N)]
_, _, macd_hist = macd(cl)

# Momentum
mom6 = [None]*N
for i in range(6, N):
    if cl[i-6] > 0: mom6[i] = (cl[i]-cl[i-6])/cl[i-6]
mom12 = [None]*N
for i in range(12, N):
    if cl[i-12] > 0: mom12[i] = (cl[i]-cl[i-12])/cl[i-12]

# Vol gate (48h avg abs 12h mom)
vol_gate = [None]*N
buf = []
for i in range(N):
    if mom12[i] is not None: buf.append(abs(mom12[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate[i] = sum(buf)/len(buf)

# Donchian channels (20-period)
dch = [None]*N; dcl = [None]*N
for i in range(19, N):
    dch[i] = max(hi[i-19:i+1])
    dcl[i] = min(lo[i-19:i+1])

# Stochastic
stoch_k = [None]*N
for i in range(13, N):
    hh = max(hi[i-13:i+1]); ll = min(lo[i-13:i+1])
    stoch_k[i] = (cl[i]-ll)/(hh-ll)*100 if hh!=ll else 50

# Volume SMA
vol_sma20 = sma(vol, 20)

print(f"done in {time.time()-t1:.1f}s")

# === BACKTEST ENGINE ===
def bt(sig, tp, sl, risk, lev, hold=8, gate_arr=None, gate_thresh=0, init=200, fee=0.0002, slip=0.001, cap_max=100000):
    cap = float(init); pk = cap; max_dd = 0.0; wins = 0; total = 0
    gross_p = 0.0; gross_l = 0.0; i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0: i += 1; continue
        if i+1 >= N: break
        if gate_arr is not None and gate_thresh > 0:
            g = gate_arr[i]
            if g is not None and g < gate_thresh: i += 1; continue
        if s == 1: entry = o[i+1]*(1+slip); tp_p = entry*(1+tp); sl_p = entry*(1-sl)
        else: entry = o[i+1]*(1-slip); tp_p = entry*(1-tp); sl_p = entry*(1+sl)
        sd = abs(entry-sl_p)
        if sd == 0: i += 1; continue
        sz = min(cap*risk/sd, cap*lev/entry)
        if sz <= 0: i += 1; continue
        closed = False
        for j in range(i+1, min(i+1+hold, N)):
            hit = False; ep = 0.0
            if s == 1:
                if hi[j] >= tp_p: hit = True; ep = tp_p
                elif lo[j] <= sl_p: hit = True; ep = sl_p
            else:
                if lo[j] <= tp_p: hit = True; ep = tp_p
                elif hi[j] >= sl_p: hit = True; ep = sl_p
            if hit:
                pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
                pnl -= entry*sz*fee*2
                cap += pnl; total += 1
                if pnl > 0: wins += 1; gross_p += pnl
                else: gross_l += abs(pnl)
                if cap > pk: pk = cap
                dd = (pk-cap)/pk*100 if pk>0 else 0
                if dd > max_dd: max_dd = dd
                if cap <= 0: i = N; break
                if cap > cap_max: cap = cap_max
                i = j+1; closed = True; break
        if not closed:
            j = min(i+hold, N-1); ep = cl[j]
            pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
            pnl -= entry*sz*fee*2
            cap += pnl; total += 1
            if pnl > 0: wins += 1; gross_p += pnl
            else: gross_l += abs(pnl)
            if cap > pk: pk = cap
            dd = (pk-cap)/pk*100 if pk>0 else 0
            if dd > max_dd: max_dd = dd
            if cap > cap_max: cap = cap_max
            i = j+1
    wr = wins/total*100 if total>0 else 0
    pf = gross_p/gross_l if gross_l>0 else float('inf')
    return {'cap':round(cap,2),'pk':round(pk,2),'dd':round(max_dd,1),'trades':total,'wins':wins,'wr':round(wr,1),'pf':round(pf,2)}

# === STRATEGY GENERATORS ===

def strat_rsi_mean_rev():
    """RSI < 30 LONG, RSI > 70 SHORT (mean reversion)"""
    sig = [None]*N
    for i in range(15, N):
        if rsi14[i] is not None:
            if rsi14[i] < 30: sig[i] = 1
            elif rsi14[i] > 70: sig[i] = -1
    return sig

def strat_bb_mean_rev():
    """Price < lower BB LONG, Price > upper BB SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1
            elif cl[i] > bb_up[i]: sig[i] = -1
    return sig

def strat_rsi_bb_combo():
    """RSI < 35 AND price < lower BB LONG; RSI > 65 AND price > upper BB SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if rsi14[i] is not None and bb_lo[i] is not None:
            if rsi14[i] < 35 and cl[i] < bb_lo[i]: sig[i] = 1
            elif rsi14[i] > 65 and cl[i] > bb_up[i]: sig[i] = -1
    return sig

def strat_stoch_mean_rev():
    """Stoch < 20 LONG, Stoch > 80 SHORT"""
    sig = [None]*N
    for i in range(14, N):
        if stoch_k[i] is not None:
            if stoch_k[i] < 20: sig[i] = 1
            elif stoch_k[i] > 80: sig[i] = -1
    return sig

def strat_ema_pullback():
    """Pullback to EMA21 in uptrend (price > EMA50, RSI < 45) LONG; reverse SHORT"""
    sig = [None]*N
    for i in range(50, N):
        if rsi14[i] is None or ema50[i] is None or ema21[i] is None: continue
        # Uptrend pullback
        if cl[i] > ema50[i] and abs(cl[i]-ema21[i])/cl[i] < 0.01 and rsi14[i] < 45 and macd_hist[i] > 0:
            sig[i] = 1
        # Downtrend pullback
        elif cl[i] < ema50[i] and abs(cl[i]-ema21[i])/cl[i] < 0.01 and rsi14[i] > 55 and macd_hist[i] < 0:
            sig[i] = -1
    return sig

def strat_donchian_breakout():
    """Break above 20-period high LONG, break below 20-period low SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if dch[i] is not None and dcl[i] is not None:
            if cl[i] > dch[i-1]: sig[i] = 1
            elif cl[i] < dcl[i-1]: sig[i] = -1
    return sig

def strat_rsi_trend():
    """RSI 7 crosses above 50 + price > EMA200 LONG; crosses below 50 + price < EMA200 SHORT"""
    sig = [None]*N
    for i in range(201, N):
        if rsi7[i] is None or rsi7[i-1] is None or ema200[i] is None: continue
        if rsi7[i-1] < 50 and rsi7[i] >= 50 and cl[i] > ema200[i]: sig[i] = 1
        elif rsi7[i-1] > 50 and rsi7[i] <= 50 and cl[i] < ema200[i]: sig[i] = -1
    return sig

def strat_vol_breakout():
    """Volume spike + price breakout: vol > 2x SMA20 + mom6 > 1% LONG; < -1% SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if vol_sma20[i] is None or vol_sma20[i] <= 0 or mom6[i] is None: continue
        if vol[i] > vol_sma20[i]*2:
            if mom6[i] > 0.01: sig[i] = 1
            elif mom6[i] < -0.01: sig[i] = -1
    return sig

def strat_macd_cross():
    """MACD histogram crosses zero + RSI confirmation"""
    sig = [None]*N
    for i in range(201, N):
        if macd_hist[i] is None or macd_hist[i-1] is None or rsi14[i] is None: continue
        if macd_hist[i-1] < 0 and macd_hist[i] > 0 and rsi14[i] > 40: sig[i] = 1
        elif macd_hist[i-1] > 0 and macd_hist[i] < 0 and rsi14[i] < 60: sig[i] = -1
    return sig

def strat_dual_mom():
    """Both mom6 > 1% AND mom12 > 2% LONG (strong trend); reverse SHORT"""
    sig = [None]*N
    for i in range(12, N):
        if mom6[i] is not None and mom12[i] is not None:
            if mom6[i] > 0.01 and mom12[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.01 and mom12[i] < -0.02: sig[i] = -1
    return sig

# === TEST ALL STRATEGIES ===
SEEDS = list(range(100, 150))
configs = [
    # (name, sig_func, tp, sl, risk, lev, hold, use_gate)
    ("RSI Mean Rev 14",          strat_rsi_mean_rev,    0.003, 0.002, 0.05, 20, 8, False),
    ("RSI Mean Rev 14 + Gate",   strat_rsi_mean_rev,    0.003, 0.002, 0.05, 20, 8, True),
    ("BB Mean Rev",              strat_bb_mean_rev,     0.003, 0.002, 0.05, 20, 8, False),
    ("BB Mean Rev + Gate",       strat_bb_mean_rev,     0.003, 0.002, 0.05, 20, 8, True),
    ("RSI+BB Combo",             strat_rsi_bb_combo,    0.005, 0.003, 0.05, 20, 8, False),
    ("RSI+BB Combo + Gate",      strat_rsi_bb_combo,    0.005, 0.003, 0.05, 20, 8, True),
    ("Stoch Mean Rev",           strat_stoch_mean_rev,  0.003, 0.002, 0.05, 20, 8, False),
    ("Stoch Mean Rev + Gate",    strat_stoch_mean_rev,  0.003, 0.002, 0.05, 20, 8, True),
    ("EMA Pullback",             strat_ema_pullback,    0.005, 0.003, 0.05, 20, 8, False),
    ("EMA Pullback + Gate",      strat_ema_pullback,    0.005, 0.003, 0.05, 20, 8, True),
    ("Donchian Breakout",        strat_donchian_breakout, 0.003, 0.002, 0.05, 20, 8, False),
    ("Donchian Breakout + Gate", strat_donchian_breakout, 0.003, 0.002, 0.05, 20, 8, True),
    ("RSI Trend",                strat_rsi_trend,       0.005, 0.003, 0.05, 20, 8, False),
    ("RSI Trend + Gate",         strat_rsi_trend,       0.005, 0.003, 0.05, 20, 8, True),
    ("Vol Breakout",             strat_vol_breakout,    0.005, 0.003, 0.05, 20, 8, False),
    ("Vol Breakout + Gate",      strat_vol_breakout,    0.005, 0.003, 0.05, 20, 8, True),
    ("MACD Cross",               strat_macd_cross,      0.005, 0.003, 0.05, 20, 8, False),
    ("MACD Cross + Gate",        strat_macd_cross,      0.005, 0.003, 0.05, 20, 8, True),
    ("Dual Mom",                 strat_dual_mom,        0.003, 0.002, 0.05, 20, 8, False),
    ("Dual Mom + Gate",          strat_dual_mom,        0.003, 0.002, 0.05, 20, 8, True),
    # Mom6_2pct baseline
    ("mom6_2pct (baseline)",     lambda: [None]*N,      0.002, 0.002, 0.05, 20, 8, False),  # placeholder
]

# Override mom6_2pct baseline
def strat_mom6_2pct():
    sig = [None]*N
    for i in range(6, N):
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

# Fix the baseline entry
configs[-2] = ("mom6_2pct (baseline)", strat_mom6_2pct, 0.002, 0.002, 0.05, 20, 8, False)
configs[-1] = ("mom6_2pct + Gate", strat_mom6_2pct, 0.002, 0.002, 0.05, 20, 8, True)

# Also test each strategy with optimized params
# First pass: find top 5 strategies, then sweep their params

print(f"\n{'='*90}")
print(f"STRATEGY SCREENING: 22 configs, 50 seeds each")
print(f"{'='*90}")
print(f"{'Strategy':<28} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'AvgCap':>10} {'MinCap':>10} {'MaxCap':>10} {'Surv':>5}")
print("-"*90)

all_results = []
for name, sig_func, tp, sl, risk, lev, hold, use_gate in configs:
    sig = sig_func()
    seed_results = []
    for seed in SEEDS:
        random.seed(seed)
        offset = random.randint(0, 99)
        # Apply offset
        sig_off = [None]*offset + sig[offset:]
        if len(sig_off) > N: sig_off = sig_off[:N]
        elif len(sig_off) < N: sig_off.extend([None]*(N-len(sig_off)))
        gate = vol_gate if use_gate else None
        r = bt(sig_off, tp, sl, risk, lev, hold, gate_arr=gate, gate_thresh=0.02 if use_gate else 0)
        seed_results.append(r)
    a_tr = sum(r['trades'] for r in seed_results)/len(seed_results)
    a_wr = sum(r['wr'] for r in seed_results)/len(seed_results)
    a_pf = sum(r['pf'] for r in seed_results)/len(seed_results)
    a_dd = sum(r['dd'] for r in seed_results)/len(seed_results)
    a_cap = sum(r['cap'] for r in seed_results)/len(seed_results)
    m_cap = min(r['cap'] for r in seed_results)
    x_cap = max(r['cap'] for r in seed_results)
    surv = sum(1 for r in seed_results if r['cap'] > 200)/len(seed_results)*100
    all_results.append({
        'name': name, 'trades': a_tr, 'wr': a_wr, 'pf': a_pf, 'dd': a_dd,
        'avg_cap': a_cap, 'min_cap': m_cap, 'max_cap': x_cap, 'surv': surv,
        'seed_results': seed_results, 'tp': tp, 'sl': sl, 'risk': risk, 'lev': lev
    })
    print(f"{name:<28} {a_tr:>6.0f} {a_wr:>5.1f}% {a_pf:>6.2f} {a_dd:>5.1f}% ${a_cap:>9,.0f} ${m_cap:>9,.0f} ${x_cap:>9,.0f} {surv:>4.0f}%")

# Sort by avg_cap
all_results.sort(key=lambda r: r['avg_cap'], reverse=True)

print(f"\n{'='*90}")
print(f"TOP 5 STRATEGIES (by average capital)")
print(f"{'='*90}")
for i, r in enumerate(all_results[:5]):
    print(f"\n  #{i+1}: {r['name']}")
    print(f"      WR={r['wr']:.1f}% | PF={r['pf']:.2f} | DD={r['dd']:.1f}% | AvgCap=${r['avg_cap']:,.0f} | Surv={r['surv']:.0f}%")
    print(f"      TP={r['tp']*100:.2f}% SL={r['sl']*100:.2f}% {r['lev']}x {r['risk']*100:.0f}% risk")

# Parameter sweep for top 3 strategies
print(f"\n{'='*90}")
print(f"PARAMETER SWEEP: Top 3 strategies")
print(f"{'='*90}")

top3 = all_results[:3]
for r in top3:
    name = r['name']
    # Find the sig function
    sig_func = None
    for n, sf, tp, sl, risk, lev, hold, use_gate in configs:
        if n == name:
            sig_func = sf
            use_gate_flag = use_gate
            break
    if sig_func is None: continue

    sig = sig_func()
    print(f"\n--- {name} ---")
    print(f"{'TP':>5} {'SL':>5} {'Lev':>4} {'Risk':>5} {'Hold':>5} {'AvgWR':>6} {'AvgPF':>6} {'AvgDD':>6} {'AvgCap':>10} {'MinCap':>10} {'Surv':>5}")
    print("-"*70)

    for tp in [0.002, 0.003, 0.005, 0.008, 0.01]:
        for sl in [0.002, 0.003, 0.005]:
            for lev in [20, 50]:
                for hold in [4, 8, 12]:
                    sr = []
                    for seed in SEEDS[:10]:  # 10 seeds for speed
                        random.seed(seed)
                        sig_off = [None]*random.randint(0,99) + sig
                        sig_off = sig_off[:N]
                        if len(sig_off) < N: sig_off.extend([None]*(N-len(sig_off)))
                        gate = vol_gate if use_gate_flag else None
                        sr.append(bt(sig_off, tp, sl, 0.05, lev, hold, gate_arr=gate, gate_thresh=0.02 if use_gate_flag else 0))
                    a_wr = sum(x['wr'] for x in sr)/len(sr)
                    a_pf = sum(x['pf'] for x in sr)/len(sr)
                    a_dd = sum(x['dd'] for x in sr)/len(sr)
                    a_cap = sum(x['cap'] for x in sr)/len(sr)
                    m_cap = min(x['cap'] for x in sr)
                    surv = sum(1 for x in sr if x['cap'] > 200)/len(sr)*100
                    if a_cap > 1000:  # Only show promising configs
                        print(f"{tp*100:>4.1f}% {sl*100:>4.1f}% {lev:>3}x {5:>4}% {hold:>4}h {a_wr:>5.1f}% {a_pf:>6.2f} {a_dd:>5.1f}% ${a_cap:>9,.0f} ${m_cap:>9,.0f} {surv:>4.0f}%")

# Monthly breakdown for best strategy
print(f"\n{'='*90}")
print(f"MONTHLY BREAKDOWN: Best strategy ({all_results[0]['name']})")
print(f"{'='*90}")

best = all_results[0]
# Find sig function for best
for n, sf, tp, sl, risk, lev, hold, use_gate in configs:
    if n == best['name']:
        best_sig_func = sf; best_tp = tp; best_sl = sl; best_hold = hold
        best_use_gate = use_gate; break

sig = best_sig_func()
random.seed(42)
sig_off = [None]*random.randint(0,99) + sig
sig_off = sig_off[:N]
if len(sig_off) < N: sig_off.extend([None]*(N-len(sig_off)))

monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0,'cap_start':0,'cap_end':0})
cap = 200.0; pk = cap; i = 0
while i < N:
    s = sig_off[i]
    if s is None or cap <= 1.0: i += 1; continue
    if i+1 >= N: break
    if best_use_gate and vol_gate[i] is not None and vol_gate[i] < 0.02: i += 1; continue
    mk = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc).strftime('%Y-%m')
    if monthly[mk]['cap_start'] == 0: monthly[mk]['cap_start'] = cap
    if s == 1: entry = o[i+1]*1.001; tp_p = entry*(1+best_tp); sl_p = entry*(1-best_sl)
    else: entry = o[i+1]*0.999; tp_p = entry*(1-best_tp); sl_p = entry*(1+best_sl)
    sd = abs(entry-sl_p)
    if sd == 0: i += 1; continue
    sz = min(cap*0.05/sd, cap*20/entry)
    if sz <= 0: i += 1; continue
    closed = False
    for j in range(i+1, min(i+1+best_hold, N)):
        hit = False; ep = 0
        if s == 1:
            if hi[j] >= tp_p: hit = True; ep = tp_p
            elif lo[j] <= sl_p: hit = True; ep = sl_p
        else:
            if lo[j] <= tp_p: hit = True; ep = tp_p
            elif hi[j] >= sl_p: hit = True; ep = sl_p
        if hit:
            pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
            pnl -= entry*sz*0.0002*2
            cap += pnl
            monthly[mk]['trades'] += 1; monthly[mk]['wins'] += int(pnl > 0); monthly[mk]['pnl'] += pnl
            if cap > pk: pk = cap
            if cap <= 0: i = N; break
            if cap > 100000: cap = 100000
            i = j+1; closed = True; break
    if not closed:
        j = min(i+best_hold, N-1); ep = cl[j]
        pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
        pnl -= entry*sz*0.0002*2
        cap += pnl
        monthly[mk]['trades'] += 1; monthly[mk]['wins'] += int(pnl > 0); monthly[mk]['pnl'] += pnl
        if cap > pk: pk = cap
        if cap > 100000: cap = 100000
        i = j+1
    monthly[mk]['cap_end'] = cap

print(f"{'Month':>8} {'Tr':>4} {'W':>3} {'WR%':>5} {'PnL$':>10} {'Cap':>10}")
print("-"*50)
for mk in sorted(monthly.keys()):
    m = monthly[mk]
    if m['trades'] == 0: continue
    wr = m['wins']/m['trades']*100 if m['trades']>0 else 0
    marker = " <--" if m['cap_end'] >= 2700 else ""
    print(f"{mk:>8} {m['trades']:>4} {m['wins']:>3} {wr:>5.1f}% ${m['pnl']:>9,.2f} ${m['cap_end']:>9,.2f}{marker}")

print(f"\n  Final: ${cap:,.2f} | Peak: ${pk:,.2f}")
print(f"\nCompleted in {time.time()-t0:.1f}s")
