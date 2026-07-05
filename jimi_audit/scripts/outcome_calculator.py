#!/usr/bin/env python3
"""
JIMI Outcome Calculator
Treats each fired signal as a trade. Checks if TP or SL was hit first
using actual price data from scan files.
"""

import json
import glob
import os
import bisect
import statistics
import math
from datetime import datetime, timedelta
from collections import Counter, defaultdict

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
SIGNAL_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"
OUTPUT = "/root/.openclaw/workspace/jimi_audit/data/outcome_results.json"
MIN_SAMPLES = 30
CONFIDENCE_MIN = 50


def load_price_series():
    """Build a sorted price+timestamp series from scan files for lookups."""
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    timestamps = []
    prices = []
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
                ts = d.get("timestamp")
                price = d.get("price")
                if ts and price:
                    timestamps.append(ts)
                    prices.append(price)
        except:
            pass
    return timestamps, prices


def load_fired_signals():
    """Load fired signals from strategy_signals.jsonl."""
    signals = []
    if not os.path.exists(SIGNAL_FILE):
        return signals
    with open(SIGNAL_FILE) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("fired") and d.get("entry") and d.get("sl") and d.get("tp1"):
                    signals.append(d)
            except:
                pass
    return signals


def find_price_at(ts_list, price_list, target_ts):
    """Binary search for price at target timestamp."""
    idx = bisect.bisect_left(ts_list, target_ts)
    best_idx = None
    best_diff = timedelta(hours=999)
    for candidate in [idx - 1, idx, idx + 1]:
        if 0 <= candidate < len(ts_list):
            try:
                dt1 = datetime.strptime(ts_list[candidate], "%Y-%m-%d %H:%M:%S")
                dt2 = datetime.strptime(target_ts, "%Y-%m-%d %H:%M:%S")
                diff = abs(dt1 - dt2)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = candidate
            except:
                pass
    if best_idx is not None and best_diff < timedelta(hours=1):
        return price_list[best_idx]
    return None


def check_outcome(ts_list, price_list, signal, max_hours=24):
    """
    For a fired signal, walk forward through price data to determine:
    - Did price hit TP first? → WIN
    - Did price hit SL first? → LOSS
    - Neither within max_hours? → TIMEOUT
    """
    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp1"]
    direction = signal["direction"]
    start_ts = signal["timestamp"]

    if not start_ts or not entry or not sl or not tp:
        return None

    # Find start index
    start_idx = bisect.bisect_left(ts_list, start_ts)
    if start_idx >= len(ts_list):
        return None

    # Walk forward
    try:
        start_dt = datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
    except:
        return None

    for i in range(start_idx, min(start_idx + max_hours * 4, len(ts_list))):  # ~15min bars
        try:
            bar_dt = datetime.strptime(ts_list[i], "%Y-%m-%d %H:%M:%S")
        except:
            continue
        if bar_dt - start_dt > timedelta(hours=max_hours):
            break

        price = price_list[i]

        if direction == "LONG":
            if price >= tp:
                return {"outcome": "WIN", "exit_price": tp, "bars_held": i - start_idx,
                        "hours_held": round((bar_dt - start_dt).total_seconds() / 3600, 2)}
            if price <= sl:
                return {"outcome": "LOSS", "exit_price": sl, "bars_held": i - start_idx,
                        "hours_held": round((bar_dt - start_dt).total_seconds() / 3600, 2)}
        elif direction == "SHORT":
            if price <= tp:
                return {"outcome": "WIN", "exit_price": tp, "bars_held": i - start_idx,
                        "hours_held": round((bar_dt - start_dt).total_seconds() / 3600, 2)}
            if price >= sl:
                return {"outcome": "LOSS", "exit_price": sl, "bars_held": i - start_idx,
                        "hours_held": round((bar_dt - start_dt).total_seconds() / 3600, 2)}

    return {"outcome": "TIMEOUT", "exit_price": None, "bars_held": None, "hours_held": None}


def wilson_interval(wins, total, z=1.96):
    if total == 0:
        return {"lower": 0, "upper": 0, "point": 0}
    p = wins / total
    denom = 1 + z**2 / total
    center = p + z**2 / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    return {
        "lower": round((center - spread) / denom * 100, 1),
        "upper": round((center + spread) / denom * 100, 1),
        "point": round(p * 100, 1)
    }


def main():
    print("Loading price series...")
    ts_list, price_list = load_price_series()
    print(f"Loaded {len(ts_list)} price points")

    print("Loading fired signals...")
    signals = load_fired_signals()
    print(f"Loaded {len(signals)} fired signals with entry/SL/TP")

    if not signals:
        print("No fired signals found!")
        return

    print("Computing outcomes...")
    results = []
    by_strategy = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0,
                                        "rr_achieved": [], "hours_held": [], "convictions": []})
    by_strategy_dir = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0})
    by_conviction_bucket = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0})

    for sig in signals:
        outcome = check_outcome(ts_list, price_list, sig)
        if outcome is None:
            continue

        strat = sig.get("strategy", "unknown")
        direction = sig.get("direction", "UNKNOWN")
        conviction = sig.get("conviction", 0)
        rr1 = sig.get("rr1", 0)

        result = {
            "timestamp": sig["timestamp"],
            "strategy": strat,
            "direction": direction,
            "entry": sig["entry"],
            "sl": sig["sl"],
            "tp1": sig["tp1"],
            "conviction": conviction,
            "rr1_target": rr1,
            **outcome
        }
        results.append(result)

        by_strategy[strat]["total"] += 1
        by_strategy[strat]["convictions"].append(conviction)
        if outcome["outcome"] == "WIN":
            by_strategy[strat]["wins"] += 1
            by_strategy[strat]["rr_achieved"].append(rr1)
        elif outcome["outcome"] == "LOSS":
            by_strategy[strat]["losses"] += 1
            by_strategy[strat]["rr_achieved"].append(-1)  # -1R
        else:
            by_strategy[strat]["timeouts"] += 1

        if outcome["hours_held"] is not None:
            by_strategy[strat]["hours_held"].append(outcome["hours_held"])

        strat_dir = f"{strat}_{direction}"
        by_strategy_dir[strat_dir]["total"] += 1
        if outcome["outcome"] == "WIN": by_strategy_dir[strat_dir]["wins"] += 1
        elif outcome["outcome"] == "LOSS": by_strategy_dir[strat_dir]["losses"] += 1
        else: by_strategy_dir[strat_dir]["timeouts"] += 1

        # Conviction buckets
        if conviction < 0.3: c_bucket = "low (<0.3)"
        elif conviction < 0.5: c_bucket = "medium (0.3-0.5)"
        elif conviction < 0.7: c_bucket = "high (0.5-0.7)"
        else: c_bucket = "very_high (0.7+)"
        by_conviction_bucket[c_bucket]["total"] += 1
        if outcome["outcome"] == "WIN": by_conviction_bucket[c_bucket]["wins"] += 1
        elif outcome["outcome"] == "LOSS": by_conviction_bucket[c_bucket]["losses"] += 1
        else: by_conviction_bucket[c_bucket]["timeouts"] += 1

    # Build summary
    def strategy_summary(d, name):
        n = d["total"]
        if n < MIN_SAMPLES:
            return {"n": n, "insufficient_data": True, "note": f"Need {MIN_SAMPLES - n} more"}
        wins = d["wins"]
        losses = d["losses"]
        timeouts = d["timeouts"]
        settled = wins + losses
        ci = wilson_interval(wins, settled) if settled >= CONFIDENCE_MIN else None
        avg_rr = round(statistics.mean(d["rr_achieved"]), 3) if d["rr_achieved"] else 0
        avg_hours = round(statistics.mean(d["hours_held"]), 1) if d["hours_held"] else None
        return {
            "n": n,
            "wins": wins,
            "losses": losses,
            "timeouts": timeouts,
            "win_rate": round(wins / settled * 100, 1) if settled > 0 else None,
            "win_rate_95ci": ci,
            "avg_rr": avg_rr,
            "avg_conviction": round(statistics.mean(d["convictions"]), 3) if d["convictions"] else 0,
            "avg_hours_held": avg_hours,
            "settled_trades": settled,
        }

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "methodology": "Signal = Trade. Each fired signal treated as a trade at entry price. Outcome = TP hit first (WIN) or SL hit first (LOSS). Price data from scan files (~15min bars).",
        "total_signals_evaluated": len(results),
        "by_strategy": {k: strategy_summary(v, k) for k, v in sorted(by_strategy.items())},
        "by_strategy_direction": {k: {"n": v["total"],
                                       "wins": v["wins"], "losses": v["losses"], "timeouts": v["timeouts"],
                                       "win_rate": round(v["wins"]/(v["wins"]+v["losses"])*100, 1) if (v["wins"]+v["losses"]) > 0 else None}
                                   for k, v in sorted(by_strategy_dir.items()) if v["total"] >= MIN_SAMPLES},
        "by_conviction_bucket": {k: {"n": v["total"],
                                      "wins": v["wins"], "losses": v["losses"], "timeouts": v["timeouts"],
                                      "win_rate": round(v["wins"]/(v["wins"]+v["losses"])*100, 1) if (v["wins"]+v["losses"]) > 0 else None}
                                  for k, v in sorted(by_conviction_bucket.items())},
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults written to {OUTPUT}")
    print(f"{len(results)} trades evaluated")
    print("\n=== SUMMARY BY STRATEGY ===")
    for k, v in sorted(summary["by_strategy"].items()):
        if v.get("insufficient_data"):
            print(f"  {k}: n={v['n']} (insufficient)")
        else:
            ci_str = f" [{v['win_rate_95ci']['lower']}-{v['win_rate_95ci']['upper']}%]" if v.get("win_rate_95ci") else ""
            print(f"  {k}: {v['win_rate']}% WR (n={v['settled_trades']}){ci_str}  avg_RR={v['avg_rr']}")


if __name__ == "__main__":
    main()

def compute_outcomes_summary(ts_list, price_list, signals):
    """Compute trade outcomes summary for integration with deep_analysis_prep."""
    results = []
    by_strategy = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0,
                                        "rr_achieved": [], "hours_held": [], "convictions": []})
    by_strategy_dir = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0})
    by_conviction_bucket = defaultdict(lambda: {"wins": 0, "losses": 0, "timeouts": 0, "total": 0})

    for sig in signals:
        if not sig.get("fired") or not sig.get("entry") or not sig.get("sl") or not sig.get("tp1"):
            continue
        outcome = check_outcome(ts_list, price_list, sig)
        if outcome is None:
            continue
        strat = sig.get("strategy", "unknown")
        direction = sig.get("direction", "UNKNOWN")
        conviction = sig.get("conviction", 0)
        rr1 = sig.get("rr1", 0)
        results.append({"timestamp": sig["timestamp"], "strategy": strat, "direction": direction,
                        "entry": sig["entry"], "sl": sig["sl"], "tp1": sig["tp1"],
                        "conviction": conviction, "rr1_target": rr1, **outcome})
        by_strategy[strat]["total"] += 1
        by_strategy[strat]["convictions"].append(conviction)
        if outcome["outcome"] == "WIN":
            by_strategy[strat]["wins"] += 1
            by_strategy[strat]["rr_achieved"].append(rr1)
        elif outcome["outcome"] == "LOSS":
            by_strategy[strat]["losses"] += 1
            by_strategy[strat]["rr_achieved"].append(-1)
        else:
            by_strategy[strat]["timeouts"] += 1
        if outcome["hours_held"] is not None:
            by_strategy[strat]["hours_held"].append(outcome["hours_held"])
        strat_dir = f"{strat}_{direction}"
        by_strategy_dir[strat_dir]["total"] += 1
        if outcome["outcome"] == "WIN": by_strategy_dir[strat_dir]["wins"] += 1
        elif outcome["outcome"] == "LOSS": by_strategy_dir[strat_dir]["losses"] += 1
        else: by_strategy_dir[strat_dir]["timeouts"] += 1
        if conviction < 0.3: c_bucket = "low (<0.3)"
        elif conviction < 0.5: c_bucket = "medium (0.3-0.5)"
        elif conviction < 0.7: c_bucket = "high (0.5-0.7)"
        else: c_bucket = "very_high (0.7+)"
        by_conviction_bucket[c_bucket]["total"] += 1
        if outcome["outcome"] == "WIN": by_conviction_bucket[c_bucket]["wins"] += 1
        elif outcome["outcome"] == "LOSS": by_conviction_bucket[c_bucket]["losses"] += 1
        else: by_conviction_bucket[c_bucket]["timeouts"] += 1

    def strat_summary(d):
        n = d["total"]
        if n < 30:
            return {"n": n, "insufficient_data": True}
        wins, losses, timeouts = d["wins"], d["losses"], d["timeouts"]
        settled = wins + losses
        ci = wilson_interval(wins, settled) if settled >= 50 else None
        return {"n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
                "win_rate": round(wins/settled*100, 1) if settled > 0 else None,
                "win_rate_95ci": ci,
                "avg_rr": round(statistics.mean(d["rr_achieved"]), 3) if d["rr_achieved"] else 0,
                "avg_conviction": round(statistics.mean(d["convictions"]), 3) if d["convictions"] else 0,
                "avg_hours_held": round(statistics.mean(d["hours_held"]), 1) if d["hours_held"] else None,
                "settled_trades": settled}

    return {
        "total_trades_evaluated": len(results),
        "by_strategy": {k: strat_summary(v) for k, v in sorted(by_strategy.items())},
        "by_strategy_direction": {k: {"n": v["total"], "wins": v["wins"], "losses": v["losses"],
                                       "win_rate": round(v["wins"]/(v["wins"]+v["losses"])*100, 1) if (v["wins"]+v["losses"]) > 0 else None}
                                   for k, v in sorted(by_strategy_dir.items()) if v["total"] >= 30},
        "by_conviction_bucket": {k: {"n": v["total"], "wins": v["wins"], "losses": v["losses"],
                                      "win_rate": round(v["wins"]/(v["wins"]+v["losses"])*100, 1) if (v["wins"]+v["losses"]) > 0 else None}
                                  for k, v in sorted(by_conviction_bucket.items())},
    }

