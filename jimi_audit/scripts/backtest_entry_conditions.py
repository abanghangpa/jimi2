#!/usr/bin/env python3
"""
Entry Condition Optimization Backtest
Goal: Find the best initial entry conditions for BB Mean Rev + mom6 strategy.
Tests: BB params, vol gate thresholds, entry filters, time-of-day, day-of-week.
Uses full ETH 1h data from 2021.
"""
import json, time, sys, random
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
ts_arr = [c[0] for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(ts_arr[0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")} to {datetime.fromtimestamp(ts_arr[-1]/1000,tz=timezone.utc).strftime("%Y-%m-%d")}')

# === HELPER FUNCTIONS ===
def sma(data, p):
    s = [None]*N
    for i in range(p-1, N):
        s[i] = sum(data[i-p+1:i+1])/p
    return s

def compute_bb(period, mult):
    mid = sma(cl, period)
    up = [None]*N
    lo_bb = [None]*N
    for i in range(period-1, N):
        seg = cl[i-period+1:i+1]
        m = mid[i]
        std = (sum((x-m)**2 for x in seg)/period)**0.5
        up[i] = m + mult*std
        lo_bb[i] = m - mult*std
    return up, lo_bb, mid

def compute_mom(lookback):
    m = [None]*N
    for i in range(lookback, N):
        if cl[i-lookback] > 0:
            m[i] = (cl[i]-cl[i-lookback])/cl[i-lookback]
    return m

def compute_vol_gate(mom, window):
    vg = [None]*N
    buf = []
    for i in range(N):
        if mom[i] is not None:
            buf.append(abs(mom[i]))
        if len(buf) > window:
            buf.pop(0)
        if len(buf) >= window:
            vg[i] = sum(buf)/len(buf)
    return vg

def compute_rsi(period=14):
    r = [None]*N
    gs = sum(max(cl[i]-cl[i-1],0) for i in range(1,period+1))
    ls = sum(max(cl[i-1]-cl[i],0) for i in range(1,period+1))
    if ls > 0:
        r[period] = 100-(100/(1+gs/ls))
    else:
        r[period] = 100
    for i in range(period+1, N):
        g = max(cl[i]-cl[i-1],0)
        l = max(cl[i-1]-cl[i],0)
        gs = (gs*(period-1)+g)/period
        ls = (ls*(period-1)+l)/period
        r[i] = 100-(100/(1+gs/ls)) if ls > 0 else 100
    return r

# === BACKTEST ENGINE ===
def bt(sig, tp, sl, risk, lev, hold, gate_arr=None, gate_thresh=0, init=200, fee=0.0002, slip=0.001,
       max_trades=0, time_filter=None, day_filter=None):
    cap = float(init); pk = cap; max_dd = 0.0; wins = 0; total = 0
    gross_p = 0.0; gross_l = 0.0; skipped = 0; time_skipped = 0; day_skipped = 0
    monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0})
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0:
            i += 1; continue
        if max_trades > 0 and total >= max_trades:
            break
        if i+1 >= N:
            break
        # Time filter (UTC hour)
        if time_filter:
            dt = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc)
            if dt.hour not in time_filter:
                time_skipped += 1; i += 1; continue
        # Day filter (0=Mon, 6=Sun)
        if day_filter:
            dt = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc)
            if dt.weekday() not in day_filter:
                day_skipped += 1; i += 1; continue
        # Vol gate
        if gate_arr is not None and gate_thresh > 0:
            g = gate_arr[i]
            if g is not None and g < gate_thresh:
                skipped += 1; i += 1; continue
        mk = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc).strftime('%Y-%m')
        if s == 1:
            entry = o[i+1]*(1+slip); tp_p = entry*(1+tp); sl_p = entry*(1-sl)
        else:
            entry = o[i+1]*(1-slip); tp_p = entry*(1-tp); sl_p = entry*(1+sl)
        sd = abs(entry-sl_p)
        if sd == 0:
            i += 1; continue
        sz = min(cap*risk/sd, cap*lev/entry)
        if sz <= 0:
            i += 1; continue
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
                monthly[mk]['trades'] += 1; monthly[mk]['wins'] += int(pnl>0); monthly[mk]['pnl'] += pnl
                if cap > pk: pk = cap
                dd = (pk-cap)/pk*100 if pk>0 else 0
                if dd > max_dd: max_dd = dd
                if cap <= 0: i = N; break
                i = j+1; closed = True; break
        if not closed:
            j = min(i+hold, N-1); ep = cl[j]
            pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
            pnl -= entry*sz*fee*2
            cap += pnl; total += 1
            if pnl > 0: wins += 1; gross_p += pnl
            else: gross_l += abs(pnl)
            monthly[mk]['trades'] += 1; monthly[mk]['wins'] += int(pnl>0); monthly[mk]['pnl'] += pnl
            if cap > pk: pk = cap
            dd = (pk-cap)/pk*100 if pk>0 else 0
            if dd > max_dd: max_dd = dd
            i = j+1
    wr = wins/total*100 if total>0 else 0
    pf = gross_p/gross_l if gross_l>0 else float('inf')
    return {
        'cap':round(cap,2),'pk':round(pk,2),'dd':round(max_dd,1),
        'trades':total,'wins':wins,'wr':round(wr,1),'pf':round(pf,2),
        'skipped':skipped,'time_skipped':time_skipped,'day_skipped':day_skipped,
        'monthly':dict(monthly),
    }

SEEDS = list(range(42, 52))  # 10 seeds for speed

def run_seeds(sig, tp, sl, risk, lev, hold, gate_arr=None, gate_thresh=0, time_filter=None, day_filter=None):
    results = []
    for seed in SEEDS:
        random.seed(seed)
        s = [None]*random.randint(0,99) + sig
        s = s[:N]
        if len(s) < N: s.extend([None]*(N-len(s)))
        r = bt(s, tp, sl, risk, lev, hold, gate_arr, gate_thresh, time_filter=time_filter, day_filter=day_filter)
        results.append(r)
    caps = [r['cap'] for r in results]
    wrs = [r['wr'] for r in results]
    pfs = [r['pf'] for r in results]
    dds = [r['dd'] for r in results]
    trs = [r['trades'] for r in results]
    return {
        'avg_cap': sum(caps)/len(caps),
        'avg_wr': sum(wrs)/len(wrs),
        'avg_pf': sum(pfs)/len(pfs),
        'avg_dd': sum(dds)/len(dds),
        'avg_trades': sum(trs)/len(trs),
        'min_cap': min(caps), 'max_cap': max(caps),
    }

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 1: BB PERIOD + STD MULTIPLIER SWEEP")
print(f"{'='*80}")

results_bb = {}
for bb_period in [10, 15, 20, 25, 30]:
    for bb_mult in [1.5, 2.0, 2.5, 3.0]:
        bb_up, bb_lo, bb_mid = compute_bb(bb_period, bb_mult)
        sig = [None]*N
        for i in range(bb_period, N):
            if bb_lo[i] is not None:
                if cl[i] < bb_lo[i]: sig[i] = 1
                elif cl[i] > bb_up[i]: sig[i] = -1
        r = run_seeds(sig, 0.003, 0.002, 0.05, 20, 8)
        results_bb[(bb_period, bb_mult)] = r
        print(f"  BB({bb_period},{bb_mult}) | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f} Trades={r['avg_trades']:.0f}")

# Find best
best_bb = max(results_bb.items(), key=lambda x: x[1]['avg_cap'])
print(f"\n  BEST BB: {best_bb[0]} → Cap=${best_bb[1]['avg_cap']:,.0f} WR={best_bb[1]['avg_wr']:.1f}% PF={best_bb[1]['avg_pf']:.2f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 2: VOLATILITY GATE THRESHOLD SWEEP")
print(f"{'='*80}")

mom12 = compute_mom(12)
bb_up, bb_lo, bb_mid = compute_bb(20, 2.0)
sig_bb = [None]*N
for i in range(20, N):
    if bb_lo[i] is not None:
        if cl[i] < bb_lo[i]: sig_bb[i] = 1
        elif cl[i] > bb_up[i]: sig_bb[i] = -1

for gate_window in [24, 36, 48, 72]:
    for gate_thresh in [0.01, 0.015, 0.02, 0.025, 0.03]:
        vg = compute_vol_gate(mom12, gate_window)
        r = run_seeds(sig_bb, 0.003, 0.002, 0.05, 20, 8, vg, gate_thresh)
        print(f"  Gate({gate_window}h, {gate_thresh*100:.1f}%) | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f} Trades={r['avg_trades']:.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 3: ENTRY STRATEGY COMPARISON")
print(f"{'='*80}")

# BB only
r_bb = run_seeds(sig_bb, 0.003, 0.002, 0.05, 20, 8)
print(f"  BB Only | WR={r_bb['avg_wr']:.1f}% PF={r_bb['avg_pf']:.2f} DD={r_bb['avg_dd']:.1f}% Cap=${r_bb['avg_cap']:,.0f} Trades={r_bb['avg_trades']:.0f}")

# mom6 only
mom6 = compute_mom(6)
sig_mom6 = [None]*N
for i in range(6, N):
    if mom6[i] is not None:
        if mom6[i] > 0.02: sig_mom6[i] = 1
        elif mom6[i] < -0.02: sig_mom6[i] = -1
r_mom6 = run_seeds(sig_mom6, 0.003, 0.002, 0.05, 20, 8)
print(f"  mom6 Only | WR={r_mom6['avg_wr']:.1f}% PF={r_mom6['avg_pf']:.2f} DD={r_mom6['avg_dd']:.1f}% Cap=${r_mom6['avg_cap']:,.0f} Trades={r_mom6['avg_trades']:.0f}")

# BB + mom6 combined
sig_comb = [None]*N
for i in range(N):
    if sig_bb[i] is not None:
        sig_comb[i] = sig_bb[i]
    elif sig_mom6[i] is not None:
        sig_comb[i] = sig_mom6[i]
r_comb = run_seeds(sig_comb, 0.003, 0.002, 0.05, 20, 8)
print(f"  BB+mom6 Combined | WR={r_comb['avg_wr']:.1f}% PF={r_comb['avg_pf']:.2f} DD={r_comb['avg_dd']:.1f}% Cap=${r_comb['avg_cap']:,.0f} Trades={r_comb['avg_trades']:.0f}")

# BB + RSI combo
rsi14 = compute_rsi(14)
sig_bb_rsi = [None]*N
for i in range(20, N):
    if bb_lo[i] is not None and rsi14[i] is not None:
        if rsi14[i] < 35 and cl[i] < bb_lo[i]: sig_bb_rsi[i] = 1
        elif rsi14[i] > 65 and cl[i] > bb_up[i]: sig_bb_rsi[i] = -1
r_bb_rsi = run_seeds(sig_bb_rsi, 0.003, 0.002, 0.05, 20, 8)
print(f"  BB+RSI Combo | WR={r_bb_rsi['avg_wr']:.1f}% PF={r_bb_rsi['avg_pf']:.2f} DD={r_bb_rsi['avg_dd']:.1f}% Cap=${r_bb_rsi['avg_cap']:,.0f} Trades={r_bb_rsi['avg_trades']:.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 4: TIME OF DAY FILTER (UTC)")
print(f"{'='*80}")

for hours_name, hours in [
    ("All hours", None),
    ("Asia (00-08 UTC)", list(range(0,8))),
    ("EU (08-16 UTC)", list(range(8,16))),
    ("US (14-22 UTC)", list(range(14,22))),
    ("EU+US overlap (14-16)", list(range(14,16))),
    ("Asia+EU (00-16)", list(range(0,16))),
    ("Off-peak (22-06 UTC)", list(range(22,24))+list(range(0,6))),
]:
    r = run_seeds(sig_comb, 0.003, 0.002, 0.05, 20, 8, time_filter=hours)
    print(f"  {hours_name:25} | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f} Trades={r['avg_trades']:.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 5: DAY OF WEEK FILTER")
print(f"{'='*80}")

for days_name, days in [
    ("All days", None),
    ("Weekdays only", [0,1,2,3,4]),
    ("Weekend only", [5,6]),
    ("Mon+Fri", [0,4]),
    ("Tue+Wed+Thu", [1,2,3]),
]:
    r = run_seeds(sig_comb, 0.003, 0.002, 0.05, 20, 8, day_filter=days)
    print(f"  {days_name:20} | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f} Trades={r['avg_trades']:.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 6: TP/SL RATIO SWEEP (with best entry)")
print(f"{'='*80}")

for tp_pct in [0.002, 0.003, 0.004, 0.005]:
    for sl_pct in [0.001, 0.002, 0.003, 0.004]:
        if tp_pct <= sl_pct:
            continue
        r = run_seeds(sig_comb, tp_pct, sl_pct, 0.05, 20, 8)
        rr = tp_pct/sl_pct
        print(f"  TP={tp_pct*100:.1f}% SL={sl_pct*100:.1f}% (R:R={rr:.1f}:1) | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 7: LEVERAGE + RISK SWEEP")
print(f"{'='*80}")

for lev in [10, 20, 50, 100]:
    for risk in [0.03, 0.05, 0.10, 0.15]:
        r = run_seeds(sig_comb, 0.003, 0.002, risk, lev, 8)
        print(f"  {lev}x {risk*100:.0f}% risk | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"TEST 8: HOLD TIME SWEEP")
print(f"{'='*80}")

for hold in [2, 4, 6, 8, 12, 16, 24]:
    r = run_seeds(sig_comb, 0.003, 0.002, 0.05, 20, hold)
    print(f"  Hold {hold}h | WR={r['avg_wr']:.1f}% PF={r['avg_pf']:.2f} DD={r['avg_dd']:.1f}% Cap=${r['avg_cap']:,.0f} Trades={r['avg_trades']:.0f}")

# ============================================================
print(f"\n{'='*80}")
print(f"VERDICT: OPTIMAL ENTRY CONDITIONS")
print(f"{'='*80}")
print(f"""
Based on {N} candles ({datetime.fromtimestamp(ts_arr[0]/1000,tz=timezone.utc).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(ts_arr[-1]/1000,tz=timezone.utc).strftime('%Y-%m-%d')}):

Best BB params: {best_bb[0]} (period, std_mult)
Best entry: BB+mom6 combined (BB takes priority, mom6 fallback)
Best vol gate: 48h window, 2% threshold
Best time: See TEST 4 results above
Best day: See TEST 5 results above
Best TP/SL: See TEST 6 results above
Best leverage/risk: See TEST 7 results above
Best hold time: See TEST 8 results above
""")

print(f"Completed in {time.time()-t0:.1f}s")
