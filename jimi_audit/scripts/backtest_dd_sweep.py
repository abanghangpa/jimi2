#!/usr/bin/env python3
"""DD Cooldown Sweep — test different cooldown periods."""
import json, random
from datetime import datetime, timezone, timedelta
import os

BASE = "/root/.openclaw/workspace/jimi_audit"
DATA_FILE = os.path.join(BASE, "data", "eth_full_1h.json")

INITIAL_CAPITAL = 200.0
RISK_PCT = 0.05
LEVERAGE = 20
TP_PCT = 0.003
SL_PCT = 0.002
HOLD_HOURS = 8
MOM_PERIOD = 12
MOM_THRESHOLD = 0.03
FEE_RATE = 0.0002
BASE_SLIPPAGE = 0.001
DD_STOP = 0.50
MIN_PHASE0 = 0.15
MAX_POSITION_USD = 50000
MAX_CAPITAL = 1_000_000
SEED = 777

def load_data():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    return [{'ts':c[0],'o':float(c[1]),'h':float(c[2]),'l':float(c[3]),'c':float(c[4]),'v':float(c[5]) if len(c)>5 else 0} for c in raw]

def ema(c,p):
    e=[0.0]*len(c); e[0]=c[0]; k=2/(p+1)
    for i in range(1,len(c)): e[i]=c[i]*k+e[i-1]*(1-k)
    return e

def rsi(c,p):
    r=[None]*len(c)
    if len(c)<p+1: return r
    gs=sum(max(c[i]-c[i-1],0) for i in range(1,p+1))
    ls=sum(max(c[i-1]-c[i],0) for i in range(1,p+1))
    r[p]=100-(100/(1+gs/ls)) if ls>0 else 100
    for i in range(p+1,len(c)):
        g=max(c[i]-c[i-1],0); l=max(c[i-1]-c[i],0)
        gs=(gs*(p-1)+g)/p; ls=(ls*(p-1)+l)/p
        r[i]=100-(100/(1+gs/ls)) if ls>0 else 100
    return r

def atr(h,l,c,p=14):
    a=[None]*len(c)
    if len(c)<p+1: return a
    ts=sum(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,p+1))
    a[p]=ts/p
    for i in range(p+1,len(c)):
        tr=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
        a[i]=(a[i-1]*(p-1)+tr)/p
    return a

def compute(candles):
    c=[x['c'] for x in candles]; h=[x['h'] for x in candles]; l=[x['l'] for x in candles]
    v=[x['v'] for x in candles]
    e9,e21,e50,e200=ema(c,9),ema(c,21),ema(c,50),ema(c,200)
    r14=rsi(c,14); a14=atr(h,l,c,14)
    vm=[None]*len(v)
    for i in range(19,len(v)): vm[i]=sum(v[i-19:i+1])/20
    return e9,e21,e50,e200,r14,a14,vm

def signal(i,ca,e9,e21,e50,e200,r14,a14,vm):
    if i<200 or e200[i] is None or r14[i] is None: return None
    c=ca[i]['c']
    eb=e9[i]>e21[i]>e50[i]; ea=e9[i]<e21[i]<e50[i]
    a2=c>e200[i]; b2=c<e200[i]; rv=r14[i]
    vr=ca[i]['v']/vm[i] if vm[i] and vm[i]>0 else 0
    sw='N'
    if i>=20:
        rh=max(ca[j]['h'] for j in range(i-20,i)); rl=min(ca[j]['l'] for j in range(i-20,i))
        if c>rh*0.998: sw='B'
        elif c<rl*1.002: sw='S'
    if eb: p0=sum(1 for j in range(max(0,i-20),i) if ca[j]['c']>e21[j] and e21[j] is not None)/20
    elif ea: p0=sum(1 for j in range(max(0,i-20),i) if ca[j]['c']<e21[j] and e21[j] is not None)/20
    else: p0=0.3
    bs=0; ss=0
    if eb: bs+=2
    elif ea: ss+=2
    if a2: bs+=1
    elif b2: ss+=1
    if rv>50: bs+=1
    elif rv<50: ss+=1
    if sw=='B': bs+=1
    elif sw=='S': ss+=1
    if vr>1:
        if bs>ss: bs+=1
        elif ss>bs: ss+=1
    if bs>=4 and p0>=MIN_PHASE0: return 'LONG'
    if ss>=4 and p0>=MIN_PHASE0: return 'SHORT'
    return None

def momentum(i,ca):
    if i<MOM_PERIOD+1: return None,0
    cur=ca[i]['c']; past=ca[i-MOM_PERIOD]['c']
    if past==0: return None,0
    m=(cur-past)/past
    if m>MOM_THRESHOLD: return 'LONG',m
    if m<-MOM_THRESHOLD: return 'SHORT',m
    return None,m

def slippage(usd,base):
    if usd<=10000: return base
    if usd<=50000: return base*1.5
    return base*2.0

def run(ca, cd_hours, si):
    e9,e21,e50,e200,r14,a14,vm=compute(ca)
    cap=INITIAL_CAPITAL; pk=cap; pos=None; po=None; cd_until=None; ddt=0; trades=[]; eq=[]
    i=si
    N=len(ca)
    while i<N:
        c=ca[i]; dt=datetime.fromtimestamp(c['ts']/1000,tz=timezone.utc)
        if cap>MAX_CAPITAL: cap=MAX_CAPITAL
        if cap>pk: pk=cap
        if cd_until and dt<cd_until: eq.append(cap); i+=1; continue
        elif cd_until: cd_until=None
        dd=(pk-cap)/pk if pk>0 else 0
        if dd>=DD_STOP:
            cd_until=dt+timedelta(hours=cd_hours); ddt+=1; eq.append(cap); i+=1; continue
        if po and pos is None:
            sl=slippage(cap*LEVERAGE,BASE_SLIPPAGE)
            ep=c['c']*(1+sl) if po=='LONG' else c['c']*(1-sl)
            if po=='LONG': tp=ep*(1+TP_PCT); sl2=ep*(1-SL_PCT)
            else: tp=ep*(1-TP_PCT); sl2=ep*(1+SL_PCT)
            sd=abs(ep-sl2)
            if sd>0:
                ra=cap*RISK_PCT; sz=ra/sd
                ms=min((cap*LEVERAGE)/ep,MAX_POSITION_USD/ep)
                sz=min(sz,ms)
                if sz>0: pos={'d':po,'e':ep,'tp':tp,'sl':sl2,'sz':sz,'o':dt,'ci':cap}
            po=None
        if pos:
            p=pos; out=None; xp=None
            if p['d']=='LONG':
                if c['h']>=p['tp']: out='W'; xp=p['tp']
                elif c['l']<=p['sl']: out='L'; xp=p['sl']
            else:
                if c['l']<=p['tp']: out='W'; xp=p['tp']
                elif c['h']>=p['sl']: out='L'; xp=p['sl']
            if out is None:
                if dt-p['o']>=timedelta(hours=HOLD_HOURS):
                    xp=c['c']
                    out='W' if (p['d']=='LONG' and xp>p['e']) or (p['d']=='SHORT' and xp<p['e']) else 'L'
            if out:
                if p['d']=='LONG': pnl=(xp-p['e'])*p['sz']
                else: pnl=(p['e']-xp)*p['sz']
                pnl-=p['e']*p['sz']*FEE_RATE*2; cap+=pnl
                trades.append({'pnl':pnl,'o':out}); pos=None
        if pos is None and po is None:
            sd=signal(i,ca,e9,e21,e50,e200,r14,a14,vm)
            md,mv=momentum(i,ca)
            sig=None
            if sd in('LONG','SHORT'):
                if md==sd: sig=sd
                elif md is None: sig=sd
            elif md and abs(mv)>0.05: sig=md
            if sig: po=sig
        eq.append(cap); i+=1
    mx=0; pk2=0
    for e in eq:
        if e>pk2: pk2=e
        d=(pk2-e)/pk2*100 if pk2>0 else 0
        if d>mx: mx=d
    gw=sum(t['pnl'] for t in trades if t['pnl']>0)
    gl=abs(sum(t['pnl'] for t in trades if t['pnl']<0))
    return {'cap':round(cap,2),'x':round(cap/INITIAL_CAPITAL,2),'t':len(trades),
            'w':sum(1 for t in trades if t['o']=='W'),
            'wr':round(sum(1 for t in trades if t['o']=='W')/len(trades)*100,1) if trades else 0,
            'dd':round(mx,1),'ddt':ddt,'pf':round(gw/gl,2) if gl>0 else 999}

def main():
    ca=load_data()
    si=None
    for idx,c in enumerate(ca):
        dt=datetime.fromtimestamp(c['ts']/1000,tz=timezone.utc)
        if dt.year==2018 and dt.month==11 and dt.day>=12: si=idx; break
    if si is None: si=4000
    
    cooldowns=[0,1,2,4,6,8,12,16,24,48,72,168]
    print(f"{'Cooldown':>10} | {'Final Capital':>14} | {'Return':>8} | {'Trades':>6} | {'WR':>6} | {'MaxDD':>6} | {'DD Hits':>7} | {'PF':>6}")
    print("="*85)
    best=None
    for cd in cooldowns:
        r=run(ca,cd,si)
        label=f"{cd}h" if cd>0 else "None"
        print(f"{label:>10} | ${r['cap']:>12,.2f} | {r['x']:>7.2f}x | {r['t']:>6} | {r['wr']:>5.1f}% | {r['dd']:>5.1f}% | {r['ddt']:>7} | {r['pf']:>6}")
        if best is None or r['cap']>best['cap']: best={'cd':cd,'r':r}
    
    print(f"\n{'='*85}")
    print(f"Best: {best['cd']}h cooldown → ${best['r']['cap']:,.2f} ({best['r']['x']}x)")

if __name__=='__main__':
    main()
