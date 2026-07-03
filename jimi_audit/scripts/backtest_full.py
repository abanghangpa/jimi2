#!/usr/bin/env python3
"""Fast backtester on full ETH history (2017-2026). Pre-computed indicators."""
import json
from datetime import datetime, timezone

with open('data/eth_full_1h.json') as f: raw = json.load(f)
N = len(raw)
o = [float(c[1]) for c in raw]
h = [float(c[2]) for c in raw]
l = [float(c[3]) for c in raw]
cl = [float(c[4]) for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(raw[0][0]/1000,tz=timezone.utc)} to {datetime.fromtimestamp(raw[-1][0]/1000,tz=timezone.utc)}')
print(f'Price: ${cl[0]:.0f} -> ${cl[-1]:.0f}, range ${min(l):.0f} - ${max(h):.0f}')

def pre_rsi(closes, p):
    r = [None]*len(closes)
    gs = sum(max(closes[i]-closes[i-1],0) for i in range(1,p+1))
    ls = sum(max(closes[i-1]-closes[i],0) for i in range(1,p+1))
    r[p] = 100-(100/(1+gs/ls)) if ls>0 else 100
    for i in range(p+1, len(closes)):
        g = max(closes[i]-closes[i-1],0); l = max(closes[i-1]-closes[i],0)
        gs = (gs*(p-1)+g)/p; ls = (ls*(p-1)+l)/p
        r[i] = 100-(100/(1+gs/ls)) if ls>0 else 100
    return r

def pre_ema(closes, p):
    e = [0.0]*len(closes); e[0] = closes[0]; k = 2/(p+1)
    for i in range(1, len(closes)): e[i] = closes[i]*k + e[i-1]*(1-k)
    return e

print("Pre-computing indicators...")
r7 = pre_rsi(cl, 7); r14 = pre_rsi(cl, 14); r21 = pre_rsi(cl, 21)
e9 = pre_ema(cl, 9); e21 = pre_ema(cl, 21); e34 = pre_ema(cl, 34)
print("Done.\n")

def bt(sig, tp, sl, risk, lev, fee=0.0002, slip=0.001, init=200, hold=8):
    cap = init; pk = cap; dd = 0; w = 0; t = 0; r1m = False; i = 0
    while i < N:
        s = sig[i] if i < len(sig) else None
        if s is None or cap <= 1: i += 1; continue
        if i+1 >= N: break
        e = o[i+1]*(1+slip) if s==1 else o[i+1]*(1-slip)
        if s==1: tp2=e*(1+tp); sl2=e*(1-sl)
        else: tp2=e*(1-tp); sl2=e*(1+sl)
        sd = abs(e-sl2)
        if sd == 0: i += 1; continue
        sz = (cap*risk)/sd; sz = min(sz, (cap*lev)/e)
        if sz <= 0: i += 1; continue
        closed = False
        for j in range(i+1, min(i+1+hold, N)):
            ht = hs = False
            if s==1:
                if h[j]>=tp2: ht=True; ep=tp2
                elif l[j]<=sl2: hs=True; ep=sl2
            else:
                if l[j]<=tp2: ht=True; ep=tp2
                elif h[j]>=sl2: hs=True; ep=sl2
            if ht or hs:
                pnl = (ep-e)*sz if s==1 else (e-ep)*sz
                pnl -= e*sz*fee*2; cap += pnl; t += 1; w += int(ht)
                if cap>pk: pk=cap
                d = (pk-cap)/pk*100 if pk>0 else 0
                if d>dd: dd=d
                if cap>=1e6 and not r1m: r1m=True
                if cap<=0: i=N; break
                i = j+1; closed = True; break
        if not closed:
            j = min(i+hold, N-1); ep = cl[j]
            pnl = (ep-e)*sz if s==1 else (e-ep)*sz
            pnl -= e*sz*fee*2; cap += pnl; t += 1; w += int(pnl>0)
            if cap>pk: pk=cap
            d = (pk-cap)/pk*100 if pk>0 else 0
            if d>dd: dd=d
            if cap>=1e6 and not r1m: r1m=True
            if cap<=0: break
            i = j+1
    return {'cap':round(cap,2),'t':t,'w':w,'wr':round(w/t*100,1) if t else 0,'dd':round(dd,1),'r1m':r1m}

def mk_rsi(arr, os_, ob):
    return [1 if v is not None and v<os_ else (-1 if v is not None and v>ob else None) for v in arr]

def mk_ema_cross(fa, sa):
    s = [None]*N
    for i in range(1,N):
        if fa[i-1]<=sa[i-1] and fa[i]>sa[i]: s[i]=1
        elif fa[i-1]>=sa[i-1] and fa[i]<sa[i]: s[i]=-1
    return s

def mk_mom(closes, lb, thr):
    s = [None]*N
    for i in range(lb, N):
        chg = (closes[i]-closes[i-lb])/closes[i-lb]
        if chg>thr: s[i]=1
        elif chg<-thr: s[i]=-1
    return s

def mk_bb(closes, p, std_m):
    s = [None]*N
    for i in range(p, N):
        seg = closes[i-p:i]; mean=sum(seg)/len(seg)
        std = (sum((x-mean)**2 for x in seg)/len(seg))**0.5
        if closes[i] < mean-std_m*std: s[i]=1
        elif closes[i] > mean+std_m*std: s[i]=-1
    return s

def mk_brk(closes, highs, lows, lb):
    s = [None]*N
    for i in range(lb, N):
        hi = max(highs[i-lb:i]); lo = min(lows[i-lb:i])
        if closes[i]>hi: s[i]=1
        elif closes[i]<lo: s[i]=-1
    return s

print("Building signal arrays...")
sig_list = [
    ("RSI7_30_70", mk_rsi(r7, 30, 70)),
    ("RSI7_25_75", mk_rsi(r7, 25, 75)),
    ("RSI7_20_80", mk_rsi(r7, 20, 80)),
    ("RSI14_30_70", mk_rsi(r14, 30, 70)),
    ("RSI14_25_75", mk_rsi(r14, 25, 75)),
    ("RSI14_20_80", mk_rsi(r14, 20, 80)),
    ("RSI21_30_70", mk_rsi(r21, 30, 70)),
    ("EMA_9_21", mk_ema_cross(e9, e21)),
    ("EMA_9_34", mk_ema_cross(e9, e34)),
    ("Mom12_2pct", mk_mom(cl, 12, 0.02)),
    ("Mom12_3pct", mk_mom(cl, 12, 0.03)),
    ("Mom24_3pct", mk_mom(cl, 24, 0.03)),
    ("Mom24_5pct", mk_mom(cl, 24, 0.05)),
    ("BB20_2", mk_bb(cl, 20, 2.0)),
    ("BB20_2.5", mk_bb(cl, 20, 2.5)),
    ("Brk24", mk_brk(cl, h, l, 24)),
    ("Brk48", mk_brk(cl, h, l, 48)),
]
print(f'{len(sig_list)} signal arrays ready.')

configs = []
for risk in [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    for lev in [10, 20, 30, 50]:
        for tp, sl in [(0.003,0.002), (0.005,0.003), (0.005,0.0025),
                       (0.008,0.004), (0.01,0.005), (0.02,0.01),
                       (0.03,0.015), (0.05,0.025), (0.05,0.02)]:
            for hold in [4, 8, 12, 24]:
                configs.append((tp, sl, risk, lev, hold))

total = len(sig_list) * len(configs)
print(f'{len(sig_list)} signals x {len(configs)} configs = {total} backtests...\n')

results = []
for name, sig in sig_list:
    for tp, sl, risk, lev, hold in configs:
        r = bt(sig, tp, sl, risk, lev, hold=hold)
        r['sig']=name; r['tp']=tp; r['sl']=sl; r['risk']=risk; r['lev']=lev; r['hold']=hold
        results.append(r)

results.sort(key=lambda r: r['cap'], reverse=True)
m = [r for r in results if r['r1m']]

print(f'Reached $1M: {len(m)} / {len(results)}')
print(f'\n{"#":<4} {"Signal":<15} {"Cap":>14} {"x":>10} {"T":>6} {"WR":>6} {"DD":>6} {"1M":>3} {"Risk":>5} {"Lev":>4} {"Hold":>5} {"TP%":>6} {"SL%":>6}')
print('='*110)
for i, r in enumerate(results[:40]):
    x = r['cap']/200
    print(f'{i+1:<4} {r["sig"]:<15} ${r["cap"]:>12,.0f} {x:>9.1f}x {r["t"]:>6} {r["wr"]:>5.1f}% {r["dd"]:>5.1f}% {"Y" if r["r1m"] else "N":>3} {r["risk"]*100:>4.0f}% {r["lev"]:>3}x {r["hold"]:>4}h {r["tp"]*100:>5.2f}% {r["sl"]*100:>5.2f}%')

if m:
    print(f'\n*** {len(m)} hit $1M! ***')
    seen = set()
    for r in m[:25]:
        k = f'{r["sig"]}_{r["tp"]}_{r["sl"]}_{r["lev"]}_{r["hold"]}'
        if k not in seen:
            seen.add(k)
            print(f'  {r["sig"]:<15} risk={r["risk"]*100:.0f}% lev={r["lev"]}x hold={r["hold"]}h tp={r["tp"]*100:.2f}% sl={r["sl"]*100:.2f}% -> ${r["cap"]:,.0f} ({r["cap"]/200:.0f}x) | {r["t"]}T {r["wr"]:.0f}%WR DD:{r["dd"]:.0f}%')
else:
    print(f'\nNo $1M. Best 10:')
    seen = set()
    for r in results[:15]:
        k = f'{r["sig"]}_{r["tp"]}_{r["sl"]}'
        if k not in seen:
            seen.add(k)
            print(f'  {r["sig"]:<15} risk={r["risk"]*100:.0f}% lev={r["lev"]}x hold={r["hold"]}h tp={r["tp"]*100:.2f}% sl={r["sl"]*100:.2f}% -> ${r["cap"]:,.0f} ({r["cap"]/200:.1f}x) | {r["t"]}T {r["wr"]:.0f}%WR DD:{r["dd"]:.0f}%')
