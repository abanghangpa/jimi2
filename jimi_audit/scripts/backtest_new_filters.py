#!/usr/bin/env python3
"""
Backtest with new filters: trend alignment (EMA200) and volume ratio.
Looks up ema_200 and vol_ratio from scan files for each signal timestamp.
"""

import json, glob, os, bisect, math, statistics
from datetime import datetime, timedelta
from collections import defaultdict

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
SIGNAL_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"

def load_scan_index():
    """Build index of timestamp -> (ema_200, vol_ratio, price, trend_dir) from scan files."""
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    index = {}
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
                ts = d.get("timestamp")
                if ts:
                    index[ts] = {
                        "ema_200": d.get("ema_200"),
                        "vol_ratio": d.get("vol_ratio"),
                        "price": d.get("price"),
                        "trend_dir": d.get("trend_dir"),
                        "atr": d.get("atr"),
                    }
        except:
            pass
    return index

def load_price_series():
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    timestamps, prices = [], []
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
                ts, price = d.get("timestamp"), d.get("price")
                if ts and price:
                    timestamps.append(ts)
                    prices.append(float(price))
        except:
            pass
    return timestamps, prices

def load_signals():
    signals = []
    with open(SIGNAL_FILE) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("fired") and d.get("entry") and d.get("sl") and d.get("tp1"):
                    signals.append(d)
            except:
                pass
    return signals

def check_outcome(ts_list, price_list, entry, sl, tp, direction, start_ts, max_hours=24):
    start_idx = bisect.bisect_left(ts_list, start_ts)
    if start_idx >= len(ts_list):
        return None
    try:
        start_dt = datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
    except:
        return None
    for i in range(start_idx, min(start_idx + max_hours * 4, len(ts_list))):
        try:
            bar_dt = datetime.strptime(ts_list[i], "%Y-%m-%d %H:%M:%S")
        except:
            continue
        if bar_dt - start_dt > timedelta(hours=max_hours):
            break
        price = price_list[i]
        if direction == "LONG":
            if price >= tp: return "WIN"
            if price <= sl: return "LOSS"
        elif direction == "SHORT":
            if price <= tp: return "WIN"
            if price >= sl: return "LOSS"
    return "TIMEOUT"

def wilson_interval(wins, total, z=1.96):
    if total == 0: return (0, 0, 0)
    p = wins / total
    denom = 1 + z**2 / total
    center = p + z**2 / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    return (round((center - spread) / denom * 100, 1),
            round((center + spread) / denom * 100, 1),
            round(p * 100, 1))

def run_scenario(signals, ts_list, price_list, scan_index, name, filters):
    """Run a backtest scenario with given filters."""
    wins, losses, timeouts, skipped = 0, 0, 0, 0
    by_strat = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0})
    by_strat_dir = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})

    for sig in signals:
        ts = sig["timestamp"]
        scan = scan_index.get(ts, {})
        price = sig["entry"]
        direction = sig["direction"]
        strat = sig["strategy"]

        # Apply filters
        skip = False
        for filt in filters:
            if not filt(sig, scan, price, direction):
                skip = True
                break
        if skip:
            skipped += 1
            continue

        outcome = check_outcome(ts_list, price_list, price, sig["sl"], sig["tp1"], direction, ts)
        if outcome is None:
            continue

        by_strat[strat]["total"] += 1
        if outcome == "WIN":
            wins += 1
            by_strat[strat]["wins"] += 1
        elif outcome == "LOSS":
            losses += 1
            by_strat[strat]["losses"] += 1
        else:
            timeouts += 1
            by_strat[strat]["timeouts"] += 1

        sd = f"{strat}_{direction}"
        by_strat_dir[sd]["total"] += 1
        if outcome == "WIN": by_strat_dir[sd]["wins"] += 1
        elif outcome == "LOSS": by_strat_dir[sd]["losses"] += 1

    settled = wins + losses
    wr = round(wins / settled * 100, 1) if settled > 0 else 0
    ci = wilson_interval(wins, settled) if settled >= 50 else None

    return {
        "name": name,
        "wins": wins, "losses": losses, "timeouts": timeouts,
        "skipped": skipped, "settled": settled, "win_rate": wr,
        "ci_95": ci,
        "signals": wins + losses + timeouts,
        "by_strategy": {k: {
            "n": v["wins"] + v["losses"],
            "wr": round(v["wins"] / (v["wins"] + v["losses"]) * 100, 1) if (v["wins"] + v["losses"]) > 0 else 0
        } for k, v in sorted(by_strat.items()) if v["wins"] + v["losses"] >= 20},
        "by_direction": {k: {
            "n": v["total"],
            "wr": round(v["wins"] / (v["wins"] + v["losses"]) * 100, 1) if (v["wins"] + v["losses"]) > 0 else 0
        } for k, v in sorted(by_strat_dir.items()) if v["total"] >= 20},
    }


def main():
    print("Loading data...")
    ts_list, price_list = load_price_series()
    signals = load_signals()
    scan_index = load_scan_index()
    print(f"Prices: {len(ts_list)}, Signals: {len(signals)}, Scans: {len(scan_index)}")

    # Count how many signals have ema_200 / vol_ratio data
    has_ema = sum(1 for s in signals if scan_index.get(s["timestamp"], {}).get("ema_200"))
    has_vol = sum(1 for s in signals if scan_index.get(s["timestamp"], {}).get("vol_ratio"))
    print(f"Signals with ema_200 data: {has_ema}/{len(signals)}")
    print(f"Signals with vol_ratio data: {has_vol}/{len(signals)}")

    # Define filter functions
    def filt_baseline(sig, scan, price, direction):
        return True

    def filt_trend_aligned(sig, scan, price, direction):
        ema = scan.get("ema_200")
        if ema is None:
            return True  # no data = don't filter
        if direction == "LONG":
            return price > ema
        else:
            return price < ema

    def filt_trend_aligned_strict(sig, scan, price, direction):
        """Price must be >1% above/below EMA200."""
        ema = scan.get("ema_200")
        if ema is None:
            return True
        dist_pct = (price - ema) / ema * 100
        if direction == "LONG":
            return dist_pct > 1.0
        else:
            return dist_pct < -1.0

    def filt_vol_above_015(sig, scan, price, direction):
        vr = scan.get("vol_ratio")
        if vr is None:
            return True
        return vr > 0.15

    def filt_vol_above_020(sig, scan, price, direction):
        vr = scan.get("vol_ratio")
        if vr is None:
            return True
        return vr > 0.20

    def filt_vol_above_025(sig, scan, price, direction):
        vr = scan.get("vol_ratio")
        if vr is None:
            return True
        return vr > 0.25

    def filt_trend_and_vol(sig, scan, price, direction):
        return filt_trend_aligned(sig, scan, price, direction) and filt_vol_above_015(sig, scan, price, direction)

    def filt_trend_and_vol_strict(sig, scan, price, direction):
        return filt_trend_aligned(sig, scan, price, direction) and filt_vol_above_020(sig, scan, price, direction)

    def filt_with_trend_only(sig, scan, price, direction):
        """Only trade in direction of trend_dir from scan."""
        trend = scan.get("trend_dir")
        if trend is None:
            return True
        if direction == "LONG" and trend == "DOWN":
            return False
        if direction == "SHORT" and trend == "UP":
            return False
        return True

    def filt_ema_cross(sig, scan, price, direction):
        """Price must be on correct side of EMA200 AND trend_dir must align."""
        ema_ok = filt_trend_aligned(sig, scan, price, direction)
        trend_ok = filt_with_trend_only(sig, scan, price, direction)
        return ema_ok and trend_ok

    # Define scenarios
    scenarios = [
        ("BASELINE", [filt_baseline]),
        ("trend_aligned (EMA200)", [filt_trend_aligned]),
        ("trend_aligned_strict (>1%)", [filt_trend_aligned_strict]),
        ("vol_ratio > 0.15", [filt_vol_above_015]),
        ("vol_ratio > 0.20", [filt_vol_above_020]),
        ("vol_ratio > 0.25", [filt_vol_above_025]),
        ("trend + vol>0.15", [filt_trend_and_vol]),
        ("trend + vol>0.20", [filt_trend_and_vol_strict]),
        ("trend_dir aligned", [filt_with_trend_only]),
        ("EMA200 + trend_dir", [filt_ema_cross]),
    ]

    results = []
    for name, filters in scenarios:
        print(f"  Running: {name}...")
        r = run_scenario(signals, ts_list, price_list, scan_index, name, filters)
        results.append(r)

    # Print results table
    print("\n" + "=" * 80)
    print(f"{'Filter':<30} {'Signals':>8} {'Skip':>6} {'Wins':>6} {'Loss':>6} {'WR%':>7} {'95% CI':>15}")
    print("=" * 80)
    for r in results:
        ci_str = f"[{r['ci_95'][0]}-{r['ci_95'][2]}%]" if r['ci_95'] else "—"
        print(f"{r['name']:<30} {r['signals']:>8} {r['skipped']:>6} {r['wins']:>6} {r['losses']:>6} {r['win_rate']:>6.1f}% {ci_str:>15}")

    # Print strategy breakdown for best filters
    print("\n" + "=" * 80)
    print("STRATEGY BREAKDOWN — Best Filters")
    print("=" * 80)
    for r in results[1:4]:  # top 3 non-baseline
        print(f"\n--- {r['name']} ---")
        for strat, sd in sorted(r['by_strategy'].items(), key=lambda x: -x[1]['wr']):
            print(f"  {strat:>25}: {sd['wr']}% WR (n={sd['n']})")

    # Print direction breakdown
    print("\n" + "=" * 80)
    print("DIRECTION BREAKDOWN — Best Filters")
    print("=" * 80)
    for r in results[1:4]:
        print(f"\n--- {r['name']} ---")
        for d, sd in sorted(r['by_direction'].items()):
            print(f"  {d:>30}: {sd['wr']}% WR (n={sd['n']})")

    # Save results
    with open("backtest_new_filters_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\n✅ Results saved to backtest_new_filters_results.json")


if __name__ == "__main__":
    main()
