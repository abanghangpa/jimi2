#!/usr/bin/env python3
"""Mega backtester - 50+ indicators, realistic execution with slippage + fees"""
import json, os
from datetime import datetime, timezone

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "eth_60d_1h.json")

def load():
    with open(DATA_FILE) as f: raw = json.load(f)
    return [{"o":float(c[1]),"h":float(c[2]),"l":float(c[3]),"c":float(c[4]),
             "v":float(c[5]),"dt":datetime.fromtimestamp(c[0]/1000,tz=timezone.utc)} for c in raw]

def bt(candles, sig, tp, sl, risk, lev, fee, slip, init=200):
    cap=init; pk=cap; dd=0; w=0; t=0; ot=None; r1m=None; r1m_at=None
    for i in range(1, len(candles)):
        c = candles[i]
        if not ot and cap > 1:
            s = sig(candles, i-1)
            if s:
                e = c["o"]
                e *= (1+slip) if s=="L" else (1-slip)
                if s=="L": tp2=e*(1+tp); sl2=e*(1-sl)
                else: tp2=e*(1-tp); sl2=e*(1+sl)
                sd=abs(e-sl2)
                if sd>0:
                    sz=(cap*risk)/sd; sz=min(sz,(cap*lev)/e)
                    if sz>0: ot=(s,e,sz,tp2,sl2)
        if ot:
            ht=hs=False
            if ot[0]=="L":
                if c["h"]>=ot[3]: ht=True; ep=ot[3]
                elif c["l"]<=ot[4]: hs=True; ep=ot[4]
            else:
                if c["l"]<=ot[3]: ht=True; ep=ot[3]
                elif c["h"]>=ot[4]: hs=True; ep=ot[4]
            if ht or hs:
                pnl=(ep-ot[1])*ot[2] if ot[0]=="L" else (ot[1]-ep)*ot[2]
                fc=ot[1]*ot[2]*fee*2; pnl-=fc
                cap+=pnl; t+=1; w+=int(ht)
                if cap>pk: pk=cap
                d=(pk-cap)/pk*100 if pk>0 else 0
                if d>dd: dd=d
                if cap<=0: break
                if cap>=1e6 and not r1m: r1m=True; r1m_at=c["dt"].isoformat()
                ot=None
    if ot:
        ep=candles[-1]["c"]
        pnl=(ep-ot[1])*ot[2] if ot[0]=="L" else (ot[1]-ep)*ot[2]
        fc=ot[1]*ot[2]*fee*2; pnl-=fc; cap+=pnl; t+=1; w+=int(pnl>0)
    return {"cap":round(cap,2),"t":t,"w":w,"wr":round(w/t*100,1) if t else 0,"dd":round(dd,1),"r1m":r1m is not None,"r1m_at":r1m_at}

def s_rsi(p,os_,ob):
    def f(c,i):
        if i<p+1: return None
        cl=[x["c"] for x in c[:i+1]]; g,l=[],[]
        for j in range(len(cl)-p,len(cl)): d=cl[j]-cl[j-1]; g.append(max(d,0)); l.append(max(-d,0))
        ag=sum(g)/p; al=sum(l)/p
        if al==0: return None
        rsi=100-(100/(1+ag/al))
        if rsi<os_: return "L"
        if rsi>ob: return "S"
        return None
    return f

def s_stoch_rsi(p,os_,ob):
    def f(c,i):
        if i<p*2: return None
        cl=[x["c"] for x in c[:i+1]]; g,l=[],[]
        for j in range(len(cl)-p,len(cl)): d=cl[j]-cl[j-1]; g.append(max(d,0)); l.append(max(-d,0))
        ag=sum(g)/p; al=sum(l)/p
        if al==0: rsi=100
        else: rsi=100-(100/(1+ag/al))
        rsis=[]
        for k in range(max(0,len(cl)-p*2),len(cl)):
            gg,ll=[],[]
            for m in range(max(0,k-p),k+1):
                if m>0: dd=cl[m]-cl[m-1]; gg.append(max(dd,0)); ll.append(max(-dd,0))
            aag=sum(gg)/max(len(gg),1); aal=sum(ll)/max(len(ll),1)
            if aal==0: rsis.append(100)
            else: rsis.append(100-(100/(1+aag/aal)))
        if len(rsis)<p: return None
        mn=min(rsis[-p:]); mx=max(rsis[-p:])
        if mx==mn: return None
        stoch=(rsis[-1]-mn)/(mx-mn)*100
        if stoch<os_: return "L"
        if stoch>ob: return "S"
        return None
    return f

def s_macd(fast,slow,sig_p):
    def f(c,i):
        if i<slow+sig_p: return None
        cl=[x["c"] for x in c[:i+1]]
        def ema(d,p):
            k=2/(p+1); e=d[0]
            for v in d[1:]: e=v*k+e*(1-k)
            return e
        ml=ema(cl,fast)-ema(cl,slow)
        prev_ml=ema(cl[:-1],fast)-ema(cl[:-1],slow)
        sig_vals=[ema(cl[:j+1],fast)-ema(cl[:j+1],slow) for j in range(max(0,len(cl)-sig_p),len(cl))]
        sig_line=sum(sig_vals)/len(sig_vals)
        prev_sig_vals=[ema(cl[:j+1],fast)-ema(cl[:j+1],slow) for j in range(max(0,len(cl)-sig_p-1),len(cl)-1)]
        prev_sig=sum(prev_sig_vals)/len(prev_sig_vals)
        if prev_ml<=prev_sig and ml>sig_line: return "L"
        if prev_ml>=prev_sig and ml<sig_line: return "S"
        return None
    return f

def s_bb(p,std_m):
    def f(c,i):
        if i<p: return None
        cl=[x["c"] for x in c[i-p:i]]
        mean=sum(cl)/len(cl); std=(sum((x-mean)**2 for x in cl)/len(cl))**0.5
        p_=c[i]["c"]
        if p_<mean-std_m*std: return "L"
        if p_>mean+std_m*std: return "S"
        return None
    return f

def s_cci(p,lo,hi):
    def f(c,i):
        if i<p: return None
        tp_=[(c[j]["h"]+c[j]["l"]+c[j]["c"])/3 for j in range(i-p,i)]
        mean=sum(tp_)/len(tp_)
        md=sum(abs(x-mean) for x in tp_)/len(tp_)
        if md==0: return None
        cci=(tp_[-1]-mean)/(0.015*md)
        if cci<lo: return "L"
        if cci>hi: return "S"
        return None
    return f

def s_williams_r(p,os_,ob):
    def f(c,i):
        if i<p: return None
        hh=max(c[j]["h"] for j in range(i-p,i))
        ll=min(c[j]["l"] for j in range(i-p,i))
        if hh==ll: return None
        wr=(hh-c[i]["c"])/(hh-ll)*-100
        if wr<os_: return "L"
        if wr>ob: return "S"
        return None
    return f

def s_adx(p,thr):
    def f(c,i):
        if i<p+1: return None
        plus_dm=[]; minus_dm=[]; trs=[]
        for j in range(i-p,i):
            up=c[j]["h"]-c[j-1]["h"]; dn=c[j-1]["l"]-c[j]["l"]
            plus_dm.append(up if up>dn and up>0 else 0)
            minus_dm.append(dn if dn>up and dn>0 else 0)
            tr=max(c[j]["h"]-c[j]["l"],abs(c[j]["h"]-c[j-1]["c"]),abs(c[j]["l"]-c[j-1]["c"]))
            trs.append(tr)
        atr=sum(trs)/len(trs)
        if atr==0: return None
        pdi=sum(plus_dm)/len(plus_dm)/atr*100
        mdi=sum(minus_dm)/len(minus_dm)/atr*100
        dx=abs(pdi-mdi)/(pdi+mdi)*100 if pdi+mdi>0 else 0
        if dx>thr:
            if pdi>mdi: return "L"
            if mdi>pdi: return "S"
        return None
    return f

def s_aroon(p,thr):
    def f(c,i):
        if i<p: return None
        highs=[c[j]["h"] for j in range(i-p,i)]
        lows=[c[j]["l"] for j in range(i-p,i)]
        hi_idx=highs.index(max(highs)); lo_idx=lows.index(min(lows))
        aroon_up=(p-hi_idx)/p*100; aroon_dn=(p-lo_idx)/p*100
        if aroon_up>thr and aroon_dn<thr: return "L"
        if aroon_dn>thr and aroon_up<thr: return "S"
        return None
    return f

def s_cmf(p,lo,hi):
    def f(c,i):
        if i<p: return None
        mfv_sum=0; vol_sum=0
        for j in range(i-p,i):
            hl=c[j]["h"]-c[j]["l"]
            if hl==0: continue
            mfm=((c[j]["c"]-c[j]["l"])-(c[j]["h"]-c[j]["c"]))/hl
            mfv=mfm*c[j]["v"]
            mfv_sum+=mfv; vol_sum+=c[j]["v"]
        if vol_sum==0: return None
        cmf=mfv_sum/vol_sum
        if cmf<lo: return "L"
        if cmf>hi: return "S"
        return None
    return f

def s_obv_div(p,thr):
    def f(c,i):
        if i<p: return None
        price_chg=(c[i]["c"]-c[i-p]["c"])/c[i-p]["c"]
        obv=0; obvs=[]
        for j in range(i-p,i+1):
            if j>0:
                if c[j]["c"]>c[j-1]["c"]: obv+=c[j]["v"]
                elif c[j]["c"]<c[j-1]["c"]: obv-=c[j]["v"]
            obvs.append(obv)
        if len(obvs)<r: return None
        obv_chg=(obvs[-1]-obvs[0])/abs(obvs[0]) if obvs[0]!=0 else 0
        if price_chg<-thr and obv_chg>thr: return "L"
        if price_chg>thr and obv_chg<-thr: return "S"
        return None
    return f

def s_supertrend(atr_p,mult):
    def f(c,i):
        if i<atr_p+1: return None
        trs=[]
        for j in range(i-atr_p,i):
            tr=max(c[j]["h"]-c[j]["l"],abs(c[j]["h"]-c[j-1]["c"]),abs(c[j]["l"]-c[j-1]["c"]))
            trs.append(tr)
        atr=sum(trs)/len(trs)
        hl2=(c[i]["h"]+c[i]["l"])/2
        up=hl2-mult*atr; dn=hl2+mult*atr
        if c[i]["c"]>dn: return "L"
        if c[i]["c"]<up: return "S"
        return None
    return f

def s_donchian(p):
    def f(c,i):
        if i<p: return None
        hi=max(c[j]["h"] for j in range(i-p,i)); lo=min(c[j]["l"] for j in range(i-p,i))
        p_=c[i]["c"]
        if p_>=hi: return "L"
        if p_<=lo: return "S"
        return None
    return f

def s_keltner(atr_p,mult,ema_p):
    def f(c,i):
        if i<atr_p+ema_p: return None
        cl=[x["c"] for x in c[:i+1]]
        k=2/(ema_p+1); ema_val=cl[0]
        for v in cl[1:]: ema_val=v*k+ema_val*(1-k)
        trs=[]
        for j in range(i-atr_p,i):
            tr=max(c[j]["h"]-c[j]["l"],abs(c[j]["h"]-c[j-1]["c"]),abs(c[j]["l"]-c[j-1]["c"]))
            trs.append(tr)
        atr=sum(trs)/len(trs)
        p_=c[i]["c"]
        if p_<ema_val-mult*atr: return "L"
        if p_>ema_val+mult*atr: return "S"
        return None
    return f

def s_roc(p,thr):
    def f(c,i):
        if i<p: return None
        roc=(c[i]["c"]-c[i-p]["c"])/c[i-p]["c"]
        if roc>thr: return "L"
        if roc<-thr: return "S"
        return None
    return f

def s_dmi(p,thr):
    def f(c,i):
        if i<p+1: return None
        plus_di=[]; minus_di=[]
        for j in range(i-p,i):
            up_move=c[j]["h"]-c[j-1]["h"]
            dn_move=c[j-1]["l"]-c[j]["l"]
            plus_di.append(max(up_move,0) if up_move>dn_move else 0)
            minus_di.append(max(dn_move,0) if dn_move>up_move else 0)
        pdi=sum(plus_di)/p; mdi=sum(minus_di)/p
        if pdi>thr and pdi>mdi: return "L"
        if mdi>thr and mdi>pdi: return "S"
        return None
    return f

def s_vwap_dev(p,thr):
    def f(c,i):
        if i<p: return None
        cum_tp_vol=0; cum_vol=0
        for j in range(i-p,i):
            tp_=(c[j]["h"]+c[j]["l"]+c[j]["c"])/3
            cum_tp_vol+=tp_*c[j]["v"]; cum_vol+=c[j]["v"]
        if cum_vol==0: return None
        vwap=cum_tp_vol/cum_vol
        dev=(c[i]["c"]-vwap)/vwap
        if dev<-thr: return "L"
        if dev>thr: return "S"
        return None
    return f

def s_hull(p):
    def f(c,i):
        if i<p*2: return None
        cl=[x["c"] for x in c[:i+1]]
        def wma(d,p):
            if len(d)<p: return d[-1]
            s=sum(d[-p:]); return s/p
        half=wma(cl,p//2); full=wma(cl,p)
        diff=2*half-full
        hull=wma(cl[-p:],int(p**0.5))
        prev_cl=cl[:-1]
        half_p=wma(prev_cl,p//2); full_p=wma(prev_cl,p)
        diff_p=2*half_p-full_p
        if diff_p==0: return None
        chg=(diff-diff_p)/abs(diff_p)
        if chg>0.002: return "L"
        if chg<-0.002: return "S"
        return None
    return f

def s_momentum(p,thr):
    def f(c,i):
        if i<p: return None
        chg=(c[i]["c"]-c[i-p]["c"])/c[i-p]["c"]
        if chg>thr: return "L"
        if chg<-thr: return "S"
        return None
    return f

def s_ema_cross(fast,slow):
    def f(c,i):
        if i<slow+1: return None
        cl=[x["c"] for x in c[:i+1]]
        def ema(d,p):
            k=2/(p+1); e=d[0]
            for v in d[1:]: e=v*k+e*(1-k)
            return e
        fv=ema(cl[-fast*3:],fast); sv=ema(cl[-slow*3:],slow)
        pf=ema(cl[-fast*3-1:-1],fast); ps=ema(cl[-slow*3-1:-1],slow)
        if pf<=ps and fv>sv: return "L"
        if pf>=ps and fv<sv: return "S"
        return None
    return f

def s_heikin_ashi(p):
    def f(c,i):
        if i<p+1: return None
        ha_close=(c[i]["o"]+c[i]["h"]+c[i]["l"]+c[i]["c"])/4
        ha_open=(c[i-1]["o"]+c[i-1]["c"])/2
        if ha_close>ha_open and c[i]["c"]>c[i-1]["c"]: return "L"
        if ha_close<ha_open and c[i]["c"]<c[i-1]["c"]: return "S"
        return None
    return f

def s_vol_breakout(atr_p,mult):
    def f(c,i):
        if i<atr_p+1: return None
        trs=[]
        for j in range(i-atr_p,i):
            tr=max(c[j]["h"]-c[j]["l"],abs(c[j]["h"]-c[j-1]["c"]),abs(c[j]["l"]-c[j-1]["c"]))
            trs.append(tr)
        atr=sum(trs)/len(trs)
        move=c[i]["c"]-c[i-1]["c"]
        if move>atr*mult: return "L"
        if move<-atr*mult: return "S"
        return None
    return f

def s_ichimoku(ten,kij,sen):
    def f(c,i):
        if i<sen: return None
        tenkan=(max(c[j]["h"] for j in range(i-ten,i))+min(c[j]["l"] for j in range(i-ten,i)))/2
        kijun=(max(c[j]["h"] for j in range(i-kij,i))+min(c[j]["l"] for j in range(i-kij,i)))/2
        p_=c[i]["c"]
        if p_>tenkan and p_>kijun and tenkan>kijun: return "L"
        if p_<tenkan and p_<kijun and tenkan<kijun: return "S"
        return None
    return f

def s_psar_step(step,max_step):
    def f(c,i):
        if i<5: return None
        bull=True; sar=c[i-1]["l"]; ep=c[i-1]["h"]; af=step
        for j in range(max(1,i-20),i):
            prev_sar=sar
            sar=prev_sar+af*(ep-prev_sar)
            if bull:
                if c[j]["l"]<sar: bull=False; sar=ep; ep=c[j]["l"]; af=step
                else:
                    if c[j]["h"]>ep: ep=c[j]["h"]; af=min(af+step,max_step)
            else:
                if c[j]["h"]<sar: bull=True; sar=ep; ep=c[j]["h"]; af=step
                else:
                    if c[j]["l"]<ep: ep=c[j]["l"]; af=min(af+step,max_step)
        if bull: return "L"
        if not bull: return "S"
        return None
    return f

def s_ma_envelope(p,pct):
    def f(c,i):
        if i<p: return None
        cl=[x["c"] for x in c[i-p:i]]
        mean=sum(cl)/len(cl)
        p_=c[i]["c"]
        if p_<mean*(1-pct): return "L"
        if p_>mean*(1+pct): return "S"
        return None
    return f

def s_bb_squeeze(p,std_m,atr_p):
    def f(c,i):
        if i<p+atr_p: return None
        cl=[x["c"] for x in c[i-p:i]]
        mean=sum(cl)/len(cl); std=(sum((x-mean)**2 for x in cl)/len(cl))**0.5
        trs=[]
        for j in range(i-atr_p,i):
            tr=max(c[j]["h"]-c[j]["l"],abs(c[j]["h"]-c[j-1]["c"]),abs(c[j]["l"]-c[j-1]["c"]))
            trs.append(tr)
        atr=sum(trs)/len(trs)
        bw=2*std_m*std/mean*100 if mean>0 else 0
        atr_pct=atr/mean*100 if mean>0 else 0
        p_=c[i]["c"]
        if bw<atr_pct*0.5:
            if p_>mean: return "L"
            if p_<mean: return "S"
        return None
    return f

def s_trix(p,thr):
    def f(c,i):
        if i<p*3: return None
        cl=[x["c"] for x in c[:i+1]]
        k=2/(p+1)
        e1=cl[0]; e2=e1; e3=e1
        for v in cl[1:]:
            e1=v*k+e1*(1-k); e2=e1*k+e2*(1-k); e3=e2*k+e3*(1-k)
        e1p=cl[0]; e2p=e1p; e3p=e1p
        for v in cl[:-1]:
            e1p=v*k+e1p*(1-k); e2p=e1p*k+e2p*(1-k); e3p=e2p*k+e3p*(1-k)
        if e3p==0: return None
        trix=(e3-e3p)/e3p*100
        if trix>thr: return "L"
        if trix<-thr: return "S"
        return None
    return f

def main():
    candles=load()
    print(f"Data: {len(candles)} candles, ${candles[0]['c']:.0f} -> ${candles[-1]['c']:.0f}")
    
    SLIP=0.001; FEE=0.0002
    
    sigs=[
        ("RSI7_30_70",s_rsi(7,30,70)),("RSI7_25_75",s_rsi(7,25,75)),("RSI7_20_80",s_rsi(7,20,80)),
        ("RSI14_30_70",s_rsi(14,30,70)),("RSI14_25_75",s_rsi(14,25,75)),("RSI14_20_80",s_rsi(14,20,80)),
        ("RSI21_30_70",s_rsi(21,30,70)),("RSI21_25_75",s_rsi(21,25,75)),
        ("StochRSI7_20_80",s_stoch_rsi(7,20,80)),("StochRSI14_20_80",s_stoch_rsi(14,20,80)),
        ("StochRSI7_10_90",s_stoch_rsi(7,10,90)),
        ("MACD_12_26_9",s_macd(12,26,9)),("MACD_8_21_5",s_macd(8,21,5)),
        ("BB_20_2",s_bb(20,2.0)),("BB_20_2.5",s_bb(20,2.5)),("BB_14_2",s_bb(14,2.0)),
        ("BB_Squeeze",s_bb_squeeze(20,2.0,14)),
        ("CCI_20_-100",s_cci(20,-100,100)),("CCI_14_-100",s_cci(14,-100,100)),("CCI_20_-150",s_cci(20,-150,150)),
        ("WillR_14",s_williams_r(14,-80,-20)),("WillR_21",s_williams_r(21,-80,-20)),
        ("ADX_14_25",s_adx(14,25)),("ADX_14_20",s_adx(14,20)),("ADX_21_25",s_adx(21,25)),
        ("Aroon_25_70",s_aroon(25,70)),("Aroon_14_70",s_aroon(14,70)),
        ("CMF_20",s_cmf(20,-0.1,0.1)),("CMF_14",s_cmf(14,-0.05,0.05)),
        ("OBV_Div",s_obv_div(20,0.02)),
        ("Supertrend_10_3",s_supertrend(10,3)),("Supertrend_14_2",s_supertrend(14,2)),
        ("Supertrend_7_2",s_supertrend(7,2)),
        ("Ichimoku_9_26_52",s_ichimoku(9,26,52)),
        ("Donchian_20",s_donchian(20)),("Donchian_48",s_donchian(48)),("Donchian_12",s_donchian(12)),
        ("Keltner_14_2",s_keltner(14,2,20)),("Keltner_14_1.5",s_keltner(14,1.5,20)),
        ("ROC_12_2%",s_roc(12,0.02)),("ROC_24_3%",s_roc(24,0.03)),
        ("TRIX_15",s_trix(15,0.01)),("TRIX_21",s_trix(21,0.005)),
        ("DMI_14",s_dmi(14,0.3)),("DMI_21",s_dmi(21,0.3)),
        ("VWAP_20",s_vwap_dev(20,0.02)),("VWAP_48",s_vwap_dev(48,0.03)),
        ("Hull_16",s_hull(16)),("Hull_21",s_hull(21)),
        ("Mom_12_3%",s_momentum(12,0.03)),("Mom_24_4%",s_momentum(24,0.04)),
        ("EMA_9_21",s_ema_cross(9,21)),("EMA_5_34",s_ema_cross(5,34)),
        ("MA_Env_20",s_ma_envelope(20,0.02)),("MA_Env_48",s_ma_envelope(48,0.03)),
        ("HeikinAshi",s_heikin_ashi(3)),
        ("VolBreak_7_1.5",s_vol_breakout(7,1.5)),("VolBreak_14_2",s_vol_breakout(14,2)),
        ("PSAR",s_psar_step(0.02,0.2)),
    ]
    
    configs=[]
    for risk in [0.05,0.10,0.15,0.20]:
        for lev in [10,20,30,50]:
            for tp,sl in [(0.005,0.003),(0.005,0.0025),(0.008,0.004),(0.01,0.005),(0.01,0.004),
                          (0.015,0.008),(0.015,0.007),(0.02,0.01),(0.02,0.008),
                          (0.03,0.015),(0.03,0.01),(0.05,0.02),(0.05,0.025)]:
                configs.append((tp,sl,risk,lev))
    
    results=[]
    print(f"Testing {len(sigs)} signals x {len(configs)} configs = {len(sigs)*len(configs)} backtests...")
    
    for name,sig in sigs:
        for tp,sl,risk,lev in configs:
            try:
                r=bt(candles,sig,tp,sl,risk,lev,FEE,SLIP)
                r["sig"]=name;r["tp"]=tp;r["sl"]=sl;r["risk"]=risk;r["lev"]=lev
                results.append(r)
            except: pass
    
    results.sort(key=lambda r:r["cap"],reverse=True)
    m=[r for r in results if r["r1m"]]
    
    print(f"\nReached $1M: {len(m)} / {len(results)}")
    print(f"\n{'#':<4} {'Signal':<18} {'Cap':>14} {'x':>8} {'T':>5} {'WR':>6} {'DD':>6} {'1M':>3} {'Risk':>5} {'Lev':>4} {'TP%':>7} {'SL%':>7}")
    print("="*110)
    for i,r in enumerate(results[:50]):
        x=r["cap"]/200
        print(f"{i+1:<4} {r['sig']:<18} ${r['cap']:>12,.0f} {x:>7.1f}x {r['t']:>5} {r['wr']:>5.1f}% {r['dd']:>5.1f}% {'Y' if r['r1m'] else 'N':>3} {r['risk']*100:>4.0f}% {r['lev']:>3}x {r['tp']*100:>6.2f}% {r['sl']*100:>6.2f}%")
    
    if m:
        print(f"\n*** {len(m)} hit $1M! ***")
        seen=set()
        for r in m[:30]:
            k=f"{r['sig']}_{r['tp']}_{r['sl']}_{r['lev']}"
            if k not in seen:
                seen.add(k)
                print(f"  {r['sig']:<18} risk={r['risk']*100:.0f}% lev={r['lev']}x tp={r['tp']*100:.2f}% sl={r['sl']*100:.2f}% -> ${r['cap']:,.0f} | {r['t']}T {r['wr']:.0f}%WR DD:{r['dd']:.0f}%")
    else:
        print(f"\nNo $1M. Top 10:")
        seen=set()
        for r in results[:15]:
            k=f"{r['sig']}_{r['tp']}_{r['sl']}_{r['lev']}"
            if k not in seen:
                seen.add(k)
                print(f"  {r['sig']:<18} risk={r['risk']*100:.0f}% lev={r['lev']}x tp={r['tp']*100:.2f}% sl={r['sl']*100:.2f}% -> ${r['cap']:,.0f} ({r['cap']/200:.1f}x)")

if __name__=="__main__": main()
