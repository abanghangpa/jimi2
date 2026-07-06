#!/usr/bin/env python3
"""
momentum_v3 Fast Backtest — Skip standalone, focus on paired tests.
Only iterates over fired event signals (hundreds, not 310K).
"""
import json, csv, numpy as np
from datetime import datetime, timedelta

BASE = '/root/.openclaw/workspace/jimi_audit'

# Load ETH
eth_keys = []
closes = []
highs = []
lows = []
volumes = []
eth_map = {}
with open(f'{BASE}/eth_15m_merged.csv') as f:
    for i, row in enumerate(csv.DictReader(f)):
        k = row['Open time']
        eth_keys.append(k)
        closes.append(float(row['Close']))
        highs.append(float(row['High']))
        lows.append(float(row['Low']))
        volumes.append(float(row['Volume']))
        eth_map[k] = i

closes = np.array(closes)
highs = np.array(highs)
lows = np.array(lows)
volumes = np.array(volumes)

# ATR
atr_cache = {}
for i in range(14, len(eth_keys)):
    trs = []
    for j in range(i - 14, i):
        tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
        trs.append(tr)
    atr_cache[eth_keys[i]] = np.mean(trs)

# Derivatives
deriv = {}
with open(f'{BASE}/data/derivatives_history/derivatives_collected.csv') as f:
    for row in csv.DictReader(f):
        dt = datetime.fromisoformat(row['timestamp'])
        dt_floor = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        k = dt_floor.strftime('%Y-%m-%d %H:%M:%S')
        deriv[k] = {'ls_ratio': float(row['ls_ratio']), 'funding_rate': float(row['funding_rate']), 'oi': float(row.get('oi', 0))}

oi_keys = sorted(deriv.keys())
for i in range(4, len(oi_keys)):
    curr = deriv[oi_keys[i]]['oi']
    prev = deriv[oi_keys[i-4]]['oi']
    deriv[oi_keys[i]]['oi_roc_1h'] = (curr - prev) / prev if prev > 0 else 0

# Event signals
event_signals = {}
with open(f'{BASE}/data/strategy_signals.jsonl') as f:
    for line in f:
        try:
            d = json.loads(line)
            if d.get('fired'):
                s = d.get('strategy')
                if s not in event_signals:
                    event_signals[s] = []
                event_signals[s].append(d)
        except:
            pass

print("Event signals:")
for s, sigs in sorted(event_signals.items(), key=lambda x: -len(x[1])):
    print(f"  {s}: {len(sigs)}")

def find_deriv(ts, max_min=30):
    if ts in deriv: return deriv[ts]
    dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    for off in range(1, max_min + 1, 1):
        for d in [dt - timedelta(minutes=off), dt + timedelta(minutes=off)]:
            k = d.strftime('%Y-%m-%d %H:%M:%S')
            if k in deriv: return deriv[k]
    return None

def detect_exhaustion(idx, min_signals=2):
    if idx < 80: return None
    mom_5 = (closes[idx] - closes[idx - 5]) / closes[idx - 5]
    mom_10 = (closes[idx] - closes[idx - 10]) / closes[idx - 10]
    accel = mom_5 - mom_10 / 2
    decel = (mom_5 > 0 and accel < 0) or (mom_5 < 0 and accel > 0)
    vol_recent = np.mean(volumes[idx - 5:idx])
    vol_prior = np.mean(volumes[idx - 15:idx - 5])
    vol_change = (vol_recent - vol_prior) / vol_prior if vol_prior > 0 else 0
    vol_div = abs(mom_5) > 0.005 and vol_change < -0.1
    moves = [abs(closes[j + 5] - closes[j]) / closes[j] for j in range(idx - 80, idx - 5)]
    current_move = abs(closes[idx] - closes[idx - 5]) / closes[idx - 5]
    percentile = sum(1 for m in moves if m < current_move) / len(moves) * 100
    extreme = percentile > 85
    ts = eth_keys[idx]
    dv = find_deriv(ts)
    oi_roc = dv.get('oi_roc_1h', 0) if dv else 0
    oi_div = abs(mom_5) > 0.005 and oi_roc < -0.02
    count = sum([decel, vol_div, extreme, oi_div])
    if count < min_signals: return None
    direction = 'SHORT' if mom_5 > 0 else 'LONG' if mom_5 < 0 else None
    if not direction: return None
    return {'direction': direction, 'mom_5': mom_5, 'count': count}

def sim_paired(event_sigs, min_signals=2, tp=2.0, sl=1.0, hold=24, dedup=True):
    trades = []
    capital = 200.0
    peak = capital
    max_dd = 0
    used = set()
    for sig in event_sigs:
        ts = sig['timestamp']
        d = sig['direction']
        p = sig.get('entry') or sig.get('price', 0)
        if not d or not p: continue
        if dedup and ts in used: continue
        used.add(ts)
        idx = eth_map.get(ts, -1)
        if idx < 0 or idx < 80 or idx >= len(eth_keys) - hold: continue
        exc = detect_exhaustion(idx, min_signals=min_signals)
        if not exc: continue
        if exc['direction'] != d: continue
        atr = atr_cache.get(ts, 0)
        if atr <= 0: continue
        if d == 'LONG':
            tp_p = p + tp * atr; sl_p = p - sl * atr
        else:
            tp_p = p - tp * atr; sl_p = p + sl * atr
        outcome = None
        for j in range(idx + 1, min(idx + hold + 1, len(eth_keys))):
            if d == 'LONG':
                if highs[j] >= tp_p: outcome = 'W'; exit_p = tp_p; break
                if lows[j] <= sl_p: outcome = 'L'; exit_p = sl_p; break
            else:
                if lows[j] <= tp_p: outcome = 'W'; exit_p = tp_p; break
                if highs[j] >= sl_p: outcome = 'L'; exit_p = sl_p; break
        if outcome is None:
            exit_p = closes[min(idx + hold, len(eth_keys) - 1)]
            outcome = 'W' if ((d == 'LONG' and exit_p > p) or (d == 'SHORT' and exit_p < p)) else 'L'
        pnl_pct = ((exit_p - p) / p * 100) if d == 'LONG' else ((p - exit_p) / p * 100)
        size = capital * 0.10 * 25
        net_pnl = size * pnl_pct / 100 - size * 0.0005 * 2
        capital += net_pnl
        if capital > peak: peak = capital
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
        trades.append({'time': ts, 'dir': d, 'outcome': outcome, 'pnl_dollar': net_pnl, 'pnl_pct': pnl_pct})
    if not trades: return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0}
    wins = [t for t in trades if t['outcome'] == 'W']
    losses = [t for t in trades if t['outcome'] == 'L']
    tw = sum(t['pnl_dollar'] for t in wins)
    tl = sum(abs(t['pnl_dollar']) for t in losses)
    pf = tw / tl if tl > 0 else float('inf')
    return {'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
            'wr': round(len(wins)/len(trades)*100, 1), 'pf': round(pf, 2),
            'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
            'max_dd': round(max_dd, 2)}

# ============================================================
# TESTS
# ============================================================
print("\n" + "=" * 90)
print("momentum_v3 EXHAUSTION FILTER — EVENT STRATEGY PAIRING")
print("=" * 90)

for strat_name in ['failed_breakout', 'structural_break', 'squeeze_breakout', 'trade_flow', 'orderbook_imbalance', 'taker_flow']:
    sigs = event_signals.get(strat_name, [])
    if len(sigs) < 10: continue

    print(f"\n{'='*90}")
    print(f"  {strat_name} ({len(sigs)} signals)")
    print(f"{'='*90}")
    print(f"  {'Config':>25s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'MaxDD':>6s}")
    print("  " + "-" * 80)

    # Baseline
    m_base = sim_paired(sigs, min_signals=0, tp=2.0, sl=1.0, hold=24)
    print(f"  {'baseline (no filter)':>25s} | {m_base['trades']:>6d} | {m_base.get('wins',0):>3d} {m_base.get('losses',0):>3d} | {m_base['wr']:>5.1f}% | {m_base['pf']:>6.2f} | ${m_base['pnl']:>+7.2f} | {m_base['max_dd']:>5.2f}%")

    # Exhaustion filter combos
    for min_sig in [2, 3]:
        for tp_val, sl_val, hold_val in [(1.0, 1.0, 16), (1.5, 1.0, 16), (2.0, 1.0, 24), (2.0, 1.5, 24), (2.5, 1.0, 32)]:
            m = sim_paired(sigs, min_signals=min_sig, tp=tp_val, sl=sl_val, hold=hold_val)
            if m['trades'] >= 3:
                hit = " ***" if m['pf'] >= 2.0 and m['wr'] >= 75 else ""
                print(f"  exc>={min_sig}/4 TP{tp_val}/SL{sl_val}/H{hold_val:>2d} | {m['trades']:>6d} | {m.get('wins',0):>3d} {m.get('losses',0):>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f} | {m['max_dd']:>5.2f}%{hit}")

# Summary
print(f"\n{'='*90}")
print("SUMMARY")
print(f"{'='*90}")

for strat_name in ['failed_breakout', 'structural_break', 'squeeze_breakout', 'trade_flow']:
    sigs = event_signals.get(strat_name, [])
    if len(sigs) < 10: continue
    best_pf = 0
    best_label = ''
    for min_sig in [2, 3]:
        for tp_val, sl_val, hold_val in [(1.0, 1.0, 16), (1.5, 1.0, 16), (2.0, 1.0, 24), (2.0, 1.5, 24), (2.5, 1.0, 32)]:
            m = sim_paired(sigs, min_signals=min_sig, tp=tp_val, sl=sl_val, hold=hold_val)
            if m['pf'] > best_pf and m['trades'] >= 3:
                best_pf = m['pf']
                best_label = f"exc>={min_sig}/4 TP{tp_val}/SL{sl_val}/H{hold_val}"
                best_m = m
    baseline = sim_paired(sigs, min_signals=0, tp=2.0, sl=1.0, hold=24)
    delta = best_pf - baseline['pf'] if best_pf > 0 else 0
    print(f"  {strat_name:>25s}: baseline PF={baseline['pf']:.2f} -> {best_label} PF={best_pf:.2f} (Δ={delta:+.2f}, {best_m['trades']} trades)")

print("\nDone")
