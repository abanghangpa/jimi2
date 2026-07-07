#!/usr/bin/env python3
"""
Optimize BB+mom6 for $200 → $2500/mo withdrawal.
No signal randomization — clean backtest matching bb_full_test.py methodology.
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

print("Computing indicators...", end=" "); sys.stdout.flush()

def sma(data, p):
    s = [None]*N
    for i in range(p-1, N): s[i] = sum(data[i-p+1:i+1])/p
    return s

# BB(20,2.0)
bb_mid = sma(cl, 20)
bb_up = [None]*N; bb_lo = [None]*N
for i in range(19, N):
    seg = cl[i-19:i+1]; m = bb_mid[i]
    std = (sum((x-m)**2 for x in seg)/20)**0.5
    bb_up[i] = m + 2*std
    bb_lo[i] = m - 2*std

# 12h momentum
mom12 = [None]*N
for i in range(12, N):
    if cl[i-12] > 0: mom12[i] = (cl[i]-cl[i-12])/cl[i-12]

# 48h vol gate
vol_gate_48 = [None]*N
buf = []
for i in range(N):
    if mom12[i] is not None: buf.append(abs(mom12[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate_48[i] = sum(buf)/len(buf)

# mom6
mom6 = [None]*N
for i in range(6, N):
    if cl[i-6] > 0: mom6[i] = (cl[i]-cl[i-6])/cl[i-6]

# ATR14
tr = [0]*N
for i in range(1, N):
    tr[i] = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
atr14 = [None]*N
for i in range(14, N):
    atr14[i] = sum(tr[i-13:i+1])/14

# RSI14
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

# EMA 50/200
def ema(data, p):
    e = [None]*N
    k = 2/(p+1)
    e[p-1] = sum(data[:p])/p
    for i in range(p, N):
        e[i] = data[i]*k + e[i-1]*(1-k)
    return e
ema50 = ema(cl, 50)
ema200 = ema(cl, 200)

# 1h momentum
mom1h = [None]*N
for i in range(1, N):
    if cl[i-1] > 0: mom1h[i] = (cl[i]-cl[i-1])/cl[i-1]

print(f"done in {time.time()-t0:.1f}s")

# === SIGNALS ===
def gen_bb():
    """BB only: price < lower = LONG, price > upper = SHORT"""
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1
            elif cl[i] > bb_up[i]: sig[i] = -1
    return sig

def gen_bb_mom6():
    """BB OR mom6 combined"""
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1; continue
            if cl[i] > bb_up[i]: sig[i] = -1; continue
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

def gen_bb_mom6_rsi():
    """BB + mom6 + RSI confirmation"""
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None and rsi14[i] is not None:
            if cl[i] < bb_lo[i] and rsi14[i] < 40: sig[i] = 1; continue
            if cl[i] > bb_up[i] and rsi14[i] > 60: sig[i] = -1; continue
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

def gen_bb_mom6_trend():
    """BB + mom6 + EMA200 trend filter"""
    sig = [None]*N
    for i in range(200, N):
        if bb_lo[i] is not None and ema200[i] is not None:
            if cl[i] < bb_lo[i] and cl[i] > ema200[i]: sig[i] = 1; continue
            if cl[i] > bb_up[i] and cl[i] < ema200[i]: sig[i] = -1; continue
        if mom6[i] is not None and ema200[i] is not None:
            if mom6[i] > 0.02 and cl[i] > ema200[i]: sig[i] = 1
            elif mom6[i] < -0.02 and cl[i] < ema200[i]: sig[i] = -1
    return sig

def gen_bb_mom6_rsi_trend():
    """All filters combined"""
    sig = [None]*N
    for i in range(200, N):
        if bb_lo[i] is not None and rsi14[i] is not None and ema200[i] is not None:
            if cl[i] < bb_lo[i] and rsi14[i] < 40 and cl[i] > ema200[i]: sig[i] = 1; continue
            if cl[i] > bb_up[i] and rsi14[i] > 60 and cl[i] < ema200[i]: sig[i] = -1; continue
        if mom6[i] is not None and ema200[i] is not None:
            if mom6[i] > 0.02 and cl[i] > ema200[i]: sig[i] = 1
            elif mom6[i] < -0.02 and cl[i] < ema200[i]: sig[i] = -1
    return sig

def gen_mom6_only():
    """Pure momentum signal"""
    sig = [None]*N
    for i in range(6, N):
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

def gen_bb_rsi():
    """BB + RSI only (no mom6)"""
    sig = [None]*N
    for i in range(20, N):
        if bb_lo[i] is not None and rsi14[i] is not None:
            if cl[i] < bb_lo[i] and rsi14[i] < 35: sig[i] = 1
            elif cl[i] > bb_up[i] and rsi14[i] > 65: sig[i] = -1
    return sig

# === BACKTEST ENGINE (matches bb_full_test.py exactly) ===
def bt(sig, tp, sl, risk, lev, hold, gate_arr=None, gate_thresh=0, init=200, fee=0.0002, slip=0.001,
       simulate_wd=False, wd_target=2700, wd_amount=2500, wd_keep=200):
    """Clean backtest — no randomization, entry at next-bar open."""
    cap = float(init); pk = cap; max_dd = 0.0; wins = 0; total = 0
    gross_p = 0.0; gross_l = 0.0; skipped = 0
    withdrawals = []; first_target = None
    monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0})
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0: i += 1; continue
        if i+1 >= N: break
        # Vol gate check
        if gate_arr is not None and gate_thresh > 0:
            g = gate_arr[i]
            if g is not None and g < gate_thresh:
                skipped += 1; i += 1; continue
        # Direction
        direction = 'LONG' if s == 1 else 'SHORT'
        # Entry at next bar open
        entry = o[i+1]
        if entry <= 0: i += 1; continue
        # Position sizing (risk-based)
        risk_amt = cap * risk
        if sl <= 0: i += 1; continue
        size_usd = risk_amt / (sl * lev)
        if size_usd < 1: i += 1; continue
        # TP/SL prices
        if direction == 'LONG':
            tp_price = entry * (1 + tp)
            sl_price = entry * (1 - sl)
        else:
            tp_price = entry * (1 - tp)
            sl_price = entry * (1 + sl)
        # Check bars
        closed = False
        for j in range(i+2, min(i+2+hold, N)):
            h = hi[j]; l_ = lo[j]
            if direction == 'LONG':
                if l_ <= sl_price:
                    exit_p = sl_price * (1 - slip)
                    pnl = (exit_p - entry) / entry * size_usd * lev - size_usd * fee * 2
                    cap += pnl; total += 1
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    closed = True; break
                if h >= tp_price:
                    exit_p = tp_price * (1 - slip)
                    pnl = (exit_p - entry) / entry * size_usd * lev - size_usd * fee * 2
                    cap += pnl; total += 1
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    closed = True; break
            else:
                if h >= sl_price:
                    exit_p = sl_price * (1 + slip)
                    pnl = (entry - exit_p) / entry * size_usd * lev - size_usd * fee * 2
                    cap += pnl; total += 1
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    closed = True; break
                if l_ <= tp_price:
                    exit_p = tp_price * (1 + slip)
                    pnl = (entry - exit_p) / entry * size_usd * lev - size_usd * fee * 2
                    cap += pnl; total += 1
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    closed = True; break
        if not closed:
            # Timeout exit at close of hold bar
            exit_idx = min(i+1+hold, N-1)
            exit_p = cl[exit_idx]
            if direction == 'LONG':
                pnl = (exit_p - entry) / entry * size_usd * lev - size_usd * fee * 2
            else:
                pnl = (entry - exit_p) / entry * size_usd * lev - size_usd * fee * 2
            cap += pnl; total += 1
            if pnl > 0: wins += 1; gross_p += pnl
            else: gross_l += abs(pnl)
        # Monthly tracking
        dt = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc)
        mk = f"{dt.year}-{dt.month:02d}"
        monthly[mk]['trades'] += 1
        monthly[mk]['pnl'] += pnl
        if pnl > 0: monthly[mk]['wins'] += 1
        # Peak/DD
        if cap > pk: pk = cap
        dd = (pk - cap) / pk if pk > 0 else 0
        if dd > max_dd: max_dd = dd
        # Withdrawal
        if simulate_wd and cap >= wd_target:
            if first_target is None: first_target = dt.strftime('%Y-%m-%d')
            withdrawals.append({'date': dt.strftime('%Y-%m-%d'), 'amount': wd_amount, 'cap_before': cap})
            cap -= wd_amount
            if cap < wd_keep: cap = wd_keep
        i += 1
    wr = wins/total*100 if total > 0 else 0
    pf = gross_p/gross_l if gross_l > 0 else 999
    total_wd = sum(w['amount'] for w in withdrawals)
    return {
        'final': cap, 'wr': wr, 'pf': pf, 'dd': max_dd*100, 'trades': total,
        'wins': wins, 'skipped': skipped, 'withdrawals': withdrawals,
        'total_withdrawn': total_wd, 'first_target': first_target, 'monthly': dict(monthly)
    }

# === TEST MATRIX ===
SEEDS = list(range(50))

signals = {
    'bb': gen_bb(),
    'bb_mom6': gen_bb_mom6(),
    'bb_mom6_rsi': gen_bb_mom6_rsi(),
    'bb_mom6_trend': gen_bb_mom6_trend(),
    'bb_mom6_rsi_trend': gen_bb_mom6_rsi_trend(),
    'mom6_only': gen_mom6_only(),
    'bb_rsi': gen_bb_rsi(),
}

configs = [
    # name, tp, sl, risk, lev, hold, gate, signal
    # === REPLICATE EXACT bb_full_test.py RESULTS ===
    ("bb_gate2pct_tp0.3_sl0.2", 0.003, 0.002, 0.05, 20, 8, 0.02, 'bb'),
    ("bb_mom6_gate2pct_tp0.3_sl0.2", 0.003, 0.002, 0.05, 20, 8, 0.02, 'bb_mom6'),
    # === NO GATE VARIANTS ===
    ("bb_nogate_tp0.3_sl0.2", 0.003, 0.002, 0.05, 20, 8, 0, 'bb'),
    ("bb_mom6_nogate_tp0.3_sl0.2", 0.003, 0.002, 0.05, 20, 8, 0, 'bb_mom6'),
    # === LOWER GATES ===
    ("bb_mom6_gate0.5pct", 0.003, 0.002, 0.05, 20, 8, 0.005, 'bb_mom6'),
    ("bb_mom6_gate1pct", 0.003, 0.002, 0.05, 20, 8, 0.01, 'bb_mom6'),
    ("bb_mom6_gate1.5pct", 0.003, 0.002, 0.05, 20, 8, 0.015, 'bb_mom6'),
    # === AGGRESSIVE RISK ===
    ("bb_mom6_risk10", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk15", 0.003, 0.002, 0.15, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk20", 0.003, 0.002, 0.20, 20, 8, 0, 'bb_mom6'),
    ("bb_mom6_risk25", 0.003, 0.002, 0.25, 20, 8, 0, 'bb_mom6'),
    # === HIGHER LEVERAGE ===
    ("bb_mom6_lev25_risk10", 0.003, 0.002, 0.10, 25, 8, 0, 'bb_mom6'),
    ("bb_mom6_lev30_risk10", 0.003, 0.002, 0.10, 30, 8, 0, 'bb_mom6'),
    ("bb_mom6_lev25_risk15", 0.003, 0.002, 0.15, 25, 8, 0, 'bb_mom6'),
    # === WIDER TP ===
    ("bb_mom6_tp0.5_sl0.3", 0.005, 0.003, 0.10, 20, 12, 0, 'bb_mom6'),
    ("bb_mom6_tp0.5_sl0.2", 0.005, 0.002, 0.10, 20, 12, 0, 'bb_mom6'),
    ("bb_mom6_tp0.8_sl0.4", 0.008, 0.004, 0.10, 20, 24, 0, 'bb_mom6'),
    ("bb_mom6_tp1.0_sl0.5", 0.010, 0.005, 0.10, 20, 48, 0, 'bb_mom6'),
    # === TIGHT TP (more trades) ===
    ("bb_mom6_tp0.2_sl0.15", 0.002, 0.0015, 0.10, 20, 4, 0, 'bb_mom6'),
    ("bb_mom6_tp0.15_sl0.1", 0.0015, 0.001, 0.10, 20, 2, 0, 'bb_mom6'),
    # === ALTERNATIVE SIGNALS ===
    ("bb_rsi_nogate", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_rsi'),
    ("bb_mom6_rsi_nogate", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6_rsi'),
    ("bb_mom6_trend_nogate", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6_trend'),
    ("bb_mom6_rsi_trend", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6_rsi_trend'),
    ("mom6_only_nogate", 0.003, 0.002, 0.10, 20, 8, 0, 'mom6_only'),
    # === BEST COMBOS WITH GATE ===
    ("bb_mom6_risk10_gate2pct", 0.003, 0.002, 0.10, 20, 8, 0.02, 'bb_mom6'),
    ("bb_mom6_risk10_gate1pct", 0.003, 0.002, 0.10, 20, 8, 0.01, 'bb_mom6'),
    ("bb_mom6_lev25_risk10_gate2pct", 0.003, 0.002, 0.10, 25, 8, 0.02, 'bb_mom6'),
    # === YOLO COMBOS ===
    ("yolo_lev25_risk20_wide", 0.005, 0.003, 0.20, 25, 12, 0, 'bb_mom6'),
    ("yolo_lev30_risk25_wide", 0.005, 0.003, 0.25, 30, 12, 0, 'bb_mom6'),
    ("yolo_lev25_risk15_tp0.5", 0.005, 0.002, 0.15, 25, 12, 0, 'bb_mom6'),
]

print(f"\nRunning {len(configs)} configs × {len(SEEDS)} seeds = {len(configs)*len(SEEDS)} backtests...")
print("="*120)

results = []
for ci, (name, tp, sl, risk, lev, hold, gate_t, sig_name) in enumerate(configs):
    sig = signals[sig_name]
    gate_arr = vol_gate_48 if gate_t > 0 else None
    caps = []; wrs = []; pfs = []; dds = []; trade_counts = []
    wd_totals = []; first_wds = []

    for seed in SEEDS:
        random.seed(seed)
        r = bt(sig, tp, sl, risk, lev, hold, gate_arr, gate_t,
               simulate_wd=True, wd_target=2700, wd_amount=2500, wd_keep=200)
        caps.append(r['final'] + r['total_withdrawn'])
        wrs.append(r['wr']); pfs.append(r['pf']); dds.append(r['dd'])
        trade_counts.append(r['trades'])
        wd_totals.append(r['total_withdrawn'])
        if r['first_target']: first_wds.append(r['first_target'])

    avg_cap = sum(caps)/len(caps)
    avg_wr = sum(wrs)/len(wrs)
    avg_pf = sum(pfs)/len(pfs)
    avg_dd = sum(dds)/len(dds)
    avg_trades = sum(trade_counts)/len(trade_counts)
    avg_wd = sum(wd_totals)/len(wd_totals)
    hit_rate = len(first_wds)/len(SEEDS)*100
    median_cap = sorted(caps)[len(caps)//2]
    min_cap = min(caps)

    results.append({
        'name': name, 'tp': tp, 'sl': sl, 'risk': risk, 'lev': lev, 'hold': hold,
        'gate': gate_t, 'sig': sig_name,
        'avg_cap': avg_cap, 'median_cap': median_cap, 'min_cap': min_cap,
        'avg_wr': avg_wr, 'avg_pf': avg_pf, 'avg_dd': avg_dd,
        'avg_trades': avg_trades, 'avg_wd': avg_wd, 'hit_rate': hit_rate,
        'targets_hit': len(first_wds), 'first_wd': sorted(first_wds)[:3] if first_wds else []
    })

    status = f"[{ci+1:2d}/{len(configs)}] {name:<40} WR={avg_wr:5.1f}% PF={avg_pf:5.2f} DD={avg_dd:5.1f}% Trades={avg_trades:5.0f} WD=${avg_wd:>8,.0f} Hit={hit_rate:4.0f}% AvgCap=${avg_cap:>10,.0f}"
    print(status)

# Sort by avg_wd
results.sort(key=lambda x: x['avg_wd'], reverse=True)

print("\n" + "="*120)
print("TOP 15 CONFIGS BY TOTAL WITHDRAWN")
print("="*120)
print(f"{'Config':<40} {'WR%':>6} {'PF':>6} {'DD%':>6} {'Trades':>7} {'AvgWD$':>10} {'Hit%':>6} {'AvgCap$':>12} {'1stWD':>12}")
print("-"*120)
for r in results[:15]:
    first = r['first_wd'][0] if r['first_wd'] else 'N/A'
    print(f"{r['name']:<40} {r['avg_wr']:>5.1f}% {r['avg_pf']:>5.2f} {r['avg_dd']:>5.1f}% {r['avg_trades']:>6.0f} {r['avg_wd']:>9,.0f} {r['hit_rate']:>5.0f}% ${r['avg_cap']:>10,.0f} {first:>12}")

# Save
output = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'target': '$2500/month withdrawal from $200 capital',
    'data': f'{N} candles 2021-2026, 50 seeds',
    'results': results
}
with open('/root/.openclaw/workspace/jimi_audit/data/optimization_v2.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s")
