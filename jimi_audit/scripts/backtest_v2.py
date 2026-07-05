#!/usr/bin/env python3
"""Targeted Backtester - Find $200 -> $1M with aggressive compounding"""
import json, os
from datetime import datetime, timezone

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "eth_60d_1h.json")

def load():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    return [{"h": float(c[2]), "l": float(c[3]), "c": float(c[4]),
             "dt": datetime.fromtimestamp(c[0]/1000, tz=timezone.utc)} for c in raw]

def bt(candles, sig, tp, sl, risk, lev, init=200):
    cap = init; pk = cap; dd = 0; w = 0; t = 0; ot = None; r1m = None
    for i in range(1, len(candles)):
        c = candles[i]
        if ot:
            ht = hs = False
            if ot[0] == "L":
                if c["h"] >= ot[3]: ht = True; ep = ot[3]
                elif c["l"] <= ot[4]: hs = True; ep = ot[4]
            else:
                if c["l"] <= ot[3]: ht = True; ep = ot[3]
                elif c["h"] >= ot[4]: hs = True; ep = ot[4]
            if ht or hs:
                pnl = (ep-ot[1])*ot[2] if ot[0]=="L" else (ot[1]-ep)*ot[2]
                cap += pnl; t += 1; w += int(ht)
                if cap > pk: pk = cap
                d = (pk-cap)/pk*100 if pk>0 else 0
                if d > dd: dd = d
                if cap <= 0: break
                if cap >= 1e6 and not r1m: r1m = c["dt"].isoformat()
                ot = None
        if not ot and cap > 1:
            s = sig(candles, i)
            if s:
                e = c["c"]
                if s == "L": tp2 = e*(1+tp); sl2 = e*(1-sl)
                else: tp2 = e*(1-tp); sl2 = e*(1+sl)
                sd = abs(e-sl2)
                if sd > 0:
                    sz = (cap*risk)/sd; sz = min(sz, (cap*lev)/e)
                    if sz > 0: ot = (s, e, sz, tp2, sl2)
    if ot:
        ep = candles[-1]["c"]
        pnl = (ep-ot[1])*ot[2] if ot[0]=="L" else (ot[1]-ep)*ot[2]
        cap += pnl; t += 1; w += int(pnl>0)
    return {"cap": round(cap,2), "t": t, "w": w, "wr": round(w/t*100,1) if t else 0,
            "dd": round(dd,1), "r1m": r1m is not None, "r1m_at": r1m}

# Signals
def s_rsi(p, os_=30, ob=70):
    def f(c, i):
        if i < p+1: return None
        cl = [x["c"] for x in c[:i+1]]
        g,l = [],[]
        for j in range(len(cl)-p, len(cl)):
            d = cl[j]-cl[j-1]; g.append(max(d,0)); l.append(max(-d,0))
        ag=sum(g)/p; al=sum(l)/p
        if al==0: return None
        rsi = 100-(100/(1+ag/al))
        if rsi < os_: return "L"
        if rsi > ob: return "S"
        return None
    return f

def s_mom(lb, thr):
    def f(c, i):
        if i < lb: return None
        chg = (c[i]["c"]-c[i-lb]["c"])/c[i-lb]["c"]
        if chg > thr: return "L"
        if chg < -thr: return "S"
        return None
    return f

def s_ema(fast, slow):
    def f(c, i):
        if i < slow+1: return None
        cl = [x["c"] for x in c[:i+1]]
        def ema(d, p):
            k=2/(p+1); e=d[0]
            for v in d[1:]: e=v*k+e*(1-k)
            return e
        fv = ema(cl[-fast*3:], fast); sv = ema(cl[-slow*3:], slow)
        pf = ema(cl[-fast*3-1:-1], fast); ps = ema(cl[-slow*3-1:-1], slow)
        if pf<=ps and fv>sv: return "L"
        if pf>=ps and fv<sv: return "S"
        return None
    return f

def s_brk(lb):
    def f(c, i):
        if i < lb: return None
        hi = max(x["h"] for x in c[i-lb:i]); lo = min(x["l"] for x in c[i-lb:i])
        if c[i]["c"] > hi: return "L"
        if c[i]["c"] < lo: return "S"
        return None
    return f

def s_swing(lb):
    def f(c, i):
        if i < lb: return None
        cl = [x["c"] for x in c[i-lb:i+1]]
        m = len(cl)//2
        fa = sum(cl[:m])/m; sa = sum(cl[m:])/(len(cl)-m)
        hi = max(cl); lo = min(cl); rng = hi-lo
        if rng == 0: return None
        pos = (cl[-1]-lo)/rng
        if sa > fa and pos < 0.3: return "L"
        if sa < fa and pos > 0.7: return "S"
        return None
    return f

def s_vol(atr_p, atr_m):
    def f(c, i):
        if i < atr_p+1: return None
        trs = []
        for j in range(i-atr_p, i):
            tr = max(c[j]["h"]-c[j]["l"], abs(c[j]["h"]-c[j-1]["c"]), abs(c[j]["l"]-c[j-1]["c"]))
            trs.append(tr)
        atr = sum(trs)/len(trs)
        move = c[i]["c"] - c[i-1]["c"]
        if move > atr*atr_m: return "L"
        if move < -atr*atr_m: return "S"
        return None
    return f

def s_mr(per, std_m):
    def f(c, i):
        if i < per: return None
        cl = [x["c"] for x in c[i-per:i]]
        mean = sum(cl)/len(cl)
        std = (sum((x-mean)**2 for x in cl)/len(cl))**0.5
        p = c[i]["c"]
        if p < mean-std_m*std: return "L"
        if p > mean+std_m*std: return "S"
        return None
    return f

def main():
    candles = load()
    print(f"Data: {len(candles)} candles, ${candles[0]['c']:.0f} -> ${candles[-1]['c']:.0f}")
    print(f"Range: ${min(c['l'] for c in candles):.0f} - ${max(c['h'] for c in candles):.0f}\n")
    
    # Signal configs: (name, signal_fn)
    sigs = [
        ("RSI7", s_rsi(7, 20, 80)), ("RSI7_25_75", s_rsi(7, 25, 75)), ("RSI7_30_70", s_rsi(7, 30, 70)),
        ("RSI14", s_rsi(14, 20, 80)), ("RSI14_25_75", s_rsi(14, 25, 75)), ("RSI14_30_70", s_rsi(14, 30, 70)),
        ("RSI21", s_rsi(21, 20, 80)), ("RSI21_25_75", s_rsi(21, 25, 75)),
        ("Mom6_1%", s_mom(6, 0.01)), ("Mom6_2%", s_mom(6, 0.02)), ("Mom6_3%", s_mom(6, 0.03)),
        ("Mom12_1%", s_mom(12, 0.01)), ("Mom12_2%", s_mom(12, 0.02)),
        ("EMA9_21", s_ema(9, 21)), ("EMA5_34", s_ema(5, 34)), ("EMA5_21", s_ema(5, 21)),
        ("Brk12", s_brk(12)), ("Brk24", s_brk(24)), ("Brk48", s_brk(48)),
        ("Swing24", s_swing(24)), ("Swing48", s_swing(48)),
        ("Vol7_1.5", s_vol(7, 1.5)), ("Vol7_2", s_vol(7, 2.0)), ("Vol14_1.5", s_vol(14, 1.5)),
        ("MR24_2", s_mr(24, 2.0)), ("MR48_2", s_mr(48, 2.0)), ("MR48_1.5", s_mr(48, 1.5)),
    ]
    
    # Key parameter combos that could mathematically reach $1M
    # $200 -> $1M = 5000x. Need high risk + high leverage + good R:R
    configs = []
    # (tp%, sl%, risk%, leverage)
    for risk in [0.10, 0.20, 0.30, 0.40, 0.50]:
        for lev in [10, 20, 50]:
            for tp, sl in [(0.01, 0.005), (0.02, 0.01), (0.03, 0.015), (0.05, 0.02),
                           (0.02, 0.008), (0.03, 0.01), (0.05, 0.015), (0.10, 0.03),
                           (0.015, 0.008), (0.04, 0.015), (0.005, 0.003), (0.01, 0.003)]:
                configs.append((tp, sl, risk, lev))
    
    results = []
    total = len(sigs) * len(configs)
    print(f"Running {total} backtests...")
    
    for name, sig in sigs:
        for tp, sl, risk, lev in configs:
            try:
                r = bt(candles, sig, tp, sl, risk, lev)
                r["sig"] = name; r["tp"] = tp; r["sl"] = sl; r["risk"] = risk; r["lev"] = lev
                results.append(r)
            except: pass
    
    results.sort(key=lambda r: r["cap"], reverse=True)
    
    print(f"\n{'#':<4} {'Signal':<15} {'Final':>14} {'x':>8} {'T':>5} {'WR':>6} {'DD':>6} {'1M':>3} {'Risk':>5} {'Lev':>4} {'TP%':>6} {'SL%':>6}")
    print("=" * 100)
    for i, r in enumerate(results[:50]):
        x = r["cap"]/200
        print(f"{i+1:<4} {r['sig']:<15} ${r['cap']:>12,.2f} {x:>7.1f}x {r['t']:>5} {r['wr']:>5.1f}% {r['dd']:>5.1f}% {'Y' if r['r1m'] else 'N':>3} {r['risk']*100:>4.0f}% {r['lev']:>3}x {r['tp']*100:>5.2f}% {r['sl']*100:>5.2f}%")
    
    m = [r for r in results if r["r1m"]]
    if m:
        print(f"\n*** {len(m)} combos reached $1M! ***")
        for r in m[:30]:
            print(f"  {r['sig']}: ${r['cap']:,.0f} | {r['t']}T {r['wr']:.0f}%WR | risk={r['risk']*100:.0f}% lev={r['lev']}x tp={r['tp']*100:.1f}% sl={r['sl']*100:.1f}%")
    else:
        print(f"\nNo combos reached $1M")
        b = results[0]
        print(f"Best: {b['sig']} -> ${b['cap']:,.2f} ({b['cap']/200:.1f}x)")

if __name__ == "__main__":
    main()
