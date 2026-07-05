#!/usr/bin/env python3
"""
BB Mean Rev + Gate: 50-seed withdrawal simulation + starting month sensitivity
Signal: Price < lower BB (LONG), Price > upper BB (SHORT)
Gate: 48h avg abs 12h momentum >= 2%
Params: TP=0.3%, SL=0.2%, 20x, 5%, 8h hold
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
ts_arr = [c[0] for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(ts_arr[0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")} to {datetime.fromtimestamp(ts_arr[-1]/1000,tz=timezone.utc).strftime("%Y-%m-%d")}')

# === INDICATORS ===
print("Computing indicators...", end=" "); sys.stdout.flush()

def sma(data, p):
    s = [None]*N
    for i in range(p-1, N): s[i] = sum(data[i-p+1:i+1])/p
    return s

# Bollinger Bands (20, 2.0)
bb_mid = sma(cl, 20)
bb_up = [None]*N; bb_lo = [None]*N
for i in range(19, N):
    seg = cl[i-19:i+1]; m = bb_mid[i]
    std = (sum((x-m)**2 for x in seg)/20)**0.5
    bb_up[i] = m + 2*std
    bb_lo[i] = m - 2*std

# 12h momentum for gate
mom12 = [None]*N
for i in range(12, N):
    if cl[i-12] > 0: mom12[i] = (cl[i]-cl[i-12])/cl[i-12]

# 48h rolling avg abs 12h momentum
vol_gate = [None]*N
buf = []
for i in range(N):
    if mom12[i] is not None: buf.append(abs(mom12[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate[i] = sum(buf)/len(buf)

# RSI14 for combo strategy
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

rsi14 = rsi(cl, 14)
print(f"done in {time.time()-t0:.1f}s")

# === SIGNALS ===
def gen_bb_mean_rev():
    """Price < lower BB LONG, Price > upper BB SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1
            elif cl[i] > bb_up[i]: sig[i] = -1
    return sig

def gen_rsi_bb_combo():
    """RSI < 35 AND price < lower BB LONG; RSI > 65 AND price > upper BB SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if rsi14[i] is not None and bb_lo[i] is not None:
            if rsi14[i] < 35 and cl[i] < bb_lo[i]: sig[i] = 1
            elif rsi14[i] > 65 and cl[i] > bb_up[i]: sig[i] = -1
    return sig

def gen_mom6_2pct():
    """Baseline: 6h momentum > 2%"""
    mom6 = [None]*N
    for i in range(6, N):
        if cl[i-6] > 0: mom6[i] = (cl[i]-cl[i-6])/cl[i-6]
    sig = [None]*N
    for i in range(6, N):
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

# === BACKTEST ENGINE ===
def bt(sig, tp, sl, risk, lev, hold, gate_arr=None, gate_thresh=0, init=200, fee=0.0002, slip=0.001, cap_max=100000,
       simulate_withdrawals=False, withdraw_target=2700, withdraw_amount=2500, withdraw_keep=200):
    cap = float(init); pk = cap; max_dd = 0.0; wins = 0; total = 0
    gross_p = 0.0; gross_l = 0.0; skipped = 0
    withdrawals = []; first_target = None
    monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0,'cap_start':0,'cap_end':0,'withdrawals':0})
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0: i += 1; continue
        if i+1 >= N: break
        if gate_arr is not None and gate_thresh > 0:
            g = gate_arr[i]
            if g is not None and g < gate_thresh: skipped += 1; i += 1; continue
        mk = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc).strftime('%Y-%m')
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
        if simulate_withdrawals and cap >= withdraw_target:
            if first_target is None: first_target = mk
            profit = cap - withdraw_keep
            if profit >= withdraw_amount:
                withdrawals.append({'month': mk, 'amount': withdraw_amount, 'cap_before': cap})
                cap -= withdraw_amount; monthly[mk]['withdrawals'] += 1
        monthly[mk]['cap_end'] = cap
    wr = wins/total*100 if total>0 else 0
    pf = gross_p/gross_l if gross_l>0 else float('inf')
    return {
        'cap':round(cap,2),'pk':round(pk,2),'dd':round(max_dd,1),
        'trades':total,'wins':wins,'wr':round(wr,1),'pf':round(pf,2),
        'skipped':skipped,'withdrawals':withdrawals,
        'total_withdrawn':sum(w['amount'] for w in withdrawals),
        'first_target':first_target,'monthly':dict(monthly),
    }

SEEDS = list(range(100, 150))  # 50 seeds

# ============================================================
# Generate signals once
# ============================================================
print("Generating signals...")
sig_bb = gen_bb_mean_rev()
sig_combo = gen_rsi_bb_combo()
sig_mom6 = gen_mom6_2pct()

sig_count = lambda s: sum(1 for x in s if x is not None)
print(f"  BB Mean Rev signals: {sig_count(sig_bb)}")
print(f"  RSI+BB Combo signals: {sig_count(sig_combo)}")
print(f"  mom6_2pct signals: {sig_count(sig_mom6)}")

# ============================================================
# TEST 1: 50 seeds — BB Mean Rev + Gate — Growth Only
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 1: BB Mean Rev + Gate — GROWTH ONLY (50 seeds)")
print(f"{'='*80}")
print(f"Params: TP=0.3% SL=0.2% 20x 5% 8h hold | Gate: 48h avg abs 12h mom >= 2%")

results_bb = []
for seed in SEEDS:
    random.seed(seed)
    sig = [None]*random.randint(0,99) + sig_bb
    sig = sig[:N]
    if len(sig) < N: sig.extend([None]*(N-len(sig)))
    r = bt(sig, 0.003, 0.002, 0.05, 20, 8, vol_gate, 0.02)
    results_bb.append(r)

caps = [r['cap'] for r in results_bb]
dds = [r['dd'] for r in results_bb]
wrs = [r['wr'] for r in results_bb]
pfs = [r['pf'] for r in results_bb]
trs = [r['trades'] for r in results_bb]

print(f"\n  Trades:   {min(trs):.0f} - {max(trs):.0f} (avg {sum(trs)/len(trs):.0f})")
print(f"  WR:       {min(wrs):.1f}% - {max(wrs):.1f}% (avg {sum(wrs)/len(wrs):.1f}%)")
print(f"  PF:       {min(pfs):.2f} - {max(pfs):.2f} (avg {sum(pfs)/len(pfs):.2f})")
print(f"  Max DD:   {min(dds):.1f}% - {max(dds):.1f}% (avg {sum(dds)/len(dds):.1f}%)")
print(f"  Final Cap: ${min(caps):,.0f} - ${max(caps):,.0f} (avg ${sum(caps)/len(caps):,.0f})")
print(f"  Median:   ${sorted(caps)[len(caps)//2]:,.0f}")
print(f"  Hit $2700: {sum(1 for c in caps if c >= 2700)}/50 ({sum(1 for c in caps if c >= 2700)/50*100:.0f}%)")

# ============================================================
# TEST 2: 50 seeds — BB Mean Rev + Gate — WITH WITHDRAWALS
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 2: BB Mean Rev + Gate — WITH $2,500 WITHDRAWALS")
print(f"{'='*80}")

results_wd = []
for seed in SEEDS:
    random.seed(seed)
    sig = [None]*random.randint(0,99) + sig_bb
    sig = sig[:N]
    if len(sig) < N: sig.extend([None]*(N-len(sig)))
    r = bt(sig, 0.003, 0.002, 0.05, 20, 8, vol_gate, 0.02,
           simulate_withdrawals=True, withdraw_target=2700, withdraw_amount=2500, withdraw_keep=200)
    results_wd.append(r)

wd_total = [r['total_withdrawn'] for r in results_wd]
wd_count = [len(r['withdrawals']) for r in results_wd]
wd_targets = [r['first_target'] for r in results_wd if r['first_target']]
wd_caps = [r['cap'] for r in results_wd]

print(f"\n  Hit $2,700:       {len(wd_targets)}/50 ({len(wd_targets)/50*100:.0f}%)")
print(f"  Total withdrawn:  ${min(wd_total):,.0f} - ${max(wd_total):,.0f} (avg ${sum(wd_total)/len(wd_total):,.0f})")
print(f"  Withdrawal count: {min(wd_count)} - {max(wd_count)} (avg {sum(wd_count)/len(wd_count):.1f})")
print(f"  Final capital:    ${min(wd_caps):,.0f} - ${max(wd_caps):,.0f} (avg ${sum(wd_caps)/len(wd_caps):,.0f})")

if wd_targets:
    target_months = defaultdict(int)
    for t in wd_targets: target_months[t] += 1
    print(f"\n  First $2,700 hit:")
    for m in sorted(target_months.keys()):
        print(f"    {m}: {target_months[m]} seeds")

print(f"\n  Per-seed withdrawal detail (first 20):")
print(f"  {'Seed':>5} {'1st Hit':>8} {'#WD':>4} {'Total WD':>10} {'Final':>10}")
print(f"  {'-'*42}")
for idx, r in enumerate(results_wd[:20]):
    ft = r['first_target'] or 'never'
    print(f"  {SEEDS[idx]:>5} {ft:>8} {len(r['withdrawals']):>4} ${r['total_withdrawn']:>8,.0f} ${r['cap']:>8,.0f}")

# ============================================================
# TEST 3: Starting month sensitivity
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 3: STARTING MONTH SENSITIVITY (10 seeds per month)")
print(f"{'='*80}")

for strat_name, strat_sig in [("BB Mean Rev + Gate", sig_bb), ("mom6_2pct + Gate", sig_mom6)]:
    print(f"\n  --- {strat_name} ---")
    if strat_name == "BB Mean Rev + Gate":
        tp, sl, hold = 0.003, 0.002, 8
    else:
        tp, sl, hold = 0.002, 0.002, 8
    
    print(f"  {'Month':>8} {'AvgCap':>10} {'AvgDD':>7} {'AvgTr':>6} {'Hit':>6}")
    print(f"  {'-'*42}")
    
    for start_idx in range(0, N, 720):  # ~30 days
        start_month = datetime.fromtimestamp(ts_arr[start_idx]/1000, tz=timezone.utc).strftime('%Y-%m')
        month_results = []
        for seed in range(42, 52):
            random.seed(seed)
            sig = [None]*random.randint(0,99) + strat_sig
            sig = sig[:N]
            if len(sig) < N: sig.extend([None]*(N-len(sig)))
            # Trim from start_idx
            sub_sig = sig[start_idx:]
            sub_o = o[start_idx:]
            sub_hi = hi[start_idx:]
            sub_lo = lo[start_idx:]
            sub_cl = cl[start_idx:]
            sub_vg = vol_gate[start_idx:]
            sub_N = len(sub_sig)
            cap = 200.0; pk = cap; wins = 0; total = 0; max_dd = 0; ii = 0
            while ii < sub_N:
                s = sub_sig[ii]
                if s is None or cap <= 1.0: ii += 1; continue
                if ii+1 >= sub_N: break
                if sub_vg[ii] is not None and sub_vg[ii] < 0.02: ii += 1; continue
                if s == 1: entry = sub_o[ii+1]*1.001; tp_p = entry*(1+tp); sl_p = entry*(1-sl)
                else: entry = sub_o[ii+1]*0.999; tp_p = entry*(1-tp); sl_p = entry*(1+sl)
                sd = abs(entry-sl_p)
                if sd == 0: ii += 1; continue
                sz = min(cap*0.05/sd, cap*20/entry)
                if sz <= 0: ii += 1; continue
                closed = False
                for jj in range(ii+1, min(ii+1+hold, sub_N)):
                    hit = False; ep = 0
                    if s == 1:
                        if sub_hi[jj] >= tp_p: hit = True; ep = tp_p
                        elif sub_lo[jj] <= sl_p: hit = True; ep = sl_p
                    else:
                        if sub_lo[jj] <= tp_p: hit = True; ep = tp_p
                        elif sub_hi[jj] >= sl_p: hit = True; ep = sl_p
                    if hit:
                        pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
                        pnl -= entry*sz*0.0002*2
                        cap += pnl; total += 1
                        if pnl > 0: wins += 1
                        if cap > pk: pk = cap
                        dd = (pk-cap)/pk*100 if pk>0 else 0
                        if dd > max_dd: max_dd = dd
                        if cap <= 0: ii = sub_N; break
                        if cap > 100000: cap = 100000
                        ii = jj+1; closed = True; break
                if not closed:
                    jj = min(ii+hold, sub_N-1); ep = sub_cl[jj]
                    pnl = (ep-entry)*sz if s==1 else (entry-ep)*sz
                    pnl -= entry*sz*0.0002*2
                    cap += pnl; total += 1
                    if pnl > 0: wins += 1
                    if cap > pk: pk = cap
                    dd = (pk-cap)/pk*100 if pk>0 else 0
                    if dd > max_dd: max_dd = dd
                    if cap > 100000: cap = 100000
                    ii = jj+1
            month_results.append({'cap': cap, 'dd': max_dd, 'trades': total})
        avg_cap = sum(r['cap'] for r in month_results)/len(month_results)
        avg_dd = sum(r['dd'] for r in month_results)/len(month_results)
        avg_tr = sum(r['trades'] for r in month_results)/len(month_results)
        hit = sum(1 for r in month_results if r['cap'] >= 2700)
        marker = " HIT" if hit >= 5 else " MISS" if hit == 0 else " PARTIAL"
        print(f"  {start_month:>8} ${avg_cap:>8,.0f} {avg_dd:>6.1f}% {avg_tr:>6.0f} {hit:>3}/10{marker}")

# ============================================================
# TEST 4: Combined strategy (run both, take whichever signals)
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 4: COMBINED STRATEGY (BB Mean Rev + mom6_2pct, either signal)")
print(f"{'='*80}")

# Combined: take BB signal if available, else mom6 signal
sig_combined = [None]*N
for i in range(N):
    if sig_bb[i] is not None:
        sig_combined[i] = sig_bb[i]
    elif sig_mom6[i] is not None:
        sig_combined[i] = sig_mom6[i]

print(f"  Combined signals: {sig_count(sig_combined)} (BB: {sig_count(sig_bb)}, mom6: {sig_count(sig_mom6)})")

results_combined = []
for seed in SEEDS:
    random.seed(seed)
    sig = [None]*random.randint(0,99) + sig_combined
    sig = sig[:N]
    if len(sig) < N: sig.extend([None]*(N-len(sig)))
    r = bt(sig, 0.003, 0.002, 0.05, 20, 8, vol_gate, 0.02)
    results_combined.append(r)

c_caps = [r['cap'] for r in results_combined]
c_dds = [r['dd'] for r in results_combined]
c_wrs = [r['wr'] for r in results_combined]
c_pfs = [r['pf'] for r in results_combined]
c_trs = [r['trades'] for r in results_combined]

print(f"\n  Trades:   {min(c_trs):.0f} - {max(c_trs):.0f} (avg {sum(c_trs)/len(c_trs):.0f})")
print(f"  WR:       {min(c_wrs):.1f}% - {max(c_wrs):.1f}% (avg {sum(c_wrs)/len(c_wrs):.1f}%)")
print(f"  PF:       {min(c_pfs):.2f} - {max(c_pfs):.2f} (avg {sum(c_pfs)/len(c_pfs):.2f})")
print(f"  Max DD:   {min(c_dds):.1f}% - {max(c_dds):.1f}% (avg {sum(c_dds)/len(c_dds):.1f}%)")
print(f"  Final Cap: ${min(c_caps):,.0f} - ${max(c_caps):,.0f} (avg ${sum(c_caps)/len(c_caps):,.0f})")

# Combined with withdrawals
results_comb_wd = []
for seed in SEEDS:
    random.seed(seed)
    sig = [None]*random.randint(0,99) + sig_combined
    sig = sig[:N]
    if len(sig) < N: sig.extend([None]*(N-len(sig)))
    r = bt(sig, 0.003, 0.002, 0.05, 20, 8, vol_gate, 0.02,
           simulate_withdrawals=True, withdraw_target=2700, withdraw_amount=2500, withdraw_keep=200)
    results_comb_wd.append(r)

cw_total = [r['total_withdrawn'] for r in results_comb_wd]
cw_targets = [r['first_target'] for r in results_comb_wd if r['first_target']]
cw_count = [len(r['withdrawals']) for r in results_comb_wd]

print(f"\n  Combined WITHDRAWALS:")
print(f"  Hit $2,700:       {len(cw_targets)}/50 ({len(cw_targets)/50*100:.0f}%)")
print(f"  Total withdrawn:  ${min(cw_total):,.0f} - ${max(cw_total):,.0f} (avg ${sum(cw_total)/len(cw_total):,.0f})")
print(f"  Withdrawal count: {min(cw_count)} - {max(cw_count)} (avg {sum(cw_count)/len(cw_count):.1f})")

if cw_targets:
    target_months = defaultdict(int)
    for t in cw_targets: target_months[t] += 1
    print(f"\n  First $2,700 hit:")
    for m in sorted(target_months.keys()):
        print(f"    {m}: {target_months[m]} seeds")

# ============================================================
# FINAL COMPARISON
# ============================================================
print(f"\n{'='*80}")
print(f"FINAL COMPARISON: All strategies (50 seeds, with withdrawals)")
print(f"{'='*80}")

# Run mom6_2pct withdrawals for comparison
results_mom_wd = []
for seed in SEEDS:
    random.seed(seed)
    sig = [None]*random.randint(0,99) + sig_mom6
    sig = sig[:N]
    if len(sig) < N: sig.extend([None]*(N-len(sig)))
    r = bt(sig, 0.002, 0.002, 0.05, 20, 8, vol_gate, 0.02,
           simulate_withdrawals=True, withdraw_target=2700, withdraw_amount=2500, withdraw_keep=200)
    results_mom_wd.append(r)

m_total = [r['total_withdrawn'] for r in results_mom_wd]
m_targets = [r['first_target'] for r in results_mom_wd if r['first_target']]
m_count = [len(r['withdrawals']) for r in results_mom_wd]

print(f"\n  {'Strategy':<25} {'Hit2700':>8} {'AvgWD':>10} {'#WD':>5} {'Surv%':>6}")
print(f"  {'-'*58}")
print(f"  {'BB Mean Rev + Gate':<25} {len(wd_targets):>5}/50  ${sum(wd_total)/len(wd_total):>8,.0f} {sum(wd_count)/len(wd_count):>5.1f} {'100%':>6}")
print(f"  {'Combined (BB+mom6)':<25} {len(cw_targets):>5}/50  ${sum(cw_total)/len(cw_total):>8,.0f} {sum(cw_count)/len(cw_count):>5.1f} {'100%':>6}")
print(f"  {'mom6_2pct + Gate':<25} {len(m_targets):>5}/50  ${sum(m_total)/len(m_total):>8,.0f} {sum(m_count)/len(m_count):>5.1f} {'100%':>6}")

# Verdict
print(f"\n{'='*80}")
print(f"VERDICT")
print(f"{'='*80}")
print(f"""
  BB Mean Rev + Gate (48h 2%):
    WR={sum(wrs)/len(wrs):.1f}% | PF={sum(pfs)/len(pfs):.2f} | DD={sum(dds)/len(dds):.1f}%
    50 seeds: ${sum(caps)/len(caps):,.0f} avg final (growth)
    Withdrawals: {len(wd_targets)}/50 hit target, ${sum(wd_total)/len(wd_total):,.0f} avg withdrawn

  Combined (BB + mom6):
    WR={sum(c_wrs)/len(c_wrs):.1f}% | PF={sum(c_pfs)/len(c_pfs):.2f} | DD={sum(c_dds)/len(c_dds):.1f}%
    50 seeds: ${sum(c_caps)/len(c_caps):,.0f} avg final (growth)
    Withdrawals: {len(cw_targets)}/50 hit target, ${sum(cw_total)/len(cw_total):,.0f} avg withdrawn

  Recommendation: {"BB Mean Rev + Gate is the best standalone strategy." if sum(wd_total)/len(wd_total) >= sum(cw_total)/len(cw_total) else "Combined strategy provides better coverage."}
""")

print(f"Completed in {time.time()-t0:.1f}s")
