#!/usr/bin/env python3
"""
Deep analysis: Find concrete win rate and PnL improvement opportunities.
"""
import sys
import os
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCAN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'scans')

HOLD_WINDOWS = {
    'main_pipeline': 4, 'failed_breakout': 8, 'funding_arb': 4,
    'orderbook_imbalance': 4, 'trade_flow': 4, 'cross_asset': 4,
    'mtf_confluence': 4, 'structural_break': 8, 'scalp_v2': 2,
    'momentum_v2': 4, 'squeeze_breakout': 4, 'positioning_fade': 2,
    'kill_zone': 4, 'liquidity_grab': 4, 'taker_flow': 2,
    'regime_switch': 4, 'power_of_3': 4, 'cascade': 4,
    'macro_surprise': 8, 'whale_watch': 4, 'vol_rotation': 4,
    'liquidation_cascade': 4, 'judas_sweep': 4,
}


def classify_regime(trend):
    if not trend: return 'RANGING'
    if 'STRONG_DOWN' in trend: return 'STRONG_DOWN'
    elif 'DOWN' in trend: return 'DOWN'
    elif 'STRONG_UP' in trend: return 'STRONG_UP'
    elif 'UP' in trend: return 'UP'
    return 'RANGING'


def load_scans():
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    scans = []
    for f in files:
        try:
            with open(f) as fh:
                scans.append(json.load(fh))
        except: pass
    return scans


def find_price_at_offset(price_cache, sorted_ts, base_ts, hours):
    try:
        base_dt = datetime.strptime(base_ts, "%Y-%m-%d %H:%M:%S")
    except: return None
    target = base_dt + timedelta(hours=hours)
    best, best_diff = None, timedelta(hours=999)
    for t in sorted_ts:
        try:
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except: continue
        diff = abs(dt - target)
        if diff < best_diff:
            best_diff = diff
            best = price_cache[t]
    return best if best_diff < timedelta(hours=2) else None


def find_prices_in_range(price_cache, sorted_ts, start_ts, end_ts):
    return [price_cache[t] for t in sorted_ts if start_ts <= t <= end_ts]


def evaluate(price_cache, sorted_ts, ts, direction, entry, sl, tp1, hold_hours):
    exit_p = find_price_at_offset(price_cache, sorted_ts, ts, hold_hours)
    if exit_p is None or not entry: return None
    try:
        sig_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        end_ts = (sig_dt + timedelta(hours=hold_hours)).strftime("%Y-%m-%d %H:%M:%S")
        prices = find_prices_in_range(price_cache, sorted_ts, ts, end_ts)
    except: prices = []

    if direction == 'LONG':
        pnl = (exit_p - entry) / entry * 100
        mf = max((p - entry) / entry * 100 for p in prices) if prices else 0
        ma = min((p - entry) / entry * 100 for p in prices) if prices else 0
        hit_tp = exit_p >= tp1 if tp1 > 0 else False
        hit_sl = exit_p <= sl if sl > 0 else False
    else:
        pnl = (entry - exit_p) / entry * 100
        mf = max((entry - p) / entry * 100 for p in prices) if prices else 0
        ma = min((entry - p) / entry * 100 for p in prices) if prices else 0
        hit_tp = exit_p <= tp1 if tp1 > 0 else False
        hit_sl = exit_p >= sl if sl > 0 else False

    outcome = 'WIN' if hit_tp or pnl > 0.1 else 'LOSS' if hit_sl or pnl < -0.1 else 'NEUTRAL'
    return {'outcome': outcome, 'pnl': pnl, 'hit_tp': hit_tp, 'hit_sl': hit_sl, 'mf': mf, 'ma': ma}


def analyze():
    print("Loading scans...")
    scans = load_scans()
    print(f"Loaded {len(scans)} scans")

    price_cache = {}
    for s in scans:
        ts, p = s.get('timestamp'), s.get('price')
        if ts and p: price_cache[ts] = float(p)
    sorted_ts = sorted(price_cache.keys())

    # Collect all signals with metadata
    signals = []
    for scan in scans:
        if scan.get('status') != 'SIGNAL': continue
        ts = scan.get('timestamp', '')
        price = scan.get('price', 0)
        direction = scan.get('direction', '')
        source = scan.get('source', 'main_pipeline')
        trend = scan.get('trend_dir', '')
        regime = classify_regime(trend)
        ics = scan.get('ics', 0)
        entry = scan.get('entry', price)
        sl = scan.get('sl', 0)
        tp1 = scan.get('tp1', 0)

        signals.append({
            'ts': ts, 'price': price, 'direction': direction,
            'source': source, 'regime': regime, 'trend': trend,
            'ics': ics, 'entry': entry, 'sl': sl, 'tp1': tp1,
            'hold': HOLD_WINDOWS.get(source, 4),
            'swing': scan.get('swing_bias', ''),
            'phase0': scan.get('phase0', 0),
            'squeeze': scan.get('squeeze_confirmed', False),
        })

        ms = scan.get('multi_strategy', {}) or {}
        for sig in ms.get('all_signals', []):
            sn = sig.get('strategy', '')
            sd = sig.get('direction', '')
            if not sn or not sd: continue
            signals.append({
                'ts': ts, 'price': price, 'direction': sd,
                'source': f'strategy:{sn}', 'regime': regime, 'trend': trend,
                'ics': ics, 'entry': price, 'sl': sig.get('sl', 0),
                'tp1': sig.get('tp1', 0), 'hold': HOLD_WINDOWS.get(sn, 4),
                'swing': scan.get('swing_bias', ''),
                'phase0': scan.get('phase0', 0),
                'squeeze': scan.get('squeeze_confirmed', False),
                'conviction': sig.get('conviction', 0),
            })

    print(f"Total signals: {len(signals)}")

    # ═══════════════════════════════════════════════════════════════════
    # ANALYSIS 1: Hold Window Optimization
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  ANALYSIS 1: HOLD WINDOW OPTIMIZATION")
    print("  Test different hold windows to find optimal for each strategy")
    print("=" * 90)

    test_windows = [1, 2, 4, 6, 8, 12, 24]
    strategy_windows = defaultdict(lambda: defaultdict(lambda: {'w': 0, 'l': 0, 't': 0, 'pnl': []}))

    for sig in signals:
        ev = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                     sig['entry'], sig['sl'], sig['tp1'], 24)  # max window
        if ev is None: continue

        source = sig['source']
        # For each test window, find price and evaluate
        for wh in test_windows:
            ev_w = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                           sig['entry'], sig['sl'], sig['tp1'], wh)
            if ev_w is None: continue
            stats = strategy_windows[source][wh]
            stats['t'] += 1
            stats['pnl'].append(ev_w['pnl'])
            if ev_w['outcome'] == 'WIN': stats['w'] += 1
            elif ev_w['outcome'] == 'LOSS': stats['l'] += 1

    print(f"\n  {'Strategy':<30} {'1h':<8} {'2h':<8} {'4h':<8} {'6h':<8} {'8h':<8} {'12h':<8} {'24h':<8} {'Best':<8}")
    print("  " + "-" * 100)

    improvements = []
    for source in sorted(strategy_windows.keys()):
        if source.startswith('strategy:'): continue  # skip duplicates
        row = {}
        best_wr, best_wh = 0, 0
        for wh in test_windows:
            stats = strategy_windows[source].get(wh, {})
            t = stats.get('t', 0)
            w = stats.get('w', 0)
            wr = w / t * 100 if t >= 10 else 0
            avg_pnl = sum(stats.get('pnl', [])) / len(stats.get('pnl', [])) if stats.get('pnl') else 0
            row[wh] = f"{wr:.0f}%({t})" if t >= 10 else f"--"
            if wr > best_wr and t >= 10:
                best_wr = wr
                best_wh = wh

        current_wh = HOLD_WINDOWS.get(source, 4)
        current_stats = strategy_windows[source].get(current_wh, {})
        current_wr = current_stats.get('w', 0) / current_stats.get('t', 1) * 100 if current_stats.get('t', 0) >= 10 else 0

        if best_wh != current_wh and best_wr > current_wr + 2:
            improvements.append({
                'strategy': source, 'current': current_wh, 'optimal': best_wh,
                'current_wr': current_wr, 'optimal_wr': best_wr,
                'improvement': best_wr - current_wr,
            })

        vals = [row.get(wh, '--') for wh in test_windows]
        marker = ' <--' if best_wh != current_wh and best_wr > current_wr + 2 else ''
        print(f"  {source:<30} {'  '.join(f'{v:<6}' for v in vals)}  {best_wh}h{marker}")

    if improvements:
        print(f"\n  HOLD WINDOW IMPROVEMENTS AVAILABLE:")
        for imp in sorted(improvements, key=lambda x: x['improvement'], reverse=True):
            print(f"    {imp['strategy']}: {imp['current']}h ({imp['current_wr']:.1f}%) -> {imp['optimal']}h ({imp['optimal_wr']:.1f}%) [+{imp['improvement']:.1f}%]")

    # ═══════════════════════════════════════════════════════════════════
    # ANALYSIS 2: ICS Threshold Optimization
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  ANALYSIS 2: ICS THRESHOLD ANALYSIS")
    print("  Win rate by ICS bucket")
    print("=" * 90)

    ics_buckets = defaultdict(lambda: {'w': 0, 'l': 0, 't': 0, 'pnl': []})
    for sig in signals:
        ics = sig.get('ics', 0)
        if not ics: continue
        ev = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                     sig['entry'], sig['sl'], sig['tp1'], sig['hold'])
        if ev is None: continue

        bucket = round(ics * 20) / 20  # round to nearest 0.05
        stats = ics_buckets[bucket]
        stats['t'] += 1
        stats['pnl'].append(ev['pnl'])
        if ev['outcome'] == 'WIN': stats['w'] += 1
        elif ev['outcome'] == 'LOSS': stats['l'] += 1

    print(f"\n  {'ICS Bucket':<15} {'Signals':<10} {'WR%':<10} {'Avg PnL':<12} {'PnL/Trade':<12}")
    print("  " + "-" * 60)
    for bucket in sorted(ics_buckets.keys()):
        stats = ics_buckets[bucket]
        t = stats['t']
        if t < 5: continue
        wr = stats['w'] / t * 100
        avg_pnl = sum(stats['pnl']) / t
        total_pnl = sum(stats['pnl'])
        print(f"  {bucket:<15.2f} {t:<10} {wr:<10.1f} {avg_pnl:<12.4f} {total_pnl/t:<12.4f}")

    # ═══════════════════════════════════════════════════════════════════
    # ANALYSIS 3: Conviction Threshold
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  ANALYSIS 3: CONVICTION vs WIN RATE")
    print("  (Multi-strategy signals only)")
    print("=" * 90)

    conv_buckets = defaultdict(lambda: {'w': 0, 'l': 0, 't': 0})
    for sig in signals:
        conv = sig.get('conviction', 0)
        if not conv: continue
        ev = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                     sig['entry'], sig['sl'], sig['tp1'], sig['hold'])
        if ev is None: continue

        bucket = round(conv * 10) / 10  # round to nearest 0.1
        stats = conv_buckets[bucket]
        stats['t'] += 1
        if ev['outcome'] == 'WIN': stats['w'] += 1
        elif ev['outcome'] == 'LOSS': stats['l'] += 1

    print(f"\n  {'Conviction':<12} {'Signals':<10} {'WR%':<10} {'Verdict':<15}")
    print("  " + "-" * 50)
    for bucket in sorted(conv_buckets.keys()):
        stats = conv_buckets[bucket]
        t = stats['t']
        if t < 5: continue
        wr = stats['w'] / t * 100
        verdict = 'STRONG' if wr > 55 else 'OK' if wr > 45 else 'WEAK' if wr > 35 else 'BAD'
        print(f"  {bucket:<12.1f} {t:<10} {wr:<10.1f} {verdict:<15}")

    # ═══════════════════════════════════════════════════════════════════
    # ANALYSIS 4: R:R Analysis
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  ANALYSIS 4: RISK-REWARD vs ACTUAL OUTCOME")
    print("  Is the R:R realistic?")
    print("=" * 90)

    rr_data = []
    for sig in signals:
        entry, sl, tp1 = sig['entry'], sig['sl'], sig['tp1']
        if not entry or not sl or not tp1 or sl == 0: continue
        rr = abs(tp1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        if rr <= 0 or rr > 10: continue

        ev = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                     entry, sl, tp1, sig['hold'])
        if ev is None: continue

        rr_data.append({
            'rr': rr, 'outcome': ev['outcome'], 'pnl': ev['pnl'],
            'mf': ev['mf'], 'ma': ev['ma'],
            'source': sig['source'], 'direction': sig['direction'],
        })

    rr_buckets = defaultdict(lambda: {'w': 0, 'l': 0, 't': 0, 'pnl': [], 'mf': [], 'ma': []})
    for d in rr_data:
        bucket = round(d['rr'] * 2) / 2  # round to nearest 0.5
        stats = rr_buckets[bucket]
        stats['t'] += 1
        stats['pnl'].append(d['pnl'])
        stats['mf'].append(d['mf'])
        stats['ma'].append(d['ma'])
        if d['outcome'] == 'WIN': stats['w'] += 1
        elif d['outcome'] == 'LOSS': stats['l'] += 1

    print(f"\n  {'R:R':<8} {'Signals':<10} {'WR%':<10} {'Avg PnL':<12} {'Avg MaxFav':<12} {'Avg MaxAdv':<12}")
    print("  " + "-" * 65)
    for bucket in sorted(rr_buckets.keys()):
        stats = rr_buckets[bucket]
        t = stats['t']
        if t < 5: continue
        wr = stats['w'] / t * 100
        avg_pnl = sum(stats['pnl']) / t
        avg_mf = sum(stats['mf']) / t
        avg_ma = sum(stats['ma']) / t
        print(f"  {bucket:<8.1f} {t:<10} {wr:<10.1f} {avg_pnl:<12.4f} {avg_mf:<12.4f} {avg_ma:<12.4f}")

    # ═══════════════════════════════════════════════════════════════════
    # ANALYSIS 5: Time-of-Day
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  ANALYSIS 5: TIME-OF-DAY PERFORMANCE")
    print("  UTC hour → win rate")
    print("=" * 90)

    hour_stats = defaultdict(lambda: {'w': 0, 'l': 0, 't': 0})
    for sig in signals:
        try:
            dt = datetime.strptime(sig['ts'], "%Y-%m-%d %H:%M:%S")
            hour = dt.hour
        except: continue
        ev = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                     sig['entry'], sig['sl'], sig['tp1'], sig['hold'])
        if ev is None: continue
        stats = hour_stats[hour]
        stats['t'] += 1
        if ev['outcome'] == 'WIN': stats['w'] += 1
        elif ev['outcome'] == 'LOSS': stats['l'] += 1

    print(f"\n  {'Hour(UTC)':<12} {'Signals':<10} {'WR%':<10} {'Verdict':<15}")
    print("  " + "-" * 50)
    for hour in range(24):
        stats = hour_stats[hour]
        t = stats['t']
        if t < 3: continue
        wr = stats['w'] / t * 100
        verdict = 'HOT' if wr > 55 else 'OK' if wr > 45 else 'COLD' if wr > 35 else 'BAD'
        bar = '#' * int(wr / 5)
        print(f"  {hour:02d}:00       {t:<10} {wr:<10.1f} {verdict:<15} {bar}")

    # ═══════════════════════════════════════════════════════════════════
    # ANALYSIS 6: Max Favorable Excursion (MFE) — TP placement
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  ANALYSIS 6: MAX FAVORABLE EXCURSION — TP OPTIMIZATION")
    print("  How far does price actually go vs where TP1 is set?")
    print("=" * 90)

    mfe_data = defaultdict(lambda: {'mfe': [], 'tp_hit': 0, 'total': 0})
    for sig in signals:
        entry, sl, tp1 = sig['entry'], sig['sl'], sig['tp1']
        if not entry or not tp1: continue
        ev = evaluate(price_cache, sorted_ts, sig['ts'], sig['direction'],
                     entry, sl, tp1, sig['hold'])
        if ev is None: continue

        source = sig['source']
        mfe_data[source]['mfe'].append(ev['mf'])
        mfe_data[source]['total'] += 1
        if ev['hit_tp']: mfe_data[source]['tp_hit'] += 1

    print(f"\n  {'Strategy':<30} {'Avg MFE%':<12} {'TP Hit%':<12} {'TP Miss%':<12} {'Signals':<10}")
    print("  " + "-" * 75)
    for source in sorted(mfe_data.keys()):
        d = mfe_data[source]
        if d['total'] < 10: continue
        avg_mfe = sum(d['mfe']) / len(d['mfe'])
        tp_hit = d['tp_hit'] / d['total'] * 100
        tp_miss = 100 - tp_hit
        print(f"  {source:<30} {avg_mfe:<12.4f} {tp_hit:<12.1f} {tp_miss:<12.1f} {d['total']:<10}")


if __name__ == '__main__':
    analyze()
