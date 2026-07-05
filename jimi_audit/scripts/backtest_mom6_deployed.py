#!/usr/bin/env python3
"""Backtest mom6_2pct: TP=0.2% SL=0.2% 100x 20% risk - 10 seeds, 2017-2026"""
import json, time, random, sys
from datetime import datetime, timezone
from collections import defaultdict

t0 = time.time()
random.seed(42)

with open('/root/.openclaw/workspace/jimi_audit/data/eth_full_1h.json') as f:
    raw = json.load(f)
N = len(raw)
o = [float(c[1]) for c in raw]
hi = [float(c[2]) for c in raw]
lo = [float(c[3]) for c in raw]
cl = [float(c[4]) for c in raw]
vol = [float(c[5]) for c in raw]
print(f'{N} candles: {datetime.fromtimestamp(raw[0][0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")} to {datetime.fromtimestamp(raw[-1][0]/1000,tz=timezone.utc).strftime("%Y-%m-%d")}')
print(f'Price: ${cl[0]:.0f} -> ${cl[-1]:.0f}, range ${min(lo):.0f} - ${max(hi):.0f}')

# Momentum arrays
print("Computing momentum...", end=" "); sys.stdout.flush()
mom6 = [None]*N
for i in range(6, N):
    if cl[i-6] > 0:
        mom6[i] = (cl[i] - cl[i-6]) / cl[i-6]
print(f"done in {time.time()-t0:.1f}s")

# ATR for filtering
atr_pct = [0.0]*N
tr = [0.0]*N
for i in range(1, N):
    tr[i] = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
atr14 = [0.0]*N
atr14[14] = sum(tr[1:15])/14
for i in range(15, N):
    atr14[i] = (atr14[i-1]*13 + tr[i])/14
for i in range(N):
    atr_pct[i] = atr14[i]/cl[i]*100 if cl[i] > 0 else 0

def gen_mom6_2pct(offset=0):
    sig = [None]*N
    for i in range(6+offset, N):
        m = mom6[i]
        if m is not None:
            if m > 0.02: sig[i] = 1
            elif m < -0.02: sig[i] = -1
    return sig

def bt(sig, tp_pct, sl_pct, risk_pct, leverage, hold_hours=8, atr_filter=0, init=200, fee=0.0002, slip=0.001, cap_max=100000):
    cap = float(init)
    pk = cap
    max_dd = 0.0
    wins = 0
    total = 0
    bars_held = 0
    gross_profit = 0.0
    gross_loss = 0.0
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0:
            i += 1
            continue
        if i+1 >= N:
            break
        if atr_filter > 0:
            ap = atr_pct[i]
            if ap is not None and ap < atr_filter:
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
            hit_tp = False
            hit_sl = False
            exit_p = 0.0
            if s == 1:
                if hi[j] >= tp_price:
                    hit_tp = True
                    exit_p = tp_price
                elif lo[j] <= sl_price:
                    hit_sl = True
                    exit_p = sl_price
            else:
                if lo[j] <= tp_price:
                    hit_tp = True
                    exit_p = tp_price
                elif hi[j] >= sl_price:
                    hit_sl = True
                    exit_p = sl_price
            if hit_tp or hit_sl:
                if s == 1:
                    pnl = (exit_p - entry) * size
                else:
                    pnl = (entry - exit_p) * size
                pnl -= entry * size * fee * 2
                cap += pnl
                total += 1
                if hit_tp:
                    wins += 1
                bars_held += (j - i)
                if pnl > 0:
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
                if cap > pk:
                    pk = cap
                dd = (pk - cap) / pk * 100 if pk > 0 else 0
                if dd > max_dd:
                    max_dd = dd
                if cap <= 0:
                    i = N
                    break
                if cap > cap_max:
                    cap = cap_max
                i = j + 1
                closed = True
                break
        if not closed:
            exit_j = min(i + hold_hours, N-1)
            exit_p = cl[exit_j]
            if s == 1:
                pnl = (exit_p - entry) * size
            else:
                pnl = (entry - exit_p) * size
            pnl -= entry * size * fee * 2
            cap += pnl
            total += 1
            if pnl > 0:
                wins += 1
                gross_profit += pnl
            else:
                gross_loss += abs(pnl)
            bars_held += (exit_j - i)
            if cap > pk:
                pk = cap
            dd = (pk - cap) / pk * 100 if pk > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if cap > cap_max:
                cap = cap_max
            if cap <= 0:
                break
            i = exit_j + 1
    wr = wins/total*100 if total > 0 else 0
    pf = gross_profit/gross_loss if gross_loss > 0 else float('inf')
    avg_hold = bars_held/total if total > 0 else 0
    return {
        'cap': round(cap, 2), 'pk': round(pk, 2), 'dd': round(max_dd, 1),
        'trades': total, 'wins': wins, 'losses': total-wins,
        'wr': round(wr, 1), 'pf': round(pf, 2), 'avg_hold': round(avg_hold, 1),
        'gross_p': round(gross_profit, 2), 'gross_l': round(gross_loss, 2),
    }

TP = 0.002
SL = 0.002
LEV = 100
RISK = 0.20
HOLD = 8
SEEDS = [random.randint(0, 99999) for _ in range(10)]

print(f"\n{'='*70}")
print(f"BACKTEST: mom6_2pct | TP=0.20% SL=0.20% | 100x | 20% risk | 8h hold")
print(f"Signal: 6h momentum > 2% LONG, < -2% SHORT")
print(f"{'='*70}")

results = []
for seed_idx, seed in enumerate(SEEDS):
    random.seed(seed)
    offset = random.randint(0, 99)
    sig = gen_mom6_2pct(offset)
    sig_count = sum(1 for s in sig if s is not None)
    r = bt(sig, TP, SL, RISK, LEV, HOLD)
    results.append(r)
    print(f"  Seed {seed_idx+1:2d} (off={offset:2d}): {sig_count:6d} signals | {r['trades']:5d} trades | WR={r['wr']:5.1f}% | PF={r['pf']:5.2f} | Cap=${r['cap']:>10,.2f} | DD={r['dd']:5.1f}%")

print(f"\n{'='*70}")
print(f"AGGREGATE (10 seeds)")
print(f"{'='*70}")
avg_wr = sum(r['wr'] for r in results)/len(results)
avg_pf = sum(r['pf'] for r in results)/len(results)
avg_trades = sum(r['trades'] for r in results)/len(results)
avg_dd = sum(r['dd'] for r in results)/len(results)
avg_cap = sum(r['cap'] for r in results)/len(results)
min_pf = min(r['pf'] for r in results)
max_pf = max(r['pf'] for r in results)
min_cap = min(r['cap'] for r in results)
max_cap = max(r['cap'] for r in results)
print(f"  Avg WR: {avg_wr:.1f}%")
print(f"  Avg PF: {avg_pf:.2f} (min={min_pf:.2f} max={max_pf:.2f})")
print(f"  Avg Trades: {avg_trades:.0f}")
print(f"  Avg DD: {avg_dd:.1f}%")
print(f"  Avg Capital: ${avg_cap:,.2f} (min=${min_cap:,.2f} max=${max_cap:,.2f})")

# Param sweep
print(f"\n{'='*70}")
print(f"PARAMETER SWEEP: TP=0.20% SL=0.20%")
print(f"{'='*70}")
print(f"{'Lev':>4} {'Risk':>5} {'AvgWR':>6} {'AvgPF':>6} {'AvgTr':>6} {'AvgDD':>6} {'AvgCap':>12} {'MinCap':>12} {'MaxCap':>12}")
print("-"*75)
for lev in [20, 50, 75, 100]:
    for risk in [0.05, 0.10, 0.15, 0.20]:
        sr = []
        for seed in SEEDS:
            random.seed(seed)
            sig = gen_mom6_2pct(random.randint(0, 99))
            sr.append(bt(sig, TP, SL, risk, lev, HOLD))
        a_wr = sum(r['wr'] for r in sr)/len(sr)
        a_pf = sum(r['pf'] for r in sr)/len(sr)
        a_tr = sum(r['trades'] for r in sr)/len(sr)
        a_dd = sum(r['dd'] for r in sr)/len(sr)
        a_cap = sum(r['cap'] for r in sr)/len(sr)
        m_cap = min(r['cap'] for r in sr)
        x_cap = max(r['cap'] for r in sr)
        print(f"{lev:>4}x {risk*100:>4.0f}% {a_wr:>5.1f}% {a_pf:>6.2f} {a_tr:>6.0f} {a_dd:>5.1f}% ${a_cap:>10,.0f} ${m_cap:>10,.0f} ${x_cap:>10,.0f}")

# Monthly breakdown
print(f"\n{'='*70}")
print(f"MONTHLY BREAKDOWN: mom6_2pct 100x 20% (seed=42)")
print(f"{'='*70}")
random.seed(42)
sig = gen_mom6_2pct(0)
monthly = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0, 'cap_end': 0})
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
    if s == 1:
        entry = o[i+1]*1.001
        tp_p = entry*1.002
        sl_p = entry*0.998
    else:
        entry = o[i+1]*0.999
        tp_p = entry*0.998
        sl_p = entry*1.002
    sl_dist = abs(entry - sl_p)
    if sl_dist == 0: i += 1; continue
    size = min(cap*0.20/sl_dist, cap*100/entry)
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

print(f"{'Month':>8} {'Trades':>6} {'Wins':>5} {'WR%':>5} {'PnL$':>10} {'Cap End':>10}")
print("-"*55)
for mk in sorted(monthly.keys()):
    m = monthly[mk]
    if m['trades'] == 0: continue
    wr = m['wins']/m['trades']*100
    print(f"{mk:>8} {m['trades']:>6} {m['wins']:>5} {wr:>5.1f}% ${m['pnl']:>9,.2f} ${m['cap_end']:>9,.2f}")

print(f"\nFinal capital: ${cap:,.2f}")
print(f"Peak capital: ${pk:,.2f}")
print(f"Completed in {time.time()-t0:.1f}s")
