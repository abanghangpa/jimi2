#!/usr/bin/env python3
"""
Backtest: Compare current system vs regime-router + adaptive gating.

Loads historical scans, simulates both paths, compares outcomes.
"""
import sys
import os
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCAN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'scans')

# ── Hold windows per strategy (from confirmation.py) ──
HOLD_WINDOWS = {
    'main_pipeline': 4,
    'failed_breakout': 8,
    'funding_arb': 4,
    'orderbook_imbalance': 4,
    'trade_flow': 4,
    'cross_asset': 4,
    'mtf_confluence': 4,
    'structural_break': 8,
    'scalp_v2': 2,
    'momentum_v3': 4,
    'squeeze_breakout': 4,
    'positioning_fade': 2,
    'kill_zone': 4,
    'liquidity_grab': 4,
    'taker_flow': 2,
    'regime_switch': 4,
    'power_of_3': 4,
    'cascade': 4,
    'macro_surprise': 8,
    'whale_watch': 4,
    'vol_rotation': 4,
    'liquidation_cascade': 4,
    'judas_sweep': 4,
}


# ── Regime Router Matrix ──
ROUTER_MATRIX = {
    "STRONG_DOWN": {
        "blocked": ["structural_break", "mtf_confluence", "regime_switch"]
    },
    "DOWN": {
        "blocked": ["structural_break", "regime_switch"]
    },
    "RANGING": {
        "blocked": ["regime_switch"]
    },
    "UP": {
        "blocked": []
    },
    "STRONG_UP": {
        "blocked": ["positioning_fade"]
    },
}


def classify_regime(trend_dir):
    if not trend_dir:
        return 'RANGING'
    if 'STRONG_DOWN' in trend_dir:
        return 'STRONG_DOWN'
    elif 'DOWN' in trend_dir:
        return 'DOWN'
    elif 'STRONG_UP' in trend_dir:
        return 'STRONG_UP'
    elif 'UP' in trend_dir:
        return 'UP'
    return 'RANGING'


def load_scans():
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    scans = []
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
            d['_file'] = os.path.basename(f)
            scans.append(d)
        except:
            pass
    return scans


def find_price_at_offset(price_cache, sorted_ts, base_ts, hours):
    try:
        base_dt = datetime.strptime(base_ts, "%Y-%m-%d %H:%M:%S")
    except:
        return None
    target = base_dt + timedelta(hours=hours)
    best = None
    best_diff = timedelta(hours=999)
    for t in sorted_ts:
        try:
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except:
            continue
        diff = abs(dt - target)
        if diff < best_diff:
            best_diff = diff
            best = price_cache[t]
    if best_diff < timedelta(hours=2):
        return best
    return None


def evaluate_signal(price_cache, sorted_ts, scan, direction, entry_price, sl, tp1, hold_hours):
    ts = scan.get('timestamp', '')
    if not ts or not entry_price:
        return None

    exit_price = find_price_at_offset(price_cache, sorted_ts, ts, hold_hours)
    if exit_price is None:
        return None

    if direction == 'LONG':
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        hit_tp1 = exit_price >= tp1 if tp1 > 0 else False
        hit_sl = exit_price <= sl if sl > 0 else False
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100
        hit_tp1 = exit_price <= tp1 if tp1 > 0 else False
        hit_sl = exit_price >= sl if sl > 0 else False

    if hit_tp1:
        outcome = 'WIN'
    elif hit_sl:
        outcome = 'LOSS'
    elif pnl_pct > 0.1:
        outcome = 'WIN'
    elif pnl_pct < -0.1:
        outcome = 'LOSS'
    else:
        outcome = 'NEUTRAL'

    return {
        'outcome': outcome,
        'pnl_pct': round(pnl_pct, 4),
        'hit_tp1': hit_tp1,
        'hit_sl': hit_sl,
        'exit_price': exit_price,
    }


def run_backtest():
    print("Loading scans...")
    scans = load_scans()
    print(f"Loaded {len(scans)} scans")

    # Build price cache
    price_cache = {}
    for s in scans:
        ts = s.get('timestamp')
        price = s.get('price')
        if ts and price:
            price_cache[ts] = float(price)
    sorted_ts = sorted(price_cache.keys())

    # ── Collect all signals from scans ──
    all_signals = []
    for scan in scans:
        if scan.get('status') != 'SIGNAL':
            continue

        ts = scan.get('timestamp', '')
        price = scan.get('price', 0)
        direction = scan.get('direction', '')
        source = scan.get('source', 'main_pipeline')
        trend_dir = scan.get('trend_dir', '')
        regime = classify_regime(trend_dir)

        # Get strategy signals from multi_strategy
        ms = scan.get('multi_strategy', {})
        strategy_signals = ms.get('all_signals', [])

        # Add main pipeline signal
        entry = scan.get('entry', price)
        sl = scan.get('sl', 0)
        tp1 = scan.get('tp1', 0)

        all_signals.append({
            'timestamp': ts,
            'price': price,
            'direction': direction,
            'source': source,
            'regime': regime,
            'trend_dir': trend_dir,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'hold_hours': HOLD_WINDOWS.get(source, 4),
            'strategy': source,
        })

        # Add multi-strategy signals
        for sig in strategy_signals:
            strat_name = sig.get('strategy', '')
            strat_dir = sig.get('direction', '')
            strat_conv = sig.get('conviction', 0)
            if not strat_name or not strat_dir:
                continue
            all_signals.append({
                'timestamp': ts,
                'price': price,
                'direction': strat_dir,
                'source': f'strategy:{strat_name}',
                'regime': regime,
                'trend_dir': trend_dir,
                'entry': price,
                'sl': sig.get('sl', 0),
                'tp1': sig.get('tp1', 0),
                'hold_hours': HOLD_WINDOWS.get(strat_name, 4),
                'strategy': strat_name,
                'conviction': strat_conv,
            })

    print(f"Total signals collected: {len(all_signals)}")

    # ── Run two scenarios ──
    results = {
        'current': {'signals': 0, 'wins': 0, 'losses': 0, 'neutral': 0, 'skipped': 0},
        'with_gating': {'signals': 0, 'wins': 0, 'losses': 0, 'neutral': 0, 'skipped': 0, 'router_blocked': 0, 'adaptive_vetoed': 0},
    }

    # Track per-strategy+regime stats for adaptive gating simulation
    strategy_regime_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})

    # Sort by timestamp for proper sequential evaluation
    all_signals.sort(key=lambda x: x['timestamp'])

    for i, sig in enumerate(all_signals):
        direction = sig['direction']
        entry = sig['entry']
        sl = sig['sl']
        tp1 = sig['tp1']
        hold_hours = sig['hold_hours']
        regime = sig['regime']
        strategy = sig['strategy']
        source = sig['source']

        if not entry or not direction:
            continue

        # Evaluate outcome
        outcome = evaluate_signal(price_cache, sorted_ts, sig, direction, entry, sl, tp1, hold_hours)
        if outcome is None:
            continue

        # ── Current system: all signals pass ──
        results['current']['signals'] += 1
        if outcome['outcome'] == 'WIN':
            results['current']['wins'] += 1
        elif outcome['outcome'] == 'LOSS':
            results['current']['losses'] += 1
        else:
            results['current']['neutral'] += 1

        # ── With gating: apply router + adaptive ──
        # 1. Regime router check
        blocked = ROUTER_MATRIX.get(regime, {}).get('blocked', [])
        if strategy in blocked:
            results['with_gating']['router_blocked'] += 1
            results['with_gating']['skipped'] += 1
            # Still record outcome for stats
            key = (strategy, regime, direction)
            strategy_regime_stats[key]['total'] += 1
            if outcome['outcome'] == 'WIN':
                strategy_regime_stats[key]['wins'] += 1
            elif outcome['outcome'] == 'LOSS':
                strategy_regime_stats[key]['losses'] += 1
            continue

        # 2. Adaptive gating check (using rolling stats)
        key = (strategy, regime, direction)
        stats = strategy_regime_stats[key]
        if stats['total'] >= 15:
            wr = stats['wins'] / stats['total'] * 100
            if wr < 35.0:
                results['with_gating']['adaptive_vetoed'] += 1
                results['with_gating']['skipped'] += 1
                # Record outcome
                stats['total'] += 1
                if outcome['outcome'] == 'WIN':
                    stats['wins'] += 1
                elif outcome['outcome'] == 'LOSS':
                    stats['losses'] += 1
                continue

        # Signal passes
        results['with_gating']['signals'] += 1
        if outcome['outcome'] == 'WIN':
            results['with_gating']['wins'] += 1
        elif outcome['outcome'] == 'LOSS':
            results['with_gating']['losses'] += 1
        else:
            results['with_gating']['neutral'] += 1

        # Record for rolling stats
        stats['total'] += 1
        if outcome['outcome'] == 'WIN':
            stats['wins'] += 1
        elif outcome['outcome'] == 'LOSS':
            stats['losses'] += 1

    # ── Print Results ──
    print("\n" + "=" * 80)
    print("  BACKTEST RESULTS: Current System vs Regime Router + Adaptive Gating")
    print("=" * 80)

    for label, r in results.items():
        total = r['signals']
        wins = r['wins']
        losses = r['losses']
        neutral = r['neutral']
        wr = wins / total * 100 if total > 0 else 0

        print(f"\n  {'CURRENT SYSTEM' if label == 'current' else 'WITH GATING'}:")
        print(f"    Signals: {total}")
        print(f"    Wins: {wins} | Losses: {losses} | Neutral: {neutral}")
        print(f"    Win Rate: {wr:.1f}%")
        if 'skipped' in r:
            print(f"    Router Blocked: {r.get('router_blocked', 0)}")
            print(f"    Adaptive Vetoed: {r.get('adaptive_vetoed', 0)}")
            print(f"    Total Skipped: {r['skipped']}")

    # ── Impact Summary ──
    c = results['current']
    g = results['with_gating']
    c_wr = c['wins'] / c['signals'] * 100 if c['signals'] > 0 else 0
    g_wr = g['wins'] / g['signals'] * 100 if g['signals'] > 0 else 0

    print(f"\n  IMPACT:")
    print(f"    Win Rate: {c_wr:.1f}% → {g_wr:.1f}% ({g_wr - c_wr:+.1f}%)")
    print(f"    Signals Reduced: {c['signals']} → {g['signals']} ({c['signals'] - g['signals']} fewer)")
    print(f"    False Signals Avoided: {g.get('router_blocked', 0) + g.get('adaptive_vetoed', 0)}")

    # ── Per-strategy breakdown ──
    print(f"\n  PER-STRATEGY BREAKDOWN (strategies with 10+ signals):")
    print(f"  {'Strategy':<30} {'Regime':<15} {'Dir':<8} {'Current WR':<12} {'Gated WR':<12} {'Blocked':<10}")
    print("  " + "-" * 90)

    for key in sorted(strategy_regime_stats.keys()):
        strategy, regime, direction = key
        stats = strategy_regime_stats[key]
        if stats['total'] < 10:
            continue

        total = stats['total']
        wins = stats['wins']
        wr = wins / total * 100 if total > 0 else 0

        # Check if this would be blocked
        blocked_by_router = strategy in ROUTER_MATRIX.get(regime, {}).get('blocked', [])
        blocked_by_adaptive = not blocked_by_router and total >= 15 and wr < 35.0
        blocked = 'ROUTER' if blocked_by_router else 'ADAPTIVE' if blocked_by_adaptive else ''

        print(f"  {strategy:<30} {regime:<15} {direction:<8} {wr:<12.1f} {'BLOCKED' if blocked else f'{wr:.1f}%':<12} {blocked:<10}")


if __name__ == '__main__':
    run_backtest()
