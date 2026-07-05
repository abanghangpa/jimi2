#!/usr/bin/env python3
"""
Mega Backtest v2: Pure Momentum vs Hybrid (50+ indicators, 10 seeds, optimized sweep)
ETH/USDT 1h data, Aug 2017 - Jul 2026 (77,686 candles)
Optimized: fewer param combos, vectorized where possible
"""
import json, time, random, sys
from datetime import datetime, timezone

t0 = time.time()
random.seed(42)

with open('/root/.openclaw/workspace/jimi_audit/data/eth_full_1h.json') as f:
    raw = json.load(f)
N = len(raw)
o = [float(c[1]) for c in raw]
h = [float(c[2]) for c in raw]
l = [float(c[3]) for c in raw]
cl = [float(c[4]) for c in raw]
vol = [float(c[5]) for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(raw[0][0]/1000,tz=timezone.utc)} to {datetime.fromtimestamp(raw[-1][0]/1000,tz=timezone.utc)}')
print(f'Price: ${cl[0]:.0f} -> ${cl[-1]:.0f}, range ${min(l):.0f} - ${max(h):.0f}')

# ============================================================
# INDICATOR PRE-COMPUTATION
# ============================================================
def pre_ema(c, p):
    e=[0.0]*N; e[0]=c[0]; k=2/(p+1)
    for i in range(1,N): e[i]=c[i]*k+e[i-1]*(1-k)
    return e

def pre_sma(a, p):
    s=[None]*N
    for i in range(p-1,N): s[i]=sum(a[i-p+1:i+1])/p
    return s

def pre_rsi(c, p):
    r=[None]*N
    gs=sum(max(c[i]-c[i-1],0) for i in range(1,p+1))
    ls=sum(max(c[i-1]-c[i],0) for i in range(1,p+1))
    r[p]=100-(100/(1+gs/ls)) if ls>0 else 100
    for i in range(p+1,N):
        g=max(c[i]-c[i-1],0); lo=max(c[i-1]-c[i],0)
        gs=(gs*(p-1)+g)/p; ls=(ls*(p-1)+lo)/p
        r[i]=100-(100/(1+gs/ls)) if ls>0 else 100
    return r

def pre_macd(c, f=12, s=26, sg=9):
    ef=pre_ema(c,f); es=pre_ema(c,s)
    m=[ef[i]-es[i] for i in range(N)]; sig=pre_ema(m,sg)
    hist=[m[i]-sig[i] for i in range(N)]
    return m, sig, hist

def pre_bb(c, p=20, sm=2.0):
    mid=pre_sma(c,p); w=[None]*N
    for i in range(p-1,N):
        seg=c[i-p+1:i+1]; m=mid[i]
        std=(sum((x-m)**2 for x in seg)/p)**0.5
        w[i]=(2*sm*std)/m*100 if m>0 else 0
    return mid, w

def pre_atr(hi, lo, c, p=14):
    tr=[0.0]*N
    for i in range(1,N): tr[i]=max(hi[i]-lo[i],abs(hi[i]-c[i-1]),abs(lo[i]-c[i-1]))
    a=[0.0]*N; a[p]=sum(tr[1:p+1])/p
    for i in range(p+1,N): a[i]=(a[i-1]*(p-1)+tr[i])/p
    ap=[a[i]/c[i]*100 if c[i]>0 else 0 for i in range(N)]
    return a, ap

def pre_adx(hi, lo, c, p=14):
    pdm=[0.0]*N; mdm=[0.0]*N; tr=[0.0]*N
    for i in range(1,N):
        up=hi[i]-hi[i-1]; dn=lo[i-1]-lo[i]
        pdm[i]=up if up>dn and up>0 else 0
        mdm[i]=dn if dn>up and dn>0 else 0
        tr[i]=max(hi[i]-lo[i],abs(hi[i]-c[i-1]),abs(lo[i]-c[i-1]))
    atr=[0.0]*N; pds=[0.0]*N; mds=[0.0]*N
    atr[p]=sum(tr[1:p+1]); pds[p]=sum(pdm[1:p+1]); mds[p]=sum(mdm[1:p+1])
    for i in range(p+1,N):
        atr[i]=atr[i-1]-atr[i-1]/p+tr[i]
        pds[i]=pds[i-1]-pds[i-1]/p+pdm[i]
        mds[i]=mds[i-1]-mds[i-1]/p+mdm[i]
    pdi=[0.0]*N; mdi=[0.0]*N; dx=[0.0]*N; adx=[0.0]*N
    for i in range(p,N):
        pdi[i]=(pds[i]/atr[i]*100) if atr[i]>0 else 0
        mdi[i]=(mds[i]/atr[i]*100) if atr[i]>0 else 0
        dx[i]=abs(pdi[i]-mdi[i])/(pdi[i]+mdi[i])*100 if (pdi[i]+mdi[i])>0 else 0
    for i in range(p+p,N): adx[i]=(adx[i-1]*(p-1)+dx[i])/p if i>p+p else sum(dx[p+1:i+1])/(i-p)
    return pdi, mdi, adx

def pre_cci(hi, lo, c, p=20):
    tp=[(hi[i]+lo[i]+c[i])/3 for i in range(N)]; cci=[None]*N
    for i in range(p-1,N):
        seg=tp[i-p+1:i+1]; m=sum(seg)/p; md=sum(abs(x-m) for x in seg)/p
        cci[i]=(tp[i]-m)/(0.015*md) if md>0 else 0
    return cci

def pre_stoch(hi, lo, c, p=14):
    sk=[None]*N
    for i in range(p-1,N):
        hh=max(hi[i-p+1:i+1]); ll=min(lo[i-p+1:i+1])
        sk[i]=(c[i]-ll)/(hh-ll)*100 if hh!=ll else 50
    return sk

def pre_mfi(hi, lo, c, v, p=14):
    tp=[(hi[i]+lo[i]+c[i])/3 for i in range(N)]
    mf=[tp[i]*v[i] for i in range(N)]
    pmf=[0.0]*N; nmf=[0.0]*N; mfi=[None]*N
    for i in range(1,N):
        pmf[i]=mf[i] if tp[i]>tp[i-1] else 0
        nmf[i]=mf[i] if tp[i]<tp[i-1] else 0
    for i in range(p,N):
        ps=sum(pmf[i-p+1:i+1]); ns=sum(nmf[i-p+1:i+1])
        mfi[i]=100-100/(1+ps/ns) if ns>0 else 100
    return mfi

def pre_obv(c, v):
    obv=[0.0]*N
    for i in range(1,N):
        if c[i]>c[i-1]: obv[i]=obv[i-1]+v[i]
        elif c[i]<c[i-1]: obv[i]=obv[i-1]-v[i]
        else: obv[i]=obv[i-1]
    return obv

def pre_supertrend(hi, lo, c, p=10, mult=3.0):
    atr_arr,_=pre_atr(hi,lo,c,p)
    st=[0.0]*N; d=[0]*N
    for i in range(p,N):
        mid=(hi[i]+lo[i])/2; up=mid+mult*atr_arr[i]; dn=mid-mult*atr_arr[i]
        if i>p:
            if c[i]>st[i-1]: st[i]=dn; d[i]=1
            elif c[i]<st[i-1]: st[i]=up; d[i]=-1
            else: st[i]=st[i-1]; d[i]=d[i-1]
        else: st[i]=up; d[i]=-1
    return st, d

def pre_donchian(hi, lo, p=20):
    dch=[None]*N; dcl=[None]*N
    for i in range(p-1,N): dch[i]=max(hi[i-p+1:i+1]); dcl[i]=min(lo[i-p+1:i+1])
    return dch, dcl

def pre_trix(c, p=15):
    e1=pre_ema(c,p); e2=pre_ema(e1,p); e3=pre_ema(e2,p)
    t=[None]*N
    for i in range(1,N):
        if e3[i-1]>0: t[i]=(e3[i]-e3[i-1])/e3[i-1]*10000
    return t

print("Computing indicators...", end=" "); sys.stdout.flush()
ind={}
ind['ema9']=pre_ema(cl,9); ind['ema21']=pre_ema(cl,21); ind['ema34']=pre_ema(cl,34)
ind['ema50']=pre_ema(cl,50); ind['ema100']=pre_ema(cl,100); ind['ema200']=pre_ema(cl,200)
ind['sma20']=pre_sma(cl,20); ind['sma50']=pre_sma(cl,50)
ind['rsi7']=pre_rsi(cl,7); ind['rsi14']=pre_rsi(cl,14); ind['rsi21']=pre_rsi(cl,21)
macd,macd_sig,macd_hist=pre_macd(cl); ind['macd']=macd; ind['macd_sig']=macd_sig; ind['macd_hist']=macd_hist
bb_mid,bb_w=pre_bb(cl); ind['bb_w']=bb_w
atr,atr_pct=pre_atr(h,cl,cl); ind['atr']=atr; ind['atr_pct']=atr_pct
pdi,mdi,adx=pre_adx(h,l,cl); ind['pdi']=pdi; ind['mdi']=mdi; ind['adx']=adx
ind['cci']=pre_cci(h,l,cl); ind['stoch']=pre_stoch(h,l,cl)
ind['mfi']=pre_mfi(h,l,cl,vol); ind['obv']=pre_obv(cl,vol)
st_trend,st_dir=pre_supertrend(h,l,cl); ind['st_dir']=st_dir
dch,dcl=pre_donchian(h,l); ind['dch']=dch; ind['dcl']=dcl
ind['trix']=pre_trix(cl)
for lb in [3,6,12,24,48,72]:
    mom=[None]*N
    for i in range(lb,N):
        if cl[i-lb]>0: mom[i]=(cl[i]-cl[i-lb])/cl[i-lb]
    ind[f'mom{lb}']=mom
ind['vol_sma20']=pre_sma(vol,20)
print(f'{len(ind)} arrays in {time.time()-t0:.1f}s')

# ============================================================
# SIGNAL GENERATORS
# ============================================================
SEEDS = [random.randint(0,99999) for _ in range(10)]

def gen_pure_momentum(offset=0):
    sig=[None]*N; mom=ind['mom12']
    for i in range(12+offset,N):
        if mom[i] is not None:
            if mom[i]>0.03: sig[i]=1
            elif mom[i]<-0.03: sig[i]=-1
    return sig

def gen_hybrid(offset=0):
    sig=[None]*N
    for i in range(max(200,offset),N):
        score=0
        rsi=ind['rsi14'][i]
        if rsi is not None:
            if rsi<30: score+=1
            elif rsi>70: score-=1
        mh=ind['macd_hist'][i]
        if mh is not None:
            if mh>0: score+=1
            elif mh<0: score-=1
        if ind['ema9'][i] and ind['ema21'][i]:
            if ind['ema9'][i]>ind['ema21'][i]: score+=1
            else: score-=1
        if ind['ema200'][i]:
            if cl[i]>ind['ema200'][i]: score+=1
            else: score-=1
        if ind['adx'][i] is not None and ind['adx'][i]>25:
            if ind['pdi'][i]>ind['mdi'][i]: score+=1
            else: score-=1
        sk=ind['stoch'][i]
        if sk is not None:
            if sk<20: score+=0.5
            elif sk>80: score-=0.5
        cci=ind['cci'][i]
        if cci is not None:
            if cci<-100: score+=0.5
            elif cci>100: score-=0.5
        if ind['st_dir'][i]: score+=ind['st_dir'][i]
        if ind['vol_sma20'][i] and ind['vol_sma20'][i]>0:
            if vol[i]>ind['vol_sma20'][i]*1.5: score+=0.5*(1 if score>0 else -1)
        direction=None
        if score>=2: direction=1
        elif score<=-2: direction=-1
        mom=ind['mom12'][i]
        if direction is not None and mom is not None:
            if direction==1 and mom>0.01: sig[i]=1
            elif direction==-1 and mom<-0.01: sig[i]=-1
        elif direction is not None:
            sig[i]=direction
    return sig

# ============================================================
# BACKTEST ENGINE (optimized)
# ============================================================
def bt(sig, tp, sl, risk, lev, hold=8, atr_filter=0, init=200, fee=0.0002, slip=0.001):
    cap=init; pk=cap; dd=0; w=0; t=0; i=0; td=0
    while i<N:
        s=sig[i] if i<N else None
        if s is None or cap<=1: i+=1; continue
        if i+1>=N: break
        if atr_filter>0:
            ap=atr_pct[i]
            if ap is not None and ap<atr_filter: i+=1; continue
        e=o[i+1]*(1+slip) if s==1 else o[i+1]*(1-slip)
        if s==1: tp2=e*(1+tp); sl2=e*(1-sl)
        else: tp2=e*(1-tp); sl2=e*(1+sl)
        sd=abs(e-sl2)
        if sd==0: i+=1; continue
        sz=(cap*risk)/sd; sz=min(sz,(cap*lev)/e)
        if sz<=0: i+=1; continue
        closed=False
        for j in range(i+1,min(i+1+hold,N)):
            ht=hs=False
            if s==1:
                if h[j]>=tp2: ht=True; ep=tp2
                elif l[j]<=sl2: hs=True; ep=sl2
            else:
                if l[j]<=tp2: ht=True; ep=tp2
                elif h[j]>=sl2: hs=True; ep=sl2
            if ht or hs:
                pnl=(ep-e)*sz if s==1 else (e-ep)*sz
                pnl-=e*sz*fee*2; cap+=pnl; t+=1; w+=int(ht); td+=j-i
                if cap>pk: pk=cap
                d=(pk-cap)/pk*100 if pk>0 else 0
                if d>dd: dd=d
                if cap<=0: i=N; break
                i=j+1; closed=True; break
        if not closed:
            j=min(i+hold,N-1); ep=cl[j]
            pnl=(ep-e)*sz if s==1 else (e-ep)*sz
            pnl-=e*sz*fee*2; cap+=pnl; t+=1; w+=int(pnl>0); td+=j-i
            if cap>pk: pk=cap
            d=(pk-cap)/pk*100 if pk>0 else 0
            if d>dd: dd=d
            if cap<=0: break
            i=j+1
    losses=t-w
    pf=w/losses if losses>0 and w>0 else (999 if w>0 and losses==0 else 0)
    return {'cap':round(cap,2),'t':t,'w':w,'wr':round(w/t*100,1) if t else 0,
            'dd':round(dd,1),'pf':round(pf,2),'avg_dur':round(td/t,1) if t else 0}

# ============================================================
# PARAMETER SWEEP (focused)
# ============================================================
# Use representative subset: 9 TP x 9 SL x 4 hold x 4 lev = 1296 combos
TP_VALS=[0.002,0.003,0.005,0.008,0.01,0.015,0.02,0.03,0.05]
SL_VALS=[0.002,0.003,0.005,0.008,0.01,0.015,0.02,0.03,0.05]
HOLD_VALS=[4,8,12,24]
LEV_VALS=[10,20,30,50]
ATR_FILTERS=[0,0.008,0.01,0.012,0.015]
RISK=0.05

configs=[(tp,sl,h,lv) for tp in TP_VALS for sl in SL_VALS for h in HOLD_VALS for lv in LEV_VALS]
print(f'Sweep: {len(configs)} params x 2 strats x 10 seeds x {len(ATR_FILTERS)} ATR = {len(configs)*2*10*len(ATR_FILTERS):,} runs')
sys.stdout.flush()

strategies={'pure_momentum':gen_pure_momentum,'hybrid':gen_hybrid}
all_results={}

for sname,gfn in strategies.items():
    print(f'\n{"="*60}\nStrategy: {sname}\n{"="*60}'); sys.stdout.flush()
    sr=[]
    for si,seed in enumerate(SEEDS):
        sig=gfn(offset=seed%100)
        sc=sum(1 for s in sig if s is not None)
        print(f'  Seed {si+1}/10 (off={seed%100}): {sc:,} signals',end=''); sys.stdout.flush()
        t1=time.time()
        for af in ATR_FILTERS:
            for tp,sl,hl,lv in configs:
                r=bt(sig,tp,sl,RISK,lv,hold=hl,atr_filter=af)
                r['tp']=tp; r['sl']=sl; r['hold']=hl; r['lev']=lv
                r['atr_f']=af; r['seed']=seed; r['strat']=sname
                sr.append(r)
        print(f' [{time.time()-t1:.0f}s]'); sys.stdout.flush()
    all_results[sname]=sr

# ============================================================
# ANALYSIS
# ============================================================
print('\n'+'='*70)
print('MEGA BACKTEST RESULTS — 2017-2026 ETH/USDT 1H')
print('='*70)

for sname in strategies:
    results=all_results[sname]
    valid=[r for r in results if r['t']>=10]
    if not valid: print(f'\n{sname}: No valid results'); continue
    
    by_pf=sorted(valid,key=lambda x:x['pf'],reverse=True)
    by_pnl=sorted(valid,key=lambda x:x['cap'],reverse=True)
    by_wr=sorted(valid,key=lambda x:x['wr'],reverse=True)
    
    print(f'\n{"="*70}')
    print(f'STRATEGY: {sname.upper()}')
    print(f'Valid configs: {len(valid):,} / {len(results):,}')
    print(f'{"="*70}')
    
    print(f'\n--- TOP 10 by Profit Factor ---')
    print(f'{"#":<3} {"TP":<7} {"SL":<7} {"H":<4} {"Lv":<4} {"ATR":<6} {"WR%":<6} {"PF":<6} {"PnL$":<10} {"Tr":<6} {"DD%":<6} {"Dur":<5}')
    for i,r in enumerate(by_pf[:10]):
        print(f'{i+1:<3} {r["tp"]*100:.2f}%  {r["sl"]*100:.2f}%  {r["hold"]:<4} {r["lev"]:<4} {r["atr_f"]*100:.1f}%  {r["wr"]:<6} {r["pf"]:<6} ${r["cap"]-200:>+8.0f}  {r["t"]:<6} {r["dd"]:<6} {r["avg_dur"]:.0f}h')
    
    print(f'\n--- TOP 10 by Total PnL ---')
    print(f'{"#":<3} {"TP":<7} {"SL":<7} {"H":<4} {"Lv":<4} {"ATR":<6} {"WR%":<6} {"PF":<6} {"PnL$":<10} {"Tr":<6} {"DD%":<6}')
    for i,r in enumerate(by_pnl[:10]):
        print(f'{i+1:<3} {r["tp"]*100:.2f}%  {r["sl"]*100:.2f}%  {r["hold"]:<4} {r["lev"]:<4} {r["atr_f"]*100:.1f}%  {r["wr"]:<6} {r["pf"]:<6} ${r["cap"]-200:>+8.0f}  {r["t"]:<6} {r["dd"]:<6}')
    
    print(f'\n--- TOP 10 by Win Rate (min 20 trades) ---')
    by_wr20=[r for r in by_wr if r['t']>=20]
    for i,r in enumerate(by_wr20[:10]):
        print(f'{i+1}. TP={r["tp"]*100:.2f}% SL={r["sl"]*100:.2f}% H={r["hold"]}h Lv={r["lev"]}x ATR={r["atr_f"]*100:.1f}% | WR={r["wr"]}% PF={r["pf"]} PnL=${r["cap"]-200:+.0f} Tr={r["t"]}')
    
    print(f'\n--- ATR Filter Impact ---')
    for af in ATR_FILTERS:
        sub=[r for r in valid if r['atr_f']==af]
        if sub:
            aw=sum(r['wr'] for r in sub)/len(sub)
            ap=sum(r['pf'] for r in sub)/len(sub)
            bp=max(r['pf'] for r in sub)
            print(f'  ATR>={af*100:.1f}%: avg WR={aw:.1f}% avg PF={ap:.2f} best PF={bp:.2f} (n={len(sub)})')

print(f'\n{"="*70}')
print('HEAD-TO-HEAD')
print(f'{"="*70}')
for sname in strategies:
    valid=[r for r in all_results[sname] if r['t']>=10]
    if not valid: continue
    best=max(valid,key=lambda x:x['pf'])
    aw=sum(r['wr'] for r in valid)/len(valid)
    ap=sum(r['pf'] for r in valid)/len(valid)
    mpnl=sorted([r['cap']-200 for r in valid])[len(valid)//2]
    print(f'\n{sname}:')
    print(f'  Best PF: {best["pf"]:.2f} (TP={best["tp"]*100:.2f}% SL={best["sl"]*100:.2f}% H={best["hold"]}h Lv={best["lev"]}x ATR={best["atr_f"]*100:.1f}%)')
    print(f'  Best WR: {max(r["wr"] for r in valid):.1f}%  Best PnL: ${max(r["cap"]-200 for r in valid):+.0f}')
    print(f'  Avg WR: {aw:.1f}% | Avg PF: {ap:.2f} | Median PnL: ${mpnl:+.0f}')
    ldd=min(valid,key=lambda x:x['dd'])
    print(f'  Lowest DD: {ldd["dd"]:.1f}% (PF={ldd["pf"]:.2f})')

print(f'\n{"="*70}')
print('CURRENT PAPER TRADER (TP=0.30% SL=0.20% H=8h Lv=20x)')
print(f'{"="*70}')
for sname,gfn in strategies.items():
    sig=gfn(offset=0)
    for af in ATR_FILTERS:
        r=bt(sig,0.003,0.002,0.05,20,hold=8,atr_filter=af)
        lb=f'ATR>={af*100:.1f}%' if af>0 else 'No ATR'
        print(f'  {sname} ({lb}): WR={r["wr"]}% PF={r["pf"]} PnL=${r["cap"]-200:+.2f} Tr={r["t"]} DD={r["dd"]}%')

elapsed=time.time()-t0
print(f'\nCompleted in {elapsed:.0f}s ({elapsed/60:.1f}min)')
