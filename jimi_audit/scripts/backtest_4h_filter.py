#!/usr/bin/env python3
"""
4H TREND FILTER BACKTEST
Adds multi-timeframe confirmation to Combined BB+Mom6 + Gate
Test: Does filtering entries against 4h trend improve WR/PF?
"""
import json, time, sys
from datetime import datetime, timezone
from collections import defaultdict

t0 = time.time()

with open('/root/.openclaw/workspace/jimi_audit/data/eth_full_1h.json') as f:
    raw_full = json.load(f)

N_full = len(raw_full)
o_full = [float(c[1]) for c in raw_full]
hi_full = [float(c[2]) for c in raw_full]
lo_full = [float(c[3]) for c in raw_full]
cl_full = [float(c[4]) for c in raw_full]
ts_full = [c[0] for c in raw_full]

print(f"Full dataset: {N_full} candles")

# === BUILD 4H CANDLES FROM 1H ===
print("Building 4h candles + indicators...", end=" "); sys.stdout.flush()

# Group 1h candles into 4h
c4h_o = []; c4h_h = []; c4h_l = []; c4h_c = []; c4h_ts = []
i = 0
while i < N_full:
    # Find 4h boundary (every 4 candles, aligned to UTC)
    end = min(i+4, N_full)
    c4h_o.append(o_full[i])
    c4h_h.append(max(hi_full[i:end]))
    c4h_l.append(min(lo_full[i:end]))
    c4h_c.append(cl_full[end-1])
    c4h_ts.append(ts_full[i])
    i = end

N4 = len(c4h_o)
print(f"4h candles: {N4}")

# 4h EMA
def ema4(data, p):
    e = [0.0]*N4; e[0] = data[0]; k = 2/(p+1)
    for i in range(1, N4): e[i] = data[i]*k + e[i-1]*(1-k)
    return e

ema4_20 = ema4(c4h_c, 20)
ema4_50 = ema4(c4h_c, 50)
ema4_100 = ema4(c4h_c, 100)
ema4_200 = ema4(c4h_c, 200)

# Map each 1h candle to its 4h candle index
map_1h_to_4h = []
for i in range(N_full):
    idx = i // 4
    if idx >= N4: idx = N4 - 1
    map_1h_to_4h.append(idx)

# 1h indicators (same as before)
bb_mid = [None]*N_full; bb_up = [None]*N_full; bb_lo = [None]*N_full
for i in range(19, N_full):
    seg = cl_full[i-19:i+1]; m = sum(seg)/20
    std = (sum((x-m)**2 for x in seg)/20)**0.5
    bb_mid[i] = m; bb_up[i] = m+2*std; bb_lo[i] = m-2*std

mom6_full = [None]*N_full
for i in range(6, N_full):
    if cl_full[i-6] > 0: mom6_full[i] = (cl_full[i]-cl_full[i-6])/cl_full[i-6]

mom12_full = [None]*N_full
for i in range(12, N_full):
    if cl_full[i-12] > 0: mom12_full[i] = (cl_full[i]-cl_full[i-12])/cl_full[i-12]

vol_gate_full = [None]*N_full
buf = []
for i in range(N_full):
    if mom12_full[i] is not None: buf.append(abs(mom12_full[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate_full[i] = sum(buf)/len(buf)

print(f"done in {time.time()-t0:.1f}s")

# === BACKTEST ENGINE ===
def bt(data_slice, sig, tp, sl, risk, lev, hold, gate_thresh=0.02, init=200, fee=0.0002, slip=0.001, cap_max=100000):
    o, hi, lo, cl, ts, vg = data_slice['o'], data_slice['hi'], data_slice['lo'], data_slice['cl'], data_slice['ts'], data_slice['vg']
    N = len(o); cap = float(init); pk = cap; max_dd = 0.0
    wins = 0; total = 0; gross_p = 0.0; gross_l = 0.0; skipped = 0
    monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0,'cap_start':0,'cap_end':0})
    i = 0
    while i < N:
        s = sig[i] if i < len(sig) else None
        if s is None or cap <= 1.0: i += 1; continue
        if i+1 >= N: break
        if gate_thresh > 0 and vg is not None and i < len(vg):
            g = vg[i]
            if g is not None and g < gate_thresh: skipped += 1; i += 1; continue
        mk = datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc).strftime('%Y-%m')
        if monthly[mk]['cap_start'] == 0: monthly[mk]['cap_start'] = cap
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
                monthly[mk]['trades'] += 1; monthly[mk]['wins'] += int(pnl>0); monthly[mk]['pnl'] += pnl
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
            monthly[mk]['trades'] += 1; monthly[mk]['wins'] += int(pnl>0); monthly[mk]['pnl'] += pnl
            if cap > pk: pk = cap
            dd = (pk-cap)/pk*100 if pk>0 else 0
            if dd > max_dd: max_dd = dd
            if cap > cap_max: cap = cap_max
            i = j+1
        monthly[mk]['cap_end'] = cap
    wr = wins/total*100 if total>0 else 0
    pf = gross_p/gross_l if gross_l>0 else float('inf')
    return {
        'cap':round(cap,2),'pk':round(pk,2),'dd':round(max_dd,1),
        'trades':total,'wins':wins,'wr':round(wr,1),'pf':round(pf,2),
        'skipped':skipped,'monthly':dict(monthly),
    }

# === SLICE HELPER ===
def slice_data(start_ms, end_ms):
    indices = [i for i in range(N_full) if ts_full[i] >= start_ms and ts_full[i] < end_ms]
    if not indices: return None
    s, e = indices[0], indices[-1]+1
    return {
        'o': o_full[s:e], 'hi': hi_full[s:e], 'lo': lo_full[s:e],
        'cl': cl_full[s:e], 'ts': ts_full[s:e], 'vg': vol_gate_full[s:e],
        's_idx': s, 'e_idx': e, 'N': e-s,
        'start': datetime.fromtimestamp(ts_full[s]/1000,tz=timezone.utc).strftime('%Y-%m-%d'),
        'end': datetime.fromtimestamp(ts_full[e-1]/1000,tz=timezone.utc).strftime('%Y-%m-%d'),
    }

def month_to_ms(y, m): return int(datetime(y,m,1,tzinfo=timezone.utc).timestamp()*1000)

# === SIGNAL GENERATORS ===
def gen_bb_sig(o, cl, N):
    sig = [None]*N
    for i in range(19, N):
        seg = cl[i-19:i+1]; m = sum(seg)/20
        std = (sum((x-m)**2 for x in seg)/20)**0.5
        lo = m-2*std; up = m+2*std
        if cl[i] < lo: sig[i] = 1
        elif cl[i] > up: sig[i] = -1
    return sig

def gen_mom6_sig(cl, N):
    sig = [None]*N
    for i in range(6, N):
        if cl[i-6] > 0:
            m = (cl[i]-cl[i-6])/cl[i-6]
            if m > 0.02: sig[i] = 1
            elif m < -0.02: sig[i] = -1
    return sig

def gen_combined_sig(o, cl, N):
    bb = gen_bb_sig(o, cl, N)
    mom = gen_mom6_sig(cl, N)
    combined = [None]*N
    for i in range(N):
        if bb[i] is not None: combined[i] = bb[i]
        elif mom[i] is not None: combined[i] = mom[i]
    return combined

def apply_4h_filter(sig, data_slice, ema_arr, ema_period):
    """Filter signals: only allow LONG if 4h price > 4h EMA, SHORT if below."""
    filtered = list(sig)
    s_idx = data_slice['s_idx']
    for i in range(len(filtered)):
        if filtered[i] is None: continue
        global_i = s_idx + i
        if global_i >= N_full: continue
        idx4 = map_1h_to_4h[global_i]
        if idx4 >= len(ema_arr) or ema_arr[idx4] == 0: continue
        price_4h = c4h_c[idx4]
        ema_val = ema_arr[idx4]
        if filtered[i] == 1 and price_4h < ema_val:
            filtered[i] = None  # Block LONG — 4h trend is bearish
        elif filtered[i] == -1 and price_4h > ema_val:
            filtered[i] = None  # Block SHORT — 4h trend is bullish
    return filtered

# === TESTS ===
train = slice_data(month_to_ms(2021,1), month_to_ms(2024,1))
test = slice_data(month_to_ms(2024,1), month_to_ms(2026,8))

# ============================================================
# TEST 1: 4H EMA PERIOD SWEEP (Combined + Gate)
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 1: 4H TREND FILTER SWEEP (Combined + Gate)")
print(f"{'='*80}")

ema_options = [
    ("None (baseline)", None, None),
    ("4h EMA20", ema4_20, 20),
    ("4h EMA50", ema4_50, 50),
    ("4h EMA100", ema4_100, 100),
    ("4h EMA200", ema4_200, 200),
    ("4h EMA20+50 (both)", "combo_20_50", None),
    ("4h EMA50+100 (both)", "combo_50_100", None),
]

print(f"\n{'Filter':<25} {'Period':>8} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'FinalCap':>10} {'Blocked':>8}")
print("-"*85)

for filter_name, ema_arr, ema_period in ema_options:
    for period_name, data in [("TRAIN", train), ("TEST", test)]:
        sig = gen_combined_sig(data['o'], data['cl'], data['N'])
        
        if ema_arr is None:
            filtered = sig
            blocked = 0
        elif isinstance(ema_arr, str):
            # Combo filter: both EMAs must agree
            if "20_50" in ema_arr:
                filtered = apply_4h_filter(sig, data, ema4_20, 20)
                filtered = apply_4h_filter(filtered, data, ema4_50, 50)
            else:
                filtered = apply_4h_filter(sig, data, ema4_50, 50)
                filtered = apply_4h_filter(filtered, data, ema4_100, 100)
            blocked = sum(1 for a,b in zip(sig, filtered) if a is not None and b is None)
        else:
            filtered = apply_4h_filter(sig, data, ema_arr, ema_period)
            blocked = sum(1 for a,b in zip(sig, filtered) if a is not None and b is None)
        
        r = bt(data, filtered, 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
        print(f"{filter_name:<25} {period_name:>8} {r['trades']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f} {blocked:>8}")

# ============================================================
# TEST 2: REGIME-SPECIFIC WITH BEST FILTER
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 2: REGIME PERFORMANCE (Combined + Gate + Best 4h Filter)")
print(f"{'='*80}")

regimes = [
    ("Bull (2021)", month_to_ms(2021,1), month_to_ms(2022,1)),
    ("Bear (2022)", month_to_ms(2022,1), month_to_ms(2023,1)),
    ("Sideways (2023)", month_to_ms(2023,1), month_to_ms(2024,1)),
    ("Recovery (2024)", month_to_ms(2024,1), month_to_ms(2025,1)),
    ("Choppy (2025-H1)", month_to_ms(2025,1), month_to_ms(2025,7)),
    ("Dead (2025-H2)", month_to_ms(2025,7), month_to_ms(2026,1)),
    ("Recent (2026-H1)", month_to_ms(2026,1), month_to_ms(2026,7)),
]

# Test baseline vs EMA50 vs EMA100
for filter_label, ema_arr in [("No Filter", None), ("4h EMA50", ema4_50), ("4h EMA100", ema4_100)]:
    print(f"\n  --- {filter_label} ---")
    print(f"  {'Regime':<20} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'FinalCap':>10} {'Ret%':>8}")
    print(f"  {'-'*65}")
    for name, start, end in regimes:
        d = slice_data(start, end)
        if d is None: continue
        sig = gen_combined_sig(d['o'], d['cl'], d['N'])
        if ema_arr is not None:
            sig = apply_4h_filter(sig, d, ema_arr, 50 if ema_arr == ema4_50 else 100)
        r = bt(d, sig, 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
        ret = (r['cap'] - 200) / 200 * 100
        marker = " GOOD" if ret > 100 else " OK" if ret > 0 else " BAD"
        print(f"  {name:<20} {r['trades']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f} {ret:>+7.0f}%{marker}")

# ============================================================
# TEST 3: ENTRY QUALITY ANALYSIS
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 3: ENTRY QUALITY — WHAT GETS BLOCKED?")
print(f"{'='*80}")

# Analyze what signals get blocked by the 4h filter
sig_full = gen_combined_sig(o_full, cl_full, N_full)

for filter_label, ema_arr, ema_p in [("4h EMA50", ema4_50, 50), ("4h EMA100", ema4_100, 100), ("4h EMA200", ema4_200, 200)]:
    long_total = sum(1 for i in range(N_full) if sig_full[i] == 1)
    short_total = sum(1 for i in range(N_full) if sig_full[i] == -1)
    
    filtered = list(sig_full)
    blocked_long = 0; blocked_short = 0
    for i in range(N_full):
        if filtered[i] is None: continue
        idx4 = map_1h_to_4h[i]
        if idx4 >= len(ema_arr) or ema_arr[idx4] == 0: continue
        price_4h = c4h_c[idx4]
        if filtered[i] == 1 and price_4h < ema_arr[idx4]:
            blocked_long += 1; filtered[i] = None
        elif filtered[i] == -1 and price_4h > ema_arr[idx4]:
            blocked_short += 1; filtered[i] = None
    
    remaining = sum(1 for x in filtered if x is not None)
    print(f"\n  {filter_label}:")
    print(f"    LONG signals:  {long_total} total, {blocked_long} blocked ({blocked_long/long_total*100:.0f}%), {long_total-blocked_long} pass")
    print(f"    SHORT signals: {short_total} total, {blocked_short} blocked ({blocked_short/short_total*100:.0f}%), {short_total-blocked_short} pass")
    print(f"    Total: {long_total+short_total} -> {remaining} ({(long_total+short_total-remaining)/(long_total+short_total)*100:.0f}% filtered)")

# ============================================================
# TEST 4: WALK-FORWARD WITH FILTER
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 4: WALK-FORWARD (Combined + Gate + 4h EMA50)")
print(f"{'='*80}")

print(f"\n{'Window':<20} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'FinalCap':>10} {'Return':>8}")
print("-"*70)

for year in range(2021, 2027):
    for month in [1, 4, 7, 10]:
        start = month_to_ms(year, month)
        end_month = month + 9; end_year = year
        if end_month > 12: end_month -= 12; end_year += 1
        if end_year > 2027: break
        end = month_to_ms(end_year, end_month)
        if end > ts_full[-1]: break
        d = slice_data(start, end)
        if d is None or d['N'] < 720: continue
        sig = gen_combined_sig(d['o'], d['cl'], d['N'])
        sig = apply_4h_filter(sig, d, ema4_50, 50)
        r = bt(d, sig, 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
        ret = (r['cap'] - 200) / 200 * 100
        marker = " GOOD" if ret > 100 else " OK" if ret > 0 else " BAD"
        print(f"{d['start']}->{d['end']:<10} {r['trades']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f} {ret:>+7.0f}%{marker}")

# ============================================================
# VERDICT
# ============================================================
print(f"\n{'='*80}")
print(f"VERDICT: Does 4h trend filter help?")
print(f"{'='*80}")

# Compare baseline vs filtered on full period
d_full = slice_data(month_to_ms(2021,1), month_to_ms(2026,8))
sig_base = gen_combined_sig(d_full['o'], d_full['cl'], d_full['N'])
sig_ema50 = apply_4h_filter(list(sig_base), d_full, ema4_50, 50)
sig_ema100 = apply_4h_filter(list(sig_base), d_full, ema4_100, 100)

r_base = bt(d_full, sig_base, 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
r_ema50 = bt(d_full, sig_ema50, 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
r_ema100 = bt(d_full, sig_ema100, 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)

print(f"""
  Baseline (no filter):    WR={r_base['wr']}% PF={r_base['pf']} DD={r_base['dd']}% Cap=${r_base['cap']:,.0f} Trades={r_base['trades']}
  + 4h EMA50 filter:       WR={r_ema50['wr']}% PF={r_ema50['pf']} DD={r_ema50['dd']}% Cap=${r_ema50['cap']:,.0f} Trades={r_ema50['trades']}
  + 4h EMA100 filter:      WR={r_ema100['wr']}% PF={r_ema100['pf']} DD={r_ema100['dd']}% Cap=${r_ema100['cap']:,.0f} Trades={r_ema100['trades']}

  WR improvement (EMA50):  {float(r_ema50['wr'])-float(r_base['wr']):+.1f}%
  PF improvement (EMA50):  {float(r_ema50['pf'])-float(r_base['pf']):+.2f}
  DD improvement (EMA50):  {float(r_ema50['dd'])-float(r_base['dd']):+.1f}%

  WR improvement (EMA100): {float(r_ema100['wr'])-float(r_base['wr']):+.1f}%
  PF improvement (EMA100): {float(r_ema100['pf'])-float(r_base['pf']):+.2f}
  DD improvement (EMA100): {float(r_ema100['dd'])-float(r_base['dd']):+.1f}%
""")

print(f"Completed in {time.time()-t0:.1f}s")
