#!/usr/bin/env python3
"""Backtest mom6_2pct with VOLATILITY GATES - 2021-2026, 10 seeds"""
import json, time, random, sys
from datetime import datetime, timezone
from collections import defaultdict

t0 = time.time()
random.seed(42)

with open('/root/.openclaw/workspace/jimi_audit/data/eth_full_1h.json') as f:
    raw_full = json.load(f)

cutoff_ts = datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
raw = [c for c in raw_full if c[0] >= cutoff_ts]
N = len(raw)
o = [float(c[1]) for c in raw]
hi = [float(c[2]) for c in raw]
lo = [float(c[3]) for c in raw]
cl = [float(c[4]) for c in raw]
vol = [float(c[5]) for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(raw[0][0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")} to {datetime.fromtimestamp(raw[-1][0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")}')
print(f'Price: ${cl[0]:.0f} -> ${cl[-1]:.0f}')

# === INDICATORS ===
print("Computing indicators...", end=" "); sys.stdout.flush()
t1 = time.time()

# 6h momentum (signal)
mom6 = [None]*N
for i in range(6, N):
    if cl[i-6] > 0:
        mom6[i] = (cl[i] - cl[i-6]) / cl[i-6]

# 12h momentum (for volatility gate)
mom12 = [None]*N
for i in range(12, N):
    if cl[i-12] > 0:
        mom12[i] = (cl[i] - cl[i-12]) / cl[i-12]

# ATR
tr = [0.0]*N
for i in range(1, N):
    tr[i] = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
atr14 = [0.0]*N
atr14[14] = sum(tr[1:15])/14
for i in range(15, N):
    atr14[i] = (atr14[i-1]*13 + tr[i])/14
atr_pct = [0.0]*N
for i in range(N):
    atr_pct[i] = atr14[i]/cl[i]*100 if cl[i] > 0 else 0

# Rolling volatility gate: 48h avg absolute 12h momentum
# Pre-compute for different windows
def rolling_avg_abs(arr, window):
    """Rolling average of absolute values, ignoring None."""
    result = [None]*N
    buf = []
    for i in range(N):
        if arr[i] is not None:
            buf.append(abs(arr[i]))
        if len(buf) > window:
            buf.pop(0)
        if len(buf) >= window:
            result[i] = sum(buf) / len(buf)
    return result

vol_gate_48 = rolling_avg_abs(mom12, 48)
vol_gate_24 = rolling_avg_abs(mom12, 24)
vol_gate_72 = rolling_avg_abs(mom12, 72)

print(f"done in {time.time()-t1:.1f}s")

# === SIGNAL GENERATOR ===
def gen_mom6_2pct(offset=0):
    sig = [None]*N
    for i in range(6+offset, N):
        m = mom6[i]
        if m is not None:
            if m > 0.02: sig[i] = 1
            elif m < -0.02: sig[i] = -1
    return sig

# === BACKTEST ENGINE ===
def bt(sig, tp_pct, sl_pct, risk_pct, leverage, hold_hours=8,
       vol_gate_arr=None, vol_gate_threshold=0, init=200, fee=0.0002, slip=0.001, cap_max=100000):
    cap = float(init)
    pk = cap
    max_dd = 0.0
    wins = 0
    total = 0
    bars_held = 0
    gross_profit = 0.0
    gross_loss = 0.0
    skipped_vol = 0
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0:
            i += 1
            continue
        if i+1 >= N:
            break
        # Volatility gate
        if vol_gate_arr is not None and vol_gate_threshold > 0:
            vg = vol_gate_arr[i]
            if vg is not None and vg < vol_gate_threshold:
                skipped_vol += 1
                i += 1
                continue
        if s == 1:
            entry = o[i+1]*(1+slip)
            tp_price = entry*(1+tp_pct)
            sl_price = entry*(1-sl_pct)
        else:
            entry = o[i+1]*(1-slip)
            tp_price = entry*(1-tp_pct)
            sl_price = entry*(1+sl_pct)
        sl_dist = abs(entry - sl_price)
        if sl_dist == 0:
            i += 1
            continue
        risk_amt = cap * risk_pct
        size = risk_amt / sl_dist
        max_size = (cap * leverage) / entry
        size = min(size, max_size)
        if size <= 0:
            i += 1
            continue
        closed = False
        end_j = min(i+1+hold_hours, N)
        for j in range(i+1, end_j):
            hit_tp = hit_sl = False
            exit_p = 0.0
            if s == 1:
                if hi[j] >= tp_price: hit_tp = True; exit_p = tp_price
                elif lo[j] <= sl_price: hit_sl = True; exit_p = sl_price
            else:
                if lo[j] <= tp_price: hit_tp = True; exit_p = tp_price
                elif hi[j] >= sl_price: hit_sl = True; exit_p = sl_price
            if hit_tp or hit_sl:
                pnl = (exit_p-entry)*size if s==1 else (entry-exit_p)*size
                pnl -= entry*size*fee*2
                cap += pnl
                total += 1
                if hit_tp: wins += 1
                bars_held += (j-i)
                if pnl > 0: gross_profit += pnl
                else: gross_loss += abs(pnl)
                if cap > pk: pk = cap
                dd = (pk-cap)/pk*100 if pk>0 else 0
                if dd > max_dd: max_dd = dd
                if cap <= 0: i = N; break
                if cap > cap_max: cap = cap_max
                i = j+1; closed = True; break
        if not closed:
            exit_j = min(i+hold_hours, N-1)
            exit_p = cl[exit_j]
            pnl = (exit_p-entry)*size if s==1 else (entry-exit_p)*size
            pnl -= entry*size*fee*2
            cap += pnl
            total += 1
            if pnl > 0: wins += 1; gross_profit += pnl
            else: gross_loss += abs(pnl)
            bars_held += (exit_j-i)
            if cap > pk: pk = cap
            dd = (pk-cap)/pk*100 if pk>0 else 0
            if dd > max_dd: max_dd = dd
            if cap > cap_max: cap = cap_max
            if cap <= 0: break
            i = exit_j+1
    wr = wins/total*100 if total>0 else 0
    pf = gross_profit/gross_loss if gross_loss>0 else float('inf')
    return {
        'cap': round(cap,2), 'pk': round(pk,2), 'dd': round(max_dd,1),
        'trades': total, 'wins': wins, 'losses': total-wins,
        'wr': round(wr,1), 'pf': round(pf,2),
        'skipped_vol': skipped_vol,
    }

TP = 0.002
SL = 0.002
SEEDS = [random.randint(0,99999) for _ in range(10)]

# ============================================================
# TEST 1: No gate (baseline)
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 1: BASELINE (no volatility gate) | 20x 5% | 2021-2026")
print(f"{'='*80}")
results_base = []
for seed_idx, seed in enumerate(SEEDS):
    random.seed(seed)
    sig = gen_mom6_2pct(random.randint(0,99))
    r = bt(sig, TP, SL, 0.05, 20, 8)
    results_base.append(r)
    print(f"  Seed {seed_idx+1:2d}: {r['trades']:5d} trades | WR={r['wr']:5.1f}% | PF={r['pf']:5.2f} | Cap=${r['cap']:>10,.2f} | DD={r['dd']:5.1f}%")
avg = lambda k: sum(r[k] for r in results_base)/len(results_base)
print(f"  AVG: {avg('trades'):.0f} trades | WR={avg('wr'):.1f}% | PF={avg('pf'):.2f} | Cap=${avg('cap'):,.0f} | DD={avg('dd'):.1f}%")

# ============================================================
# TEST 2: Volatility gate sweep (48h window, various thresholds)
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 2: VOLATILITY GATE SWEEP (48h avg abs 12h mom)")
print(f"{'='*80}")
print(f"{'Threshold':>10} {'AvgTr':>6} {'AvgWR':>6} {'AvgPF':>6} {'AvgDD':>6} {'AvgCap':>12} {'MinCap':>12} {'MaxCap':>12} {'Skipped':>8}")
print("-"*85)

for threshold_pct in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    threshold = threshold_pct / 100
    results = []
    for seed in SEEDS:
        random.seed(seed)
        sig = gen_mom6_2pct(random.randint(0,99))
        r = bt(sig, TP, SL, 0.05, 20, 8, vol_gate_arr=vol_gate_48, vol_gate_threshold=threshold)
        results.append(r)
    a_wr = sum(r['wr'] for r in results)/len(results)
    a_pf = sum(r['pf'] for r in results)/len(results)
    a_tr = sum(r['trades'] for r in results)/len(results)
    a_dd = sum(r['dd'] for r in results)/len(results)
    a_cap = sum(r['cap'] for r in results)/len(results)
    m_cap = min(r['cap'] for r in results)
    x_cap = max(r['cap'] for r in results)
    a_skip = sum(r['skipped_vol'] for r in results)/len(results)
    print(f"{threshold_pct:>9.1f}% {a_tr:>6.0f} {a_wr:>5.1f}% {a_pf:>6.2f} {a_dd:>5.1f}% ${a_cap:>10,.0f} ${m_cap:>10,.0f} ${x_cap:>10,.0f} {a_skip:>7.0f}")

# ============================================================
# TEST 3: Different gate windows (24h, 48h, 72h) at 2% threshold
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 3: GATE WINDOW COMPARISON (threshold=2.0%)")
print(f"{'='*80}")

for gate_name, gate_arr in [("None", None), ("24h", vol_gate_24), ("48h", vol_gate_48), ("72h", vol_gate_72)]:
    results = []
    for seed in SEEDS:
        random.seed(seed)
        sig = gen_mom6_2pct(random.randint(0,99))
        r = bt(sig, TP, SL, 0.05, 20, 8, vol_gate_arr=gate_arr, vol_gate_threshold=0.02 if gate_arr else 0)
        results.append(r)
    a_wr = sum(r['wr'] for r in results)/len(results)
    a_pf = sum(r['pf'] for r in results)/len(results)
    a_tr = sum(r['trades'] for r in results)/len(results)
    a_dd = sum(r['dd'] for r in results)/len(results)
    a_cap = sum(r['cap'] for r in results)/len(results)
    a_skip = sum(r['skipped_vol'] for r in results)/len(results)
    print(f"  Gate={gate_name:>4}: {a_tr:>5.0f} trades | WR={a_wr:.1f}% | PF={a_pf:.2f} | DD={a_dd:.1f}% | Cap=${a_cap:>10,.0f} | Skipped={a_skip:.0f}")

# ============================================================
# TEST 4: Leverage sweep WITH best volatility gate
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 4: LEVERAGE SWEEP + 48h 2% VOL GATE")
print(f"{'='*80}")
print(f"{'Lev':>4} {'Risk':>5} {'AvgTr':>6} {'AvgWR':>6} {'AvgPF':>6} {'AvgDD':>6} {'AvgCap':>12} {'MinCap':>12} {'MaxCap':>12} {'Surv%':>5}")
print("-"*80)
for lev in [20, 30, 50, 75, 100]:
    for risk in [0.05, 0.10, 0.15, 0.20]:
        results = []
        for seed in SEEDS:
            random.seed(seed)
            sig = gen_mom6_2pct(random.randint(0,99))
            r = bt(sig, TP, SL, risk, lev, 8, vol_gate_arr=vol_gate_48, vol_gate_threshold=0.02)
            results.append(r)
        a_wr = sum(r['wr'] for r in results)/len(results)
        a_pf = sum(r['pf'] for r in results)/len(results)
        a_tr = sum(r['trades'] for r in results)/len(results)
        a_dd = sum(r['dd'] for r in results)/len(results)
        a_cap = sum(r['cap'] for r in results)/len(results)
        m_cap = min(r['cap'] for r in results)
        x_cap = max(r['cap'] for r in results)
        survived = sum(1 for r in results if r['cap'] > 200) / len(results) * 100
        print(f"{lev:>4}x {risk*100:>4.0f}% {a_tr:>6.0f} {a_wr:>5.1f}% {a_pf:>6.2f} {a_dd:>5.1f}% ${a_cap:>10,.0f} ${m_cap:>10,.0f} ${x_cap:>10,.0f} {survived:>4.0f}%")

# ============================================================
# TEST 5: Monthly breakdown - baseline vs best gate
# ============================================================
print(f"\n{'='*80}")
print(f"TEST 5: MONTHLY COMPARISON (seed=42, 20x 5%)")
print(f"{'='*80}")

def monthly_bt(vol_gate_arr=None, vol_gate_threshold=0):
    random.seed(42)
    sig = gen_mom6_2pct(0)
    monthly = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0, 'cap_end': 0, 'skipped': 0})
    cap = 200.0
    pk = cap
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0:
            i += 1
            continue
        if i+1 >= N: break
        mk = datetime.fromtimestamp(raw[i][0]/1000, tz=timezone.utc).strftime('%Y-%m')
        if monthly[mk]['cap_end'] == 0:
            monthly[mk]['cap_end'] = cap
        # Vol gate
        if vol_gate_arr is not None and vol_gate_threshold > 0:
            vg = vol_gate_arr[i]
            if vg is not None and vg < vol_gate_threshold:
                monthly[mk]['skipped'] += 1
                i += 1
                continue
        if s == 1:
            entry = o[i+1]*1.001; tp_p = entry*1.002; sl_p = entry*0.998
        else:
            entry = o[i+1]*0.999; tp_p = entry*0.998; sl_p = entry*1.002
        sl_dist = abs(entry - sl_p)
        if sl_dist == 0: i += 1; continue
        size = min(cap*0.05/sl_dist, cap*20/entry)
        if size <= 0: i += 1; continue
        closed = False
        for j in range(i+1, min(i+9, N)):
            hit_tp = hit_sl = False
            exit_p = 0
            if s == 1:
                if hi[j] >= tp_p: hit_tp = True; exit_p = tp_p
                elif lo[j] <= sl_p: hit_sl = True; exit_p = sl_p
            else:
                if lo[j] <= tp_p: hit_tp = True; exit_p = tp_p
                elif hi[j] >= sl_p: hit_sl = True; exit_p = sl_p
            if hit_tp or hit_sl:
                pnl = (exit_p-entry)*size if s==1 else (entry-exit_p)*size
                pnl -= entry*size*0.0002*2
                cap += pnl
                monthly[mk]['trades'] += 1
                monthly[mk]['wins'] += int(hit_tp)
                monthly[mk]['pnl'] += pnl
                if cap > pk: pk = cap
                if cap <= 0: i = N; break
                if cap > 100000: cap = 100000
                i = j+1; closed = True; break
        if not closed:
            j = min(i+8, N-1)
            exit_p = cl[j]
            pnl = (exit_p-entry)*size if s==1 else (entry-exit_p)*size
            pnl -= entry*size*0.0002*2
            cap += pnl
            monthly[mk]['trades'] += 1
            monthly[mk]['wins'] += int(pnl > 0)
            monthly[mk]['pnl'] += pnl
            if cap > pk: pk = cap
            if cap > 100000: cap = 100000
            i = j+1
        monthly[mk]['cap_end'] = cap
    return monthly, cap, pk

m_base, c_base, p_base = monthly_bt()
m_gate, c_gate, p_gate = monthly_bt(vol_gate_48, 0.02)

print(f"{'Month':>8} | {'BASE Cap':>9} {'Tr':>4} {'WR%':>5} | {'GATE Cap':>9} {'Tr':>4} {'WR%':>5} {'Skip':>5} | {'Diff':>9}")
print("-"*80)
for mk in sorted(set(list(m_base.keys()) + list(m_gate.keys()))):
    b = m_base[base_key if (base_key := mk) in m_base else mk]
    g = m_gate[mk]
    b_wr = b['wins']/b['trades']*100 if b['trades'] > 0 else 0
    g_wr = g['wins']/g['trades']*100 if g['trades'] > 0 else 0
    diff = g['cap_end'] - b['cap_end']
    b_cap = f"${b['cap_end']:>8,.0f}" if b['cap_end'] > 0 else "      -"
    g_cap = f"${g['cap_end']:>8,.0f}" if g['cap_end'] > 0 else "      -"
    print(f"{mk:>8} | {b_cap} {b['trades']:>4} {b_wr:>5.1f}% | {g_cap} {g['trades']:>4} {g_wr:>5.1f}% {g['skipped']:>5} | ${diff:>+8,.0f}")

print(f"\n  BASE: Final=${c_base:,.0f} Peak=${p_base:,.0f}")
print(f"  GATE: Final=${c_gate:,.0f} Peak=${p_gate:,.0f}")

print(f"\nCompleted in {time.time()-t0:.1f}s")
