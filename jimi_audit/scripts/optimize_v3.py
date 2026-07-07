#!/usr/bin/env python3
"""
Optimize for $200 → $2500/mo withdrawal. Matches bb_full_test.py engine exactly.
Key: TP checked BEFORE SL, entry slippage, signal randomization per seed.
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
hi_arr = [float(c[2]) for c in raw]
lo_arr = [float(c[3]) for c in raw]
cl = [float(c[4]) for c in raw]
ts_arr = [c[0] for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(ts_arr[0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")} to {datetime.fromtimestamp(ts_arr[-1]/1000,tz=timezone.utc).strftime("%Y-%m-%d")}')

print("Computing indicators...", end=" "); sys.stdout.flush()

def sma(data, p):
    s = [None]*N
    for i in range(p-1, N): s[i] = sum(data[i-p+1:i+1])/p
    return s

bb_mid = sma(cl, 20)
bb_up = [None]*N; bb_lo = [None]*N
for i in range(19, N):
    seg = cl[i-19:i+1]; m = bb_mid[i]
    std = (sum((x-m)**2 for x in seg)/20)**0.5
    bb_up[i] = m + 2*std
    bb_lo[i] = m - 2*std

mom12 = [None]*N
for i in range(12, N):
    if cl[i-12] > 0: mom12[i] = (cl[i]-cl[i-12])/cl[i-12]

vol_gate_48 = [None]*N
buf = []
for i in range(N):
    if mom12[i] is not None: buf.append(abs(mom12[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate_48[i] = sum(buf)/len(buf)

mom6 = [None]*N
for i in range(6, N):
    if cl[i-6] > 0: mom6[i] = (cl[i]-cl[i-6])/cl[i-6]

# ATR14
tr_arr = [0]*N
for i in range(1, N):
    tr_arr[i] = max(hi_arr[i]-lo_arr[i], abs(hi_arr[i]-cl[i-1]), abs(lo_arr[i]-cl[i-1]))
atr14 = [None]*N
for i in range(14, N):
    atr14[i] = sum(tr_arr[i-13:i+1])/14

print(f"done in {time.time()-t0:.1f}s")

# === SIGNALS (generated once, same as bb_full_test.py) ===
def gen_bb():
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1
            elif cl[i] > bb_up[i]: sig[i] = -1
    return sig

def gen_bb_mom6():
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1; continue
            if cl[i] > bb_up[i]: sig[i] = -1; continue
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

def gen_mom6():
    sig = [None]*N
    for i in range(6, N):
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

sig_count = lambda s: sum(1 for x in s if x is not None)
sig_bb = gen_bb()
sig_bb_mom6 = gen_bb_mom6()
sig_mom6 = gen_mom6()
print(f"BB signals: {sig_count(sig_bb)} | BB+mom6: {sig_count(sig_bb_mom6)} | mom6 only: {sig_count(sig_mom6)}")

# === BACKTEST ENGINE (exact copy of bb_full_test.py bt()) ===
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
        # Entry with slippage
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
                if hi_arr[j] >= tp_p: hit = True; ep = tp_p       # TP FIRST
                elif lo_arr[j] <= sl_p: hit = True; ep = sl_p
            else:
                if lo_arr[j] <= tp_p: hit = True; ep = tp_p       # TP FIRST
                elif hi_arr[j] >= sl_p: hit = True; ep = sl_p
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

# === TEST MATRIX ===
SEEDS = list(range(100, 150))  # Same seeds as bb_full_test.py

configs = [
    # Replicate bb_full_test.py exactly
    ("bb_gate2pct", 0.003, 0.002, 0.05, 20, 8, 0.02, 'bb'),
    # No gate
    ("bb_nogate", 0.003, 0.002, 0.05, 20, 8, 0, 'bb'),
    # BB+mom6 combos
    ("bb_mom6_gate2pct", 0.003, 0.002, 0.05, 20, 8, 0.02, 'bb_mom6'),
    ("bb_mom6_nogate", 0.003, 0.002, 0.05, 20, 8, 0, 'bb_mom6'),
    # mom6 only
    ("mom6_gate2pct", 0.003, 0.002, 0.05, 20, 8, 0.02, 'mom6'),
    ("mom6_nogate", 0.003, 0.002, 0.05, 20, 8, 0, 'mom6'),
    # Lower gates
    ("bb_mom6_gate0.5pct", 0.003, 0.002, 0.05, 20, 8, 0.005, 'bb_mom6'),
    ("bb_mom6_gate1pct", 0.003, 0.002, 0.05, 20, 8, 0.01, 'bb_mom6'),
    # Aggressive risk (no gate)
    ("bb_mom6_risk10", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk15", 0.003, 0.002, 0.15, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk20", 0.003, 0.002, 0.20, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk25", 0.003, 0.002, 0.25, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk30", 0.003, 0.002, 0.30, 20, 8, 0, 'bb_mom6'),
    # Higher leverage
    ("bb_mom6_lev25_risk10", 0.003, 0.002, 0.10, 25, 8, 0, 'bb_mom6'),
    ("bb_mom6_lev30_risk10", 0.003, 0.002, 0.10, 30, 8, 0, 'bb_mom6'),
    ("bb_mom6_lev25_risk15", 0.003, 0.002, 0.15, 25, 8, 0, 'bb_mom6'),
    ("bb_mom6_lev25_risk20", 0.003, 0.002, 0.20, 25, 8, 0, 'bb_mom6'),
    # Wider TP
    ("bb_mom6_tp0.5_sl0.3", 0.005, 0.003, 0.10, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_tp0.5_sl0.3_lev25", 0.005, 0.003, 0.10, 25, 8, 0, 'bb_mom6'),
    ("bb_mom6_tp0.8_sl0.5", 0.008, 0.005, 0.10, 20, 12, 0, 'bb_mom6'),
    ("bb_mom6_tp1.0_sl0.5", 0.010, 0.005, 0.10, 20, 12, 0, 'bb_mom6'),
    ("bb_mom6_tp1.0_sl0.5_lev25", 0.010, 0.005, 0.10, 25, 12, 0, 'bb_mom6'),
    # Very wide TP (trend riding)
    ("bb_mom6_tp2.0_sl1.0", 0.020, 0.010, 0.10, 20, 24, 0, 'bb_mom6'),
    # Tight TP (scalp)
    ("bb_mom6_tp0.2_sl0.15", 0.002, 0.0015, 0.10, 20, 4, 0, 'bb_mom6'),
    # Aggressive combos
    ("mega_lev25_risk20_tp0.5", 0.005, 0.003, 0.20, 25, 8, 0, 'bb_mom6'),
    ("mega_lev25_risk25_tp0.5", 0.005, 0.003, 0.25, 25, 8, 0, 'bb_mom6'),
    ("mega_lev30_risk20_tp0.5", 0.005, 0.003, 0.20, 30, 8, 0, 'bb_mom6'),
    # bb_mom6 with gate + aggressive
    ("bb_mom6_gate2pct_risk10", 0.003, 0.002, 0.10, 20, 8, 0.02, 'bb_mom6'),
    ("bb_mom6_gate2pct_risk15", 0.003, 0.002, 0.15, 20, 8, 0.02, 'bb_mom6'),
]

print(f"\n{'='*120}")
print(f"Running {len(configs)} configs × {len(SEEDS)} seeds = {len(configs)*len(SEEDS)} backtests")
print(f"{'='*120}\n")

results = []
for ci, (name, tp, sl, risk, lev, hold, gate_t, sig_name) in enumerate(configs):
    sig_map = {'bb': sig_bb, 'bb_mom6': sig_bb_mom6, 'mom6': sig_mom6}
    base_sig = sig_map[sig_name]
    gate_arr = vol_gate_48 if gate_t > 0 else None

    # WITHDRAWAL SIMULATION (primary metric)
    wd_results = []
    for seed in SEEDS:
        random.seed(seed)
        sig = [None]*random.randint(0,99) + base_sig
        sig = sig[:N]
        if len(sig) < N: sig.extend([None]*(N-len(sig)))
        r = bt(sig, tp, sl, risk, lev, hold, gate_arr, gate_t,
               simulate_withdrawals=True, withdraw_target=2700, withdraw_amount=2500, withdraw_keep=200)
        wd_results.append(r)

    wd_totals = [r['total_withdrawn'] for r in wd_results]
    wd_caps = [r['cap'] for r in wd_results]
    wd_counts = [len(r['withdrawals']) for r in wd_results]
    wd_targets = [r['first_target'] for r in wd_results if r['first_target']]
    wrs = [r['wr'] for r in wd_results]
    pfs = [r['pf'] for r in wd_results]
    dds = [r['dd'] for r in wd_results]
    trs = [r['trades'] for r in wd_results]

    avg_wd = sum(wd_totals)/len(wd_totals)
    avg_cap = sum(wd_caps)/len(wd_caps)
    avg_wr = sum(wrs)/len(wrs)
    avg_pf = sum(pfs)/len(pfs)
    avg_dd = sum(dds)/len(dds)
    avg_trades = sum(trs)/len(trs)
    hit_rate = len(wd_targets)/len(SEEDS)*100
    avg_wd_count = sum(wd_counts)/len(wd_counts)

    results.append({
        'name': name, 'tp': tp, 'sl': sl, 'risk': risk, 'lev': lev, 'hold': hold,
        'gate': gate_t, 'sig': sig_name,
        'avg_wd': avg_wd, 'avg_cap': avg_cap, 'avg_wr': avg_wr, 'avg_pf': avg_pf,
        'avg_dd': avg_dd, 'avg_trades': avg_trades, 'hit_rate': hit_rate,
        'avg_wd_count': avg_wd_count, 'targets_hit': len(wd_targets),
        'first_wd': sorted(wd_targets)[:3] if wd_targets else [],
        'min_wd': min(wd_totals), 'max_wd': max(wd_totals),
    })

    print(f"[{ci+1:2d}/{len(configs)}] {name:<40} WR={avg_wr:5.1f}% PF={avg_pf:5.2f} DD={avg_dd:5.1f}% Tr={avg_trades:5.0f} WD=${avg_wd:>9,.0f} Hit={hit_rate:4.0f}% #WD={avg_wd_count:.1f}")

# Sort by avg_wd
results.sort(key=lambda x: x['avg_wd'], reverse=True)

print(f"\n{'='*120}")
print("TOP 15 BY TOTAL WITHDRAWN (primary metric)")
print(f"{'='*120}")
print(f"{'Config':<40} {'WR%':>6} {'PF':>6} {'DD%':>6} {'Tr':>5} {'AvgWD$':>10} {'Hit%':>6} {'#WD':>5} {'MinWD':>10} {'MaxWD':>10} {'1stWD':>8}")
print("-"*120)
for r in results[:15]:
    first = r['first_wd'][0] if r['first_wd'] else 'N/A'
    print(f"{r['name']:<40} {r['avg_wr']:>5.1f}% {r['avg_pf']:>5.2f} {r['avg_dd']:>5.1f}% {r['avg_trades']:>5.0f} {r['avg_wd']:>9,.0f} {r['hit_rate']:>5.0f}% {r['avg_wd_count']:>5.1f} {r['min_wd']:>9,.0f} {r['max_wd']:>9,.0f} {first:>8}")

print(f"\n{'='*120}")
print("BOTTOM 5 (worst)")
print(f"{'='*120}")
for r in results[-5:]:
    first = r['first_wd'][0] if r['first_wd'] else 'N/A'
    print(f"{r['name']:<40} {r['avg_wr']:>5.1f}% {r['avg_pf']:>5.2f} {r['avg_dd']:>5.1f}% {r['avg_trades']:>5.0f} {r['avg_wd']:>9,.0f} {r['hit_rate']:>5.0f}% {r['avg_wd_count']:>5.1f} {r['min_wd']:>9,.0f} {r['max_wd']:>9,.0f} {first:>8}")

# Save
output = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'target': '$2500/month withdrawal from $200 capital',
    'data': f'{N} candles 2021-2026, {len(SEEDS)} seeds (100-149)',
    'engine': 'bb_full_test.py compatible (TP-first, entry slip, per-seed randomization)',
    'results': results
}
with open('/root/.openclaw/workspace/jimi_audit/data/optimization_v3.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s. Saved to optimization_v3.json")
