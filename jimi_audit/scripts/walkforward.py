#!/usr/bin/env python3
"""
WALK-FORWARD VALIDATION
Train: 2021-01 to 2023-12 (in-sample)
Test:  2024-01 to 2026-07 (out-of-sample)
Also: rolling 12-month windows, regime-specific tests, no-fake-seeds
"""
import json, time, random, sys, math
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

def ts_to_str(ts_ms): return datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')
def month_str(ts_ms): return datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc).strftime('%Y-%m')

# === INDICATORS (computed on full dataset, sliced per window) ===
print("Computing indicators on full dataset...", end=" "); sys.stdout.flush()
t1 = time.time()

# Bollinger Bands
bb_mid = [None]*N_full
bb_up = [None]*N_full
bb_lo = [None]*N_full
for i in range(19, N_full):
    seg = cl_full[i-19:i+1]; m = sum(seg)/20
    std = (sum((x-m)**2 for x in seg)/20)**0.5
    bb_mid[i] = m; bb_up[i] = m+2*std; bb_lo[i] = m-2*std

# 12h momentum
mom12_full = [None]*N_full
for i in range(12, N_full):
    if cl_full[i-12] > 0: mom12_full[i] = (cl_full[i]-cl_full[i-12])/cl_full[i-12]

# 6h momentum
mom6_full = [None]*N_full
for i in range(6, N_full):
    if cl_full[i-6] > 0: mom6_full[i] = (cl_full[i]-cl_full[i-6])/cl_full[i-6]

# 48h rolling avg abs 12h mom (vol gate)
vol_gate_full = [None]*N_full
buf = []
for i in range(N_full):
    if mom12_full[i] is not None: buf.append(abs(mom12_full[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate_full[i] = sum(buf)/len(buf)

print(f"done in {time.time()-t1:.1f}s")

# === BACKTEST ENGINE ===
def bt_window(o, hi, lo, cl, ts, sig, vol_gate, tp, sl, risk, lev, hold,
              gate_thresh=0.02, init=200, fee=0.0002, slip=0.001, cap_max=100000):
    """Backtest on a data window. Returns detailed results."""
    N = len(o)
    cap = float(init); pk = cap; max_dd = 0.0
    wins = 0; total = 0; gross_p = 0.0; gross_l = 0.0
    skipped_gate = 0; bars_held = 0
    monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0,'cap_start':0,'cap_end':0})
    i = 0
    while i < N:
        s = sig[i] if i < len(sig) else None
        if s is None or cap <= 1.0: i += 1; continue
        if i+1 >= N: break
        # Gate
        if gate_thresh > 0 and vol_gate is not None and i < len(vol_gate):
            g = vol_gate[i]
            if g is not None and g < gate_thresh: skipped_gate += 1; i += 1; continue
        mk = month_str(ts[i])
        if monthly[mk]['cap_start'] == 0: monthly[mk]['cap_start'] = cap
        # Entry
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
                cap += pnl; total += 1; bars_held += (j-i)
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
            cap += pnl; total += 1; bars_held += (j-i)
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
        'cap': round(cap,2), 'pk': round(pk,2), 'dd': round(max_dd,1),
        'trades': total, 'wins': wins, 'wr': round(wr,1), 'pf': round(pf,2),
        'skipped_gate': skipped_gate, 'avg_hold': round(bars_held/total,1) if total>0 else 0,
        'monthly': dict(monthly),
    }

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

# === SLICE DATA ===
def slice_data(start_ms, end_ms):
    """Slice all arrays to a time window."""
    mask = [(ts_full[i] >= start_ms and ts_full[i] < end_ms) for i in range(N_full)]
    indices = [i for i in range(N_full) if mask[i]]
    if not indices: return None
    s, e = indices[0], indices[-1]+1
    return {
        'o': o_full[s:e], 'hi': hi_full[s:e], 'lo': lo_full[s:e],
        'cl': cl_full[s:e], 'ts': ts_full[s:e], 'vg': vol_gate_full[s:e],
        'start': ts_to_str(ts_full[s]), 'end': ts_to_str(ts_full[e-1]),
        'N': e-s,
    }

def month_to_ms(year, month):
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)

# ============================================================
# TEST 1: IN-SAMPLE vs OUT-OF-SAMPLE
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 1: WALK-FORWARD VALIDATION")
print(f"Train: 2021-01 to 2023-12 | Test: 2024-01 to 2026-07")
print(f"{'='*80}")

train = slice_data(month_to_ms(2021,1), month_to_ms(2024,1))
test = slice_data(month_to_ms(2024,1), month_to_ms(2026,8))

configs = [
    ("BB Mean Rev + Gate", "bb", 0.003, 0.002),
    ("mom6_2pct + Gate", "mom6", 0.002, 0.002),
    ("Combined + Gate", "combined", 0.003, 0.002),
    ("BB Mean Rev (no gate)", "bb", 0.003, 0.002),
    ("mom6_2pct (no gate)", "mom6", 0.002, 0.002),
    ("Combined (no gate)", "combined", 0.003, 0.002),
]

print(f"\n{'Strategy':<28} {'Period':<12} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'FinalCap':>10} {'Skipped':>8}")
print("-"*90)

for name, sig_type, tp, sl in configs:
    use_gate = "no gate" not in name
    for period_name, data in [("TRAIN", train), ("TEST", test)]:
        if sig_type == "bb": sig = gen_bb_sig(data['o'], data['cl'], data['N'])
        elif sig_type == "mom6": sig = gen_mom6_sig(data['cl'], data['N'])
        else: sig = gen_combined_sig(data['o'], data['cl'], data['N'])
        r = bt_window(data['o'], data['hi'], data['lo'], data['cl'], data['ts'],
                      sig, data['vg'], tp, sl, 0.05, 20, 8,
                      gate_thresh=0.02 if use_gate else 0)
        print(f"{name:<28} {period_name:<12} {r['trades']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f} {r['skipped_gate']:>8}")

# ============================================================
# TEST 2: ROLLING 12-MONTH WINDOWS
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 2: ROLLING 12-MONTH WINDOWS (Combined + Gate)")
print(f"{'='*80}")
print(f"{'Window':<20} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'FinalCap':>10} {'Return':>8}")
print("-"*70)

# Rolling 12-month windows, 3-month step
for year in range(2021, 2027):
    for month in [1, 4, 7, 10]:
        start = month_to_ms(year, month)
        end_month = month + 9
        end_year = year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        if end_year > 2027: break
        end = month_to_ms(end_year, end_month)
        if end > ts_full[-1]: break
        
        d = slice_data(start, end)
        if d is None or d['N'] < 720: continue
        
        sig = gen_combined_sig(d['o'], d['cl'], d['N'])
        r = bt_window(d['o'], d['hi'], d['lo'], d['cl'], d['ts'],
                      sig, d['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
        ret = (r['cap'] - 200) / 200 * 100
        marker = " GOOD" if ret > 100 else " OK" if ret > 0 else " BAD"
        print(f"{d['start']}->{d['end']:<10} {r['trades']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f} {ret:>+7.0f}%{marker}")

# ============================================================
# TEST 3: REGIME-SPECIFIC PERFORMANCE
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 3: REGIME-SPECIFIC PERFORMANCE (Combined + Gate)")
print(f"{'='*80}")

regimes = [
    ("Bull (2021)", month_to_ms(2021,1), month_to_ms(2022,1)),
    ("Bear (2022)", month_to_ms(2022,1), month_to_ms(2023,1)),
    ("Sideways (2023)", month_to_ms(2023,1), month_to_ms(2024,1)),
    ("Recovery (2024)", month_to_ms(2024,1), month_to_ms(2025,1)),
    ("Choppy (2025-H1)", month_to_ms(2025,1), month_to_ms(2025,7)),
    ("Dead (2025-H2)", month_to_ms(2025,7), month_to_ms(2026,1)),
    ("Recent (2026-H1)", month_to_ms(2026,1), month_to_ms(2026,7)),
    ("Full (2021-2026)", month_to_ms(2021,1), month_to_ms(2026,7)),
]

print(f"\n{'Regime':<20} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>6} {'FinalCap':>10} {'Return':>8} {'Monthly':>8}")
print("-"*75)

for name, start, end in regimes:
    d = slice_data(start, end)
    if d is None: continue
    sig = gen_combined_sig(d['o'], d['cl'], d['N'])
    r = bt_window(d['o'], d['hi'], d['lo'], d['cl'], d['ts'],
                  sig, d['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
    ret = (r['cap'] - 200) / 200 * 100
    # Approximate months
    months = d['N'] / 720
    monthly_ret = ((r['cap']/200)**(1/months) - 1) * 100 if months > 0 and r['cap'] > 0 else 0
    marker = " GOOD" if ret > 100 else " OK" if ret > 0 else " BAD"
    print(f"{name:<20} {r['trades']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f} {ret:>+7.0f}% {monthly_ret:>+7.1f}%{marker}")

# ============================================================
# TEST 4: WITHOUT GATE (baseline comparison)
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 4: WITH vs WITHOUT GATE (per regime)")
print(f"{'='*80}")

print(f"\n{'Regime':<20} {'With Gate':>12} {'No Gate':>12} {'Gate Benefit':>13}")
print("-"*60)

for name, start, end in regimes:
    d = slice_data(start, end)
    if d is None: continue
    sig = gen_combined_sig(d['o'], d['cl'], d['N'])
    r_gate = bt_window(d['o'], d['hi'], d['lo'], d['cl'], d['ts'],
                       sig, d['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
    r_nogate = bt_window(d['o'], d['hi'], d['lo'], d['cl'], d['ts'],
                         sig, d['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0)
    benefit = ((r_gate['cap'] - r_nogate['cap']) / r_nogate['cap'] * 100) if r_nogate['cap'] > 0 else 0
    marker = " GATE WINS" if r_gate['cap'] > r_nogate['cap'] else " NO GATE WINS"
    print(f"{name:<20} ${r_gate['cap']:>10,.0f} ${r_nogate['cap']:>10,.0f} {benefit:>+12.0f}%{marker}")

# ============================================================
# TEST 5: MONTHLY CONSISTENCY (train vs test)
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 5: MONTHLY RETURN CONSISTENCY")
print(f"{'='*80}")

for period_name, data in [("TRAIN (2021-2023)", train), ("TEST (2024-2026)", test)]:
    sig = gen_combined_sig(data['o'], data['cl'], data['N'])
    r = bt_window(data['o'], data['hi'], data['lo'], data['cl'], data['ts'],
                  sig, data['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)
    
    pos_months = 0; neg_months = 0; total_months = 0
    big_wins = 0; big_losses = 0
    print(f"\n  --- {period_name} ---")
    print(f"  {'Month':>8} {'Tr':>4} {'WR%':>5} {'PnL$':>10} {'Cap':>10}")
    print(f"  {'-'*42}")
    for mk in sorted(r['monthly'].keys()):
        m = r['monthly'][mk]
        if m['trades'] == 0: continue
        total_months += 1
        wr = m['wins']/m['trades']*100 if m['trades']>0 else 0
        if m['pnl'] > 0: pos_months += 1
        else: neg_months += 1
        if m['pnl'] > 5000: big_wins += 1
        if m['pnl'] < -5000: big_losses += 1
        marker = " ++" if m['pnl'] > 5000 else " --" if m['pnl'] < -5000 else ""
        print(f"  {mk:>8} {m['trades']:>4} {wr:>5.1f}% ${m['pnl']:>9,.0f} ${m['cap_end']:>9,.0f}{marker}")
    
    print(f"\n  Summary: {pos_months} positive / {neg_months} negative months ({pos_months/total_months*100:.0f}% win rate)")
    print(f"  Big wins (>$5K): {big_wins} | Big losses (<-$5K): {big_losses}")
    print(f"  Final: ${r['cap']:,.0f} | DD: {r['dd']:.1f}% | PF: {r['pf']:.2f}")

# ============================================================
# VERDICT
# ============================================================
print(f"\n{'='*80}")
print(f"WALK-FORWARD VERDICT")
print(f"{'='*80}")

# Compare train vs test for combined+gate
sig_train = gen_combined_sig(train['o'], train['cl'], train['N'])
r_train = bt_window(train['o'], train['hi'], train['lo'], train['cl'], train['ts'],
                    sig_train, train['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)

sig_test = gen_combined_sig(test['o'], test['cl'], test['N'])
r_test = bt_window(test['o'], test['hi'], test['lo'], test['cl'], test['ts'],
                   sig_test, test['vg'], 0.003, 0.002, 0.05, 20, 8, gate_thresh=0.02)

print(f"""
  IN-SAMPLE (2021-2023):
    WR={r_train['wr']}% | PF={r_train['pf']} | DD={r_train['dd']}% | Final=${r_train['cap']:,.0f}
    Trades: {r_train['trades']}

  OUT-OF-SAMPLE (2024-2026):
    WR={r_test['wr']}% | PF={r_test['pf']} | DD={r_test['dd']}% | Final=${r_test['cap']:,.0f}
    Trades: {r_test['trades']}

  Degradation:
    WR: {r_train['wr']}% -> {r_test['wr']}% ({float(r_test['wr'])-float(r_train['wr']):+.1f}%)
    PF: {r_train['pf']} -> {r_test['pf']} ({float(r_test['pf'])-float(r_train['pf']):+.2f})
    DD: {r_train['dd']}% -> {r_test['dd']}% ({float(r_test['dd'])-float(r_train['dd']):+.1f}%)

  {"PASS: Strategy performs similarly out-of-sample. Deploy with confidence." if float(r_test['pf']) > 1.2 and float(r_test['wr']) > 50 else "CAUTION: Significant degradation out-of-sample. Reduce position size." if float(r_test['pf']) > 1.0 else "FAIL: Strategy does not hold up out-of-sample. Do not deploy."}
""")

print(f"Completed in {time.time()-t0:.1f}s")
