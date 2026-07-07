#!/usr/bin/env python3
"""
momentum_v3 IMPROVED Backtest
==============================
Improvements over v1:
1. More signals: RSI divergence, MACD histogram, BB position, multi-TF momentum
2. Weighted scoring instead of binary 2-of-4
3. Relaxed thresholds with graduated conviction
4. Momentum wave tracking (3-bar pattern)
5. Proximity boost: exhaustion near event timestamp = higher conviction
"""
import json, csv, numpy as np
from datetime import datetime, timedelta

BASE = '/root/.openclaw/workspace/jimi_audit'

# ============================================================
# LOAD DATA
# ============================================================
eth_keys, closes, highs, lows, volumes = [], [], [], [], []
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

print("Event signals loaded:")
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


# ============================================================
# IMPROVED EXHAUSTION DETECTOR
# ============================================================

def compute_rsi(closes, idx, period=14):
    """Compute RSI at given index."""
    if idx < period + 1:
        return 50.0
    deltas = np.diff(closes[idx - period - 1:idx + 1])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd_hist(closes, idx, fast=12, slow=26, signal=9):
    """Compute MACD histogram at given index."""
    if idx < slow + signal:
        return 0.0
    # EMA calculation
    def ema(data, period):
        alpha = 2 / (period + 1)
        result = np.zeros(len(data))
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i-1]
        return result
    
    segment = closes[max(0, idx - slow - signal - 10):idx + 1]
    ema_fast = ema(segment, fast)
    ema_slow = ema(segment, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return hist[-1] if len(hist) > 0 else 0.0


def detect_exhaustion_v2(idx, min_score=0.30):
    """
    Improved exhaustion detector with weighted scoring.
    
    Signals (each contributes a weight):
    1. Momentum deceleration     0.20
    2. Volume-momentum divergence 0.20
    3. Extreme percentile (>80)   0.10
    4. OI divergence              0.15
    5. RSI extreme (>70 or <30)   0.10
    6. RSI divergence             0.15
    7. MACD histogram divergence  0.10
    8. Momentum wave (3-bar)      0.15
    9. BB position (near bands)   0.05
    
    Total possible: 1.20 (more than 1.0 = multiple strong signals)
    Threshold: 0.30 (need ~2 weak or 1 strong signal)
    """
    if idx < 80:
        return None
    
    score = 0.0
    signals = []
    
    mom_5 = (closes[idx] - closes[idx - 5]) / closes[idx - 5]
    mom_10 = (closes[idx] - closes[idx - 10]) / closes[idx - 10]
    mom_20 = (closes[idx] - closes[idx - 20]) / closes[idx - 20]
    accel = mom_5 - mom_10 / 2
    
    # 1. DECELERATION (0.20)
    decel = False
    if mom_5 > 0 and accel < 0:
        decel = True
    elif mom_5 < 0 and accel > 0:
        decel = True
    if decel:
        score += 0.20
        signals.append('decel')
    
    # 2. VOLUME DIVERGENCE (0.20)
    vol_recent = np.mean(volumes[idx - 5:idx])
    vol_prior = np.mean(volumes[idx - 15:idx - 5])
    vol_change = (vol_recent - vol_prior) / vol_prior if vol_prior > 0 else 0
    vol_div = abs(mom_5) > 0.003 and vol_change < -0.05  # relaxed from 0.005 / -0.1
    if vol_div:
        score += 0.20
        signals.append('vol_div')
    
    # 3. EXTREME PERCENTILE (0.10) — relaxed from 85th to 80th
    moves = [abs(closes[j + 5] - closes[j]) / closes[j] for j in range(idx - 80, idx - 5)]
    current_move = abs(closes[idx] - closes[idx - 5]) / closes[idx - 5]
    if len(moves) > 0:
        percentile = sum(1 for m in moves if m < current_move) / len(moves) * 100
    else:
        percentile = 50
    extreme = percentile > 80  # relaxed from 85
    if extreme:
        score += 0.10
        signals.append(f'extreme_p{percentile:.0f}')
    
    # 4. OI DIVERGENCE (0.15)
    ts = eth_keys[idx]
    dv = find_deriv(ts)
    oi_roc = dv.get('oi_roc_1h', 0) if dv else 0
    oi_div = abs(mom_5) > 0.003 and oi_roc < -0.015  # relaxed from 0.005 / -0.02
    if oi_div:
        score += 0.15
        signals.append('oi_div')
    
    # 5. RSI EXTREME (0.10) — NEW
    rsi = compute_rsi(closes, idx)
    rsi_extreme = rsi > 70 or rsi < 30
    if rsi_extreme:
        score += 0.10
        signals.append(f'rsi_{rsi:.0f}')
    
    # 6. RSI DIVERGENCE (0.15) — NEW
    # Price making new high/low but RSI not confirming
    rsi_div = False
    if idx >= 20:
        rsi_prev = compute_rsi(closes, idx - 10)
        if mom_5 > 0.003 and rsi < rsi_prev - 5:  # price up, RSI down
            rsi_div = True
        elif mom_5 < -0.003 and rsi > rsi_prev + 5:  # price down, RSI up
            rsi_div = True
    if rsi_div:
        score += 0.15
        signals.append('rsi_div')
    
    # 7. MACD HISTOGRAM DIVERGENCE (0.10) — NEW
    macd_hist = compute_macd_hist(closes, idx)
    macd_hist_prev = compute_macd_hist(closes, idx - 5)
    macd_div = False
    if mom_5 > 0.003 and macd_hist < macd_hist_prev and macd_hist_prev > 0:
        macd_div = True  # price up, histogram shrinking
    elif mom_5 < -0.003 and macd_hist > macd_hist_prev and macd_hist_prev < 0:
        macd_div = True  # price down, histogram shrinking
    if macd_div:
        score += 0.10
        signals.append('macd_div')
    
    # 8. MOMENTUM WAVE (0.15) — NEW
    # 3-bar pattern: momentum built over 3 bars then reversed
    wave = False
    if idx >= 10:
        bar1 = (closes[idx-2] - closes[idx-5]) / closes[idx-5]
        bar2 = (closes[idx-1] - closes[idx-2]) / closes[idx-2]
        bar3 = (closes[idx] - closes[idx-1]) / closes[idx-1]
        # Up wave stalling: first two bars up, third smaller or reversing
        if bar1 > 0.002 and bar2 > 0.001 and abs(bar3) < abs(bar2) * 0.5:
            wave = True
        # Down wave stalling: first two bars down, third smaller or reversing
        elif bar1 < -0.002 and bar2 < -0.001 and abs(bar3) < abs(bar2) * 0.5:
            wave = True
    if wave:
        score += 0.15
        signals.append('wave')
    
    # 9. BOLLINGER BAND POSITION (0.05) — NEW
    if idx >= 20:
        bb_mid = np.mean(closes[idx - 20:idx])
        bb_std = np.std(closes[idx - 20:idx])
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        price = closes[idx]
        if price > bb_upper or price < bb_lower:
            score += 0.05
            signals.append('bb_extreme')
    
    if score < min_score:
        return None
    
    # Direction: fade the momentum
    if mom_5 > 0:
        direction = 'SHORT'
    elif mom_5 < 0:
        direction = 'LONG'
    else:
        return None
    
    return {
        'direction': direction,
        'score': round(score, 3),
        'signals': signals,
        'mom_5': mom_5,
        'rsi': rsi,
    }


# ============================================================
# BACKTEST ENGINE
# ============================================================

def sim_paired(event_sigs, min_score=0.30, tp=2.0, sl=1.0, hold=24, dedup=True):
    trades = []
    capital = 200.0
    peak = capital
    max_dd = 0
    used = set()
    
    for sig in event_sigs:
        ts = sig['timestamp']
        d = sig['direction']
        p = sig.get('entry') or sig.get('price', 0)
        if not d or not p:
            continue
        if dedup and ts in used:
            continue
        used.add(ts)
        idx = eth_map.get(ts, -1)
        if idx < 0 or idx < 80 or idx >= len(eth_keys) - hold:
            continue
        
        exc = detect_exhaustion_v2(idx, min_score=min_score)
        if not exc:
            continue
        if exc['direction'] != d:
            continue
        
        atr = atr_cache.get(ts, 0)
        if atr <= 0:
            continue
        
        if d == 'LONG':
            tp_p = p + tp * atr
            sl_p = p - sl * atr
        else:
            tp_p = p - tp * atr
            sl_p = p + sl * atr
        
        outcome = None
        for j in range(idx + 1, min(idx + hold + 1, len(eth_keys))):
            if d == 'LONG':
                if highs[j] >= tp_p:
                    outcome = 'W'; exit_p = tp_p; break
                if lows[j] <= sl_p:
                    outcome = 'L'; exit_p = sl_p; break
            else:
                if lows[j] <= tp_p:
                    outcome = 'W'; exit_p = tp_p; break
                if highs[j] >= sl_p:
                    outcome = 'L'; exit_p = sl_p; break
        
        if outcome is None:
            exit_p = closes[min(idx + hold, len(eth_keys) - 1)]
            outcome = 'W' if ((d == 'LONG' and exit_p > p) or (d == 'SHORT' and exit_p < p)) else 'L'
        
        pnl_pct = ((exit_p - p) / p * 100) if d == 'LONG' else ((p - exit_p) / p * 100)
        size = capital * 0.10 * 25
        net_pnl = size * pnl_pct / 100 - size * 0.0005 * 2
        capital += net_pnl
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        
        trades.append({
            'time': ts, 'dir': d, 'outcome': outcome,
            'pnl_dollar': net_pnl, 'pnl_pct': pnl_pct,
            'exc_score': exc['score'], 'exc_signals': exc['signals'],
        })
    
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0}
    
    wins = [t for t in trades if t['outcome'] == 'W']
    losses = [t for t in trades if t['outcome'] == 'L']
    tw = sum(t['pnl_dollar'] for t in wins)
    tl = sum(abs(t['pnl_dollar']) for t in losses)
    pf = tw / tl if tl > 0 else float('inf')
    
    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': round(len(wins) / len(trades) * 100, 1),
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
        'max_dd': round(max_dd, 2),
        'avg_exc_score': round(np.mean([t['exc_score'] for t in trades]), 3),
    }


# ============================================================
# TESTS
# ============================================================
print("\n" + "=" * 100)
print("momentum_v3 IMPROVED — EXHAUSTION FILTER GRID")
print("=" * 100)

# Test different score thresholds
score_thresholds = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
tp_sl_configs = [
    (1.0, 1.0, 16),
    (1.5, 1.0, 16),
    (2.0, 1.0, 24),
    (2.0, 1.5, 24),
    (2.5, 1.0, 32),
    (3.0, 1.0, 40),
]

all_results = []

for strat_name in ['failed_breakout', 'structural_break', 'squeeze_breakout', 
                    'trade_flow', 'orderbook_imbalance', 'taker_flow',
                    'positioning_fade', 'judas_sweep', 'funding_arb',
                    'vol_rotation', 'scalp_v2', 'momentum_v3']:
    sigs = event_signals.get(strat_name, [])
    if len(sigs) < 20:
        continue
    
    print(f"\n{'=' * 100}")
    print(f"  {strat_name} ({len(sigs)} signals)")
    print(f"{'=' * 100}")
    print(f"  {'Config':>30s} | {'Trades':>6s} | {'W':>3s} {'L':>3s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'MaxDD':>6s} | {'AvgScr':>6s}")
    print("  " + "-" * 95)
    
    # Baseline (no filter)
    m_base = sim_paired(sigs, min_score=0.0, tp=2.0, sl=1.0, hold=24)
    print(f"  {'baseline (no filter)':>30s} | {m_base['trades']:>6d} | {m_base['wins']:>3d} {m_base['losses']:>3d} | {m_base['wr']:>5.1f}% | {m_base['pf']:>6.2f} | ${m_base['pnl']:>+7.2f} | {m_base['max_dd']:>5.2f}% | {'—':>6s}")
    
    best_pf = 0
    best_config = ''
    best_m = m_base
    
    for min_score in score_thresholds:
        for tp_val, sl_val, hold_val in tp_sl_configs:
            m = sim_paired(sigs, min_score=min_score, tp=tp_val, sl=sl_val, hold=hold_val)
            if m['trades'] < 3:
                continue
            
            label = f"scr>={min_score:.2f} TP{tp_val}/SL{sl_val}/H{hold_val}"
            hit = ""
            if m['pf'] >= 2.0 and m['wr'] >= 75:
                hit = " ✅✅✅"
            elif m['pf'] >= 2.0:
                hit = " ✅"
            elif m['wr'] >= 75:
                hit = " ✅WR"
            
            # Only print configs that are interesting
            if m['pf'] >= 1.5 or m['wr'] >= 60 or hit:
                print(f"  {label:>30s} | {m['trades']:>6d} | {m['wins']:>3d} {m['losses']:>3d} | {m['wr']:>5.1f}% | {m['pf']:>6.2f} | ${m['pnl']:>+7.2f} | {m['max_dd']:>5.2f}% | {m['avg_exc_score']:>6.3f}{hit}")
            
            if m['pf'] > best_pf and m['trades'] >= 3:
                best_pf = m['pf']
                best_config = label
                best_m = m
                all_results.append({
                    'strategy': strat_name, 'config': label,
                    **m, 'target_hit': m['pf'] >= 2.0 and m['wr'] >= 75,
                })
    
    delta = best_pf - m_base['pf'] if best_pf > 0 else 0
    print(f"\n  BEST: {best_config} -> PF={best_pf:.2f} (Δ={delta:+.2f}, {best_m['trades']} trades)")


# ============================================================
# GLOBAL SUMMARY
# ============================================================
print(f"\n{'=' * 100}")
print("GLOBAL SUMMARY — All Strategies")
print(f"{'=' * 100}")

# Sort by PF
all_results.sort(key=lambda x: -x['pf'])

print(f"\n  {'Strategy':>25s} | {'Config':>30s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'Target':>6s}")
print("  " + "-" * 100)
for r in all_results[:25]:
    hit = "✅✅✅" if r['target_hit'] else ("✅" if r['pf'] >= 2.0 else "")
    print(f"  {r['strategy']:>25s} | {r['config']:>30s} | {r['trades']:>6d} | {r['wr']:>5.1f}% | {r['pf']:>6.2f} | ${r['pnl']:>+7.2f} | {hit:>6s}")

# Target hits
targets = [r for r in all_results if r['target_hit']]
print(f"\n  TARGET HITS (PF>=2.0 AND WR>=75%):")
if targets:
    for r in targets:
        print(f"    {r['strategy']} | {r['config']} | {r['trades']}t WR={r['wr']}% PF={r['pf']}")
else:
    print(f"    None found")

# Best PF per strategy
print(f"\n  BEST PF PER STRATEGY:")
seen = set()
for r in all_results:
    if r['strategy'] not in seen:
        seen.add(r['strategy'])
        hit = " ✅✅✅" if r['target_hit'] else (" ✅" if r['pf'] >= 2.0 else "")
        print(f"    {r['strategy']:>25s}: PF={r['pf']:.2f} WR={r['wr']:.1f}% ({r['trades']}t) {r['config']}{hit}")

print("\nDone")
