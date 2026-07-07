#!/usr/bin/env python3
"""
Optimize BB+mom6 for $200 → $2500/mo withdrawal target.
Tests: vol gate thresholds, TP/SL combos, leverage, risk %, strategy combos.
50-seed Monte Carlo with withdrawal simulation.
"""
import json, time, random, sys, math
from datetime import datetime, timezone
from collections import defaultdict

t0 = time.time()

with open('/root/.openclaw/workspace/jimi_audit/data/eth_full_1h.json') as f:
    raw_full = json.load(f)

# Use 2021-2026 data
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

vol_gate = [None]*N
buf = []
for i in range(N):
    if mom12[i] is not None: buf.append(abs(mom12[i]))
    if len(buf) > 48: buf.pop(0)
    if len(buf) >= 48: vol_gate[i] = sum(buf)/len(buf)

# mom6 for combined strategy
mom6 = [None]*N
for i in range(6, N):
    if cl[i-6] > 0: mom6[i] = (cl[i]-cl[i-6])/cl[i-6]

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

# EMA50, EMA200 for trend filter
def ema(data, p):
    e = [None]*N
    k = 2/(p+1)
    e[p-1] = sum(data[:p])/p
    for i in range(p, N):
        e[i] = data[i]*k + e[i-1]*(1-k)
    return e

ema50 = ema(cl, 50)
ema200 = ema(cl, 200)

# ATR14 for dynamic TP/SL
tr = [0]*N
for i in range(1, N):
    tr[i] = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
atr14 = [None]*N
for i in range(14, N):
    atr14[i] = sum(tr[i-13:i+1])/14

print(f"done in {time.time()-t0:.1f}s")

# === SIGNAL GENERATORS ===
def gen_bb():
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
        # BB takes priority
        if bb_lo[i] is not None:
            if cl[i] < bb_lo[i]: sig[i] = 1; continue
            if cl[i] > bb_up[i]: sig[i] = -1; continue
        # mom6 fallback
        if mom6[i] is not None:
            if mom6[i] > 0.02: sig[i] = 1
            elif mom6[i] < -0.02: sig[i] = -1
    return sig

def gen_bb_mom6_rsi():
    """BB + mom6 + RSI filter"""
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
            # Only LONG above EMA200, SHORT below
            if cl[i] < bb_lo[i] and cl[i] > ema200[i]: sig[i] = 1; continue
            if cl[i] > bb_up[i] and cl[i] < ema200[i]: sig[i] = -1; continue
        if mom6[i] is not None and ema200[i] is not None:
            if mom6[i] > 0.02 and cl[i] > ema200[i]: sig[i] = 1
            elif mom6[i] < -0.02 and cl[i] < ema200[i]: sig[i] = -1
    return sig

# === BACKTEST ENGINE ===
def bt(sig, tp, sl, risk, lev, hold, gate_arr=None, gate_thresh=0, init=200, fee=0.0002, slip=0.001,
       simulate_wd=False, wd_target=2700, wd_amount=2500, wd_keep=200, atr_sl=False, atr_tp=False):
    """Backtest with optional ATR-based TP/SL and withdrawal simulation."""
    cap = float(init); pk = cap; max_dd = 0.0; wins = 0; total = 0
    gross_p = 0.0; gross_l = 0.0; skipped = 0
    withdrawals = []; first_target = None
    monthly = defaultdict(lambda: {'trades':0,'wins':0,'pnl':0.0,'cap_start':0,'cap_end':0})
    i = 0
    while i < N:
        s = sig[i]
        if s is None or cap <= 1.0: i += 1; continue
        if i+1 >= N: break
        if gate_arr is not None and gate_thresh > 0:
            g = gate_arr[i]
            if g is not None and g < gate_thresh:
                skipped += 1; i += 1; continue
        # Direction
        if s == 1: direction = 'LONG'
        else: direction = 'SHORT'
        # Entry at next candle open
        entry = o[i+1]
        if entry <= 0: i += 1; continue
        # ATR-based or fixed TP/SL
        if atr_tp and atr14[i] is not None:
            actual_tp = atr14[i] * tp / entry  # tp is ATR multiplier
        else:
            actual_tp = tp
        if atr_sl and atr14[i] is not None:
            actual_sl = atr14[i] * sl / entry
        else:
            actual_sl = sl
        # Position sizing
        risk_amt = cap * risk
        sl_dollar = entry * actual_sl
        if sl_dollar <= 0: i += 1; continue
        size_usd = risk_amt / (actual_sl * lev)
        size_eth = size_usd / entry
        if size_usd < 1: i += 1; continue
        # Check outcome
        tp_price = entry * (1 + actual_tp) if direction == 'LONG' else entry * (1 - actual_tp)
        sl_price = entry * (1 - actual_sl) if direction == 'LONG' else entry * (1 + actual_sl)
        closed = False
        exit_price = entry
        bars_held = 0
        for j in range(i+2, min(i+2+hold*1, N)):
            bars_held += 1
            h = hi[j]; l_ = lo[j]
            if direction == 'LONG':
                if l_ <= sl_price:
                    exit_price = sl_price * (1 - slip)
                    pnl = (exit_price - entry) / entry * size_usd * lev
                    pnl -= size_usd * fee * 2  # entry + exit fee
                    cap += pnl
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    total += 1
                    closed = True
                    break
                if h >= tp_price:
                    exit_price = tp_price * (1 - slip)
                    pnl = (exit_price - entry) / entry * size_usd * lev
                    pnl -= size_usd * fee * 2
                    cap += pnl
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    total += 1
                    closed = True
                    break
            else:
                if h >= sl_price:
                    exit_price = sl_price * (1 + slip)
                    pnl = (entry - exit_price) / entry * size_usd * lev
                    pnl -= size_usd * fee * 2
                    cap += pnl
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    total += 1
                    closed = True
                    break
                if l_ <= tp_price:
                    exit_price = tp_price * (1 + slip)
                    pnl = (entry - exit_price) / entry * size_usd * lev
                    pnl -= size_usd * fee * 2
                    cap += pnl
                    if pnl > 0: wins += 1; gross_p += pnl
                    else: gross_l += abs(pnl)
                    total += 1
                    closed = True
                    break
        if not closed:
            exit_price = cl[i+1+hold] if i+1+hold < N else cl[-1]
            if direction == 'LONG':
                pnl = (exit_price - entry) / entry * size_usd * lev
            else:
                pnl = (entry - exit_price) / entry * size_usd * lev
            pnl -= size_usd * fee * 2
            cap += pnl
            if pnl > 0: wins += 1; gross_p += pnl
            else: gross_l += abs(pnl)
            total += 1
        # Track monthly
        dt = datetime.fromtimestamp(ts_arr[i]/1000, tz=timezone.utc)
        mk = f"{dt.year}-{dt.month:02d}"
        if monthly[mk]['cap_start'] == 0: monthly[mk]['cap_start'] = cap
        monthly[mk]['trades'] += 1
        monthly[mk]['pnl'] += pnl
        if pnl > 0: monthly[mk]['wins'] += 1
        monthly[mk]['cap_end'] = cap
        # Peak/DD
        if cap > pk: pk = cap
        dd = (pk - cap) / pk if pk > 0 else 0
        if dd > max_dd: max_dd = dd
        # Withdrawal simulation
        if simulate_wd and cap >= wd_target:
            if first_target is None: first_target = dt
            withdrawals.append({'date': dt.strftime('%Y-%m-%d'), 'amount': wd_amount, 'cap_before': cap})
            cap -= wd_amount
            if cap < wd_keep: cap = wd_keep
        i += 1
    wr = wins/total*100 if total > 0 else 0
    pf = gross_p/gross_l if gross_l > 0 else 999
    total_wd = sum(w['amount'] for w in withdrawals)
    return {
        'final': cap, 'wr': wr, 'pf': pf, 'dd': max_dd*100, 'trades': total,
        'wins': wins, 'gross_p': gross_p, 'gross_l': gross_l, 'skipped': skipped,
        'withdrawals': withdrawals, 'total_withdrawn': total_wd, 'first_target': first_target,
        'monthly': dict(monthly)
    }

# === PARAMETER SWEEP ===
SEEDS = list(range(50))

# Signal generators
signals = {
    'bb_only': gen_bb(),
    'bb_mom6': gen_bb_mom6(),
    'bb_mom6_rsi': gen_bb_mom6_rsi(),
    'bb_mom6_trend': gen_bb_mom6_trend(),
}

# Parameter grid
configs = [
    # name, tp, sl, risk, lev, hold, gate_thresh, sig_name, atr_tp, atr_sl
    # --- Current deployed (broken: gate too high) ---
    ("current_deployed", 0.002, 0.001, 0.05, 20, 8, 0.025, 'bb_mom6', False, False),
    # --- No vol gate ---
    ("bb_mom6_nogate", 0.002, 0.001, 0.05, 20, 8, 0, 'bb_mom6', False, False),
    # --- Lower vol gates ---
    ("bb_mom6_gate1pct", 0.002, 0.001, 0.05, 20, 8, 0.01, 'bb_mom6', False, False),
    ("bb_mom6_gate1.5pct", 0.002, 0.001, 0.05, 20, 8, 0.015, 'bb_mom6', False, False),
    # --- Aggressive risk ---
    ("aggressive_10pct", 0.002, 0.001, 0.10, 20, 8, 0, 'bb_mom6', False, False),
    ("aggressive_15pct", 0.002, 0.001, 0.15, 20, 8, 0, 'bb_mom6', False, False),
    ("aggressive_20pct", 0.002, 0.001, 0.20, 20, 8, 0, 'bb_mom6', False, False),
    # --- Higher leverage ---
    ("lev25_risk10", 0.002, 0.001, 0.10, 25, 8, 0, 'bb_mom6', False, False),
    ("lev30_risk10", 0.002, 0.001, 0.10, 30, 8, 0, 'bb_mom6', False, False),
    # --- Wider TP ---
    ("tp0.3_sl0.2", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6', False, False),
    ("tp0.5_sl0.3", 0.005, 0.003, 0.10, 20, 8, 0, 'bb_mom6', False, False),
    ("tp0.5_sl0.2", 0.005, 0.002, 0.10, 20, 12, 0, 'bb_mom6', False, False),
    # --- Tight TP (scalping) ---
    ("tp0.15_sl0.1", 0.0015, 0.001, 0.10, 20, 4, 0, 'bb_mom6', False, False),
    ("tp0.1_sl0.1", 0.001, 0.001, 0.15, 20, 2, 0, 'bb_mom6', False, False),
    # --- ATR-based TP/SL ---
    ("atr_tp1.5_sl1", 1.5, 1.0, 0.10, 20, 8, 0, 'bb_mom6', True, True),
    ("atr_tp2_sl1.5", 2.0, 1.5, 0.10, 20, 8, 0, 'bb_mom6', True, True),
    ("atr_tp1_sl0.8", 1.0, 0.8, 0.10, 20, 4, 0, 'bb_mom6', True, True),
    # --- Different signals ---
    ("bb_only_nogate", 0.002, 0.001, 0.10, 20, 8, 0, 'bb_only', False, False),
    ("bb_mom6_rsi_nogate", 0.002, 0.001, 0.10, 20, 8, 0, 'bb_mom6_rsi', False, False),
    ("bb_mom6_trend_nogate", 0.002, 0.001, 0.10, 20, 8, 0, 'bb_mom6_trend', False, False),
    # --- Combined best: aggressive + no gate + wider TP ---
    ("yolo_wide", 0.005, 0.003, 0.15, 25, 12, 0, 'bb_mom6', False, False),
    ("yolo_tight", 0.003, 0.002, 0.15, 25, 8, 0, 'bb_mom6', False, False),
    ("yolo_scalp", 0.002, 0.001, 0.15, 30, 4, 0, 'bb_mom6', False, False),
    # --- With withdrawal simulation (target configs) ---
    ("wd_tp0.3_sl0.2_risk10", 0.003, 0.002, 0.10, 20, 8, 0, 'bb_mom6', False, False),
    ("wd_tp0.5_sl0.3_risk15", 0.005, 0.003, 0.15, 20, 12, 0, 'bb_mom6', False, False),
    ("wd_lev25_tp0.3_sl0.2", 0.003, 0.002, 0.10, 25, 8, 0, 'bb_mom6', False, False),
    ("wd_lev25_tp0.5_sl0.2", 0.005, 0.002, 0.10, 25, 12, 0, 'bb_mom6', False, False),
]

print(f"\nRunning {len(configs)} configs × {len(SEEDS)} seeds = {len(configs)*len(SEEDS)} backtests...")
print("="*100)

results = []
for ci, (name, tp, sl, risk, lev, hold, gate_t, sig_name, atr_tp, atr_sl) in enumerate(configs):
    sig = signals[sig_name]
    gate_arr = vol_gate if gate_t > 0 else None
    caps = []; wrs = []; pfs = []; dds = []; trade_counts = []
    wd_totals = []; wd_targets_hit = []; first_wds = []
    
    for seed in SEEDS:
        random.seed(seed)
        # Randomize signal order slightly (simulate different entry timing)
        sig_r = [None]*N
        offset = random.randint(0, 3)
        for i in range(N):
            if i >= offset and sig[i-offset] is not None:
                sig_r[i] = sig[i-offset]
        r = bt(sig_r, tp, sl, risk, lev, hold, gate_arr, gate_t, atr_tp=atr_tp, atr_sl=atr_sl,
               simulate_wd=True, wd_target=2700, wd_amount=2500, wd_keep=200)
        caps.append(r['final'] + r['total_withdrawn'])
        wrs.append(r['wr']); pfs.append(r['pf']); dds.append(r['dd'])
        trade_counts.append(r['trades'])
        wd_totals.append(r['total_withdrawn'])
        if r['first_target']: wd_targets_hit.append(1)
        if r['withdrawals']: first_wds.append(r['withdrawals'][0]['date'])
    
    avg_cap = sum(caps)/len(caps)
    avg_wr = sum(wrs)/len(wrs)
    avg_pf = sum(pfs)/len(pfs)
    avg_dd = sum(dds)/len(dds)
    avg_trades = sum(trade_counts)/len(trade_counts)
    avg_wd = sum(wd_totals)/len(wd_totals)
    hit_rate = len(wd_targets_hit)/len(SEEDS)*100
    
    results.append({
        'name': name, 'tp': tp, 'sl': sl, 'risk': risk, 'lev': lev, 'hold': hold,
        'gate': gate_t, 'sig': sig_name, 'atr_tp': atr_tp, 'atr_sl': atr_sl,
        'avg_cap': avg_cap, 'avg_wr': avg_wr, 'avg_pf': avg_pf, 'avg_dd': avg_dd,
        'avg_trades': avg_trades, 'avg_wd': avg_wd, 'hit_rate': hit_rate,
        'targets_hit': len(wd_targets_hit), 'first_wd': first_wds[:3] if first_wds else []
    })
    
    status = f"[{ci+1}/{len(configs)}] {name:<35} WR={avg_wr:.1f}% PF={avg_pf:.2f} DD={avg_dd:.1f}% Trades={avg_trades:.0f} WD=${avg_wd:,.0f} Hit={hit_rate:.0f}%"
    print(status)

# Sort by total withdrawn (descending)
results.sort(key=lambda x: x['avg_wd'], reverse=True)

print("\n" + "="*100)
print("TOP 10 CONFIGS BY TOTAL WITHDRAWN ($2500/month target)")
print("="*100)
print(f"{'Config':<35} {'WR%':>6} {'PF':>6} {'DD%':>6} {'Trades':>7} {'AvgWD$':>10} {'Hit%':>6} {'1stWD':>12}")
print("-"*100)
for r in results[:10]:
    first = r['first_wd'][0] if r['first_wd'] else 'N/A'
    print(f"{r['name']:<35} {r['avg_wr']:>5.1f}% {r['avg_pf']:>5.2f} {r['avg_dd']:>5.1f}% {r['avg_trades']:>6.0f} {r['avg_wd']:>9,.0f} {r['hit_rate']:>5.0f}% {first:>12}")

print("\n" + "="*100)
print("BOTTOM 5 (worst performers)")
print("="*100)
for r in results[-5:]:
    first = r['first_wd'][0] if r['first_wd'] else 'N/A'
    print(f"{r['name']:<35} {r['avg_wr']:>5.1f}% {r['avg_pf']:>5.2f} {r['avg_dd']:>5.1f}% {r['avg_trades']:>6.0f} {r['avg_wd']:>9,.0f} {r['hit_rate']:>5.0f}% {first:>12}")

# Save full results
output = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'target': '$2500/month withdrawal from $200 capital',
    'data_range': f'{N} candles 2021-2026',
    'seeds': len(SEEDS),
    'results': results
}
with open('/root/.openclaw/workspace/jimi_audit/data/optimization_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nDone in {time.time()-t0:.1f}s. Results saved to optimization_results.json")
PYEOF
