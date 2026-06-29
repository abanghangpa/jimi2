#!/usr/bin/env python3
"""
JIMI Deep Analysis Pre-Processor v2
Timeframe-aware evaluation with signal type tagging.
"""

import json
import glob
import os
import statistics
from datetime import datetime, timedelta
from collections import Counter, defaultdict

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
OUTPUT = "/root/.openclaw/workspace/jimi_audit/data/deep_analysis_summary.json"
MIN_SAMPLES = 15  # Don't report win rates below this

# Signal type → recommended hold window (hours)
HOLD_WINDOWS = {
    "strategy:scalp_v2": 1,
    "strategy:orderbook_imbalance": 2,
    "strategy:trade_flow": 2,
    "strategy:funding_arb": 4,
    "strategy:failed_breakout": 8,
    "strategy:structural_break": 8,
    "main_pipeline": 2,
    "unknown": 4,
}

def load_scans():
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    scans = []
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
                d["_file"] = os.path.basename(f)
                scans.append(d)
        except Exception as e:
            print(f"  Skip {f}: {e}")
    return scans

def get_hold_window(source):
    """Get recommended hold hours for a signal source."""
    return HOLD_WINDOWS.get(source, 4)

def classify_regime(scan):
    """Classify market regime: trending_down, trending_up, ranging."""
    trend = scan.get("trend_dir", "UNKNOWN")
    swing = scan.get("swing_bias", "UNKNOWN")
    if "STRONG_DOWN" in trend or "DOWN" in trend:
        return "trending_down"
    elif "STRONG_UP" in trend or "UP" in trend:
        return "trending_up"
    else:
        return "ranging"

def compute_ics_stats(scans):
    ics_vals = [s["ics"] for s in scans if "ics" in s and s["ics"] is not None]
    if not ics_vals:
        return {}
    buckets = {"<0.40": [], "0.40-0.50": [], "0.50-0.55": [], "0.55-0.60": [], "0.60-0.65": [], "0.65+": []}
    for v in ics_vals:
        if v < 0.40: buckets["<0.40"].append(v)
        elif v < 0.50: buckets["0.40-0.50"].append(v)
        elif v < 0.55: buckets["0.50-0.55"].append(v)
        elif v < 0.60: buckets["0.55-0.60"].append(v)
        elif v < 0.65: buckets["0.60-0.65"].append(v)
        else: buckets["0.65+"].append(v)
    weekly = defaultdict(list)
    for s in scans:
        ts = s.get("timestamp", "")
        if ts:
            try:
                dt = datetime.strptime(ts[:10], "%Y-%m-%d")
                week_key = dt.strftime("%Y-W%U")
                if "ics" in s and s["ics"] is not None:
                    weekly[week_key].append(s["ics"])
            except: pass
    weekly_avg = {k: round(statistics.mean(v), 4) for k, v in sorted(weekly.items()) if v}
    return {
        "count": len(ics_vals),
        "mean": round(statistics.mean(ics_vals), 4),
        "median": round(statistics.median(ics_vals), 4),
        "stdev": round(statistics.stdev(ics_vals), 4) if len(ics_vals) > 1 else 0,
        "min": round(min(ics_vals), 4),
        "max": round(max(ics_vals), 4),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "bucket_pcts": {k: round(len(v)/len(ics_vals)*100, 1) for k, v in buckets.items()},
        "weekly_trend": weekly_avg,
    }

def compute_direction_stats(scans):
    dir_counts = Counter()
    resolver_counts = Counter()
    signals = []
    for s in scans:
        d = s.get("direction", "UNKNOWN")
        dir_counts[d] += 1
        resolver = s.get("direction_resolver", {})
        action = resolver.get("action", "UNKNOWN")
        resolver_counts[action] += 1
        if s.get("status") == "SIGNAL":
            source = s.get("source", "unknown")
            signals.append({
                "timestamp": s.get("timestamp"),
                "price": s.get("price"),
                "direction": d,
                "action": action,
                "ics": s.get("ics"),
                "swing_bias": s.get("swing_bias"),
                "trend_dir": s.get("trend_dir"),
                "source": source,
                "hold_hours": get_hold_window(source),
                "regime": classify_regime(s),
            })
    return {
        "direction_counts": dict(dir_counts),
        "direction_pcts": {k: round(v/len(scans)*100, 1) for k, v in dir_counts.items()},
        "resolver_counts": dict(resolver_counts),
        "resolver_pcts": {k: round(v/len(scans)*100, 1) for k, v in resolver_counts.items()},
        "total_signals": len(signals),
        "signal_rate": round(len(signals)/len(scans)*100, 1),
        "signals": signals,
    }

def compute_signal_accuracy(scans, signals):
    """Timeframe-aware accuracy: measure at each signal's recommended hold window."""
    price_by_ts = {}
    for s in scans:
        ts = s.get("timestamp")
        price = s.get("price")
        if ts and price:
            price_by_ts[ts] = price
    sorted_ts = sorted(price_by_ts.keys())

    def find_price_at_offset(base_ts, hours):
        try:
            base_dt = datetime.strptime(base_ts, "%Y-%m-%d %H:%M:%S")
            target = base_dt + timedelta(hours=hours)
            best = None
            best_diff = timedelta(hours=999)
            for t in sorted_ts:
                dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
                diff = abs(dt - target)
                if diff < best_diff:
                    best_diff = diff
                    best = price_by_ts[t]
            if best_diff < timedelta(hours=2):
                return best
        except: pass
        return None

    # Results by signal type × hold window
    by_type = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    # Results by direction × hold window
    by_dir_window = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    # Results by regime × direction
    by_regime_dir = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    # Results by ICS bucket × hold window
    by_ics_bucket = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    # Results by direction × ICS bucket (at recommended hold)
    by_dir_ics = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    # Also compute at fixed timeframes for comparison
    fixed_tf = {"1h": defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0}),
                "4h": defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0}),
                "24h": defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})}

    for sig in signals:
        ts = sig["timestamp"]
        price = sig["price"]
        direction = sig["direction"]
        ics = sig["ics"] or 0
        source = sig["source"]
        hold_hours = sig["hold_hours"]
        regime = sig["regime"]

        if not ts or not price:
            continue

        # ICS bucket
        if ics < 0.40: bucket = "<0.40"
        elif ics < 0.50: bucket = "0.40-0.50"
        elif ics < 0.55: bucket = "0.50-0.55"
        elif ics < 0.60: bucket = "0.55-0.60"
        elif ics < 0.65: bucket = "0.60-0.65"
        else: bucket = "0.65+"

        # At recommended hold window
        future = find_price_at_offset(ts, hold_hours)
        if future is not None:
            pct = (future - price) / price * 100
            win = pct > 0 if direction == "LONG" else pct < 0

            type_key = f"{source}_{hold_hours}h"
            by_type[type_key]["total"] += 1
            by_type[type_key]["pct_changes"].append(pct)
            if win: by_type[type_key]["wins"] += 1
            else: by_type[type_key]["losses"] += 1

            dir_key = f"{direction}_{hold_hours}h"
            by_dir_window[dir_key]["total"] += 1
            by_dir_window[dir_key]["pct_changes"].append(pct)
            if win: by_dir_window[dir_key]["wins"] += 1
            else: by_dir_window[dir_key]["losses"] += 1

            regime_key = f"{regime}_{direction}"
            by_regime_dir[regime_key]["total"] += 1
            by_regime_dir[regime_key]["pct_changes"].append(pct)
            if win: by_regime_dir[regime_key]["wins"] += 1
            else: by_regime_dir[regime_key]["losses"] += 1

            ics_key = f"{bucket}_{hold_hours}h"
            by_ics_bucket[ics_key]["total"] += 1
            by_ics_bucket[ics_key]["pct_changes"].append(pct)
            if win: by_ics_bucket[ics_key]["wins"] += 1
            else: by_ics_bucket[ics_key]["losses"] += 1

            dir_ics_key = f"{direction}_{bucket}"
            by_dir_ics[dir_ics_key]["total"] += 1
            by_dir_ics[dir_ics_key]["pct_changes"].append(pct)
            if win: by_dir_ics[dir_ics_key]["wins"] += 1
            else: by_dir_ics[dir_ics_key]["losses"] += 1

        # Also at fixed timeframes for comparison
        for tf, hours in [("1h", 1), ("4h", 4), ("24h", 24)]:
            tf_future = find_price_at_offset(ts, hours)
            if tf_future is not None:
                tf_pct = (tf_future - price) / price * 100
                tf_win = tf_pct > 0 if direction == "LONG" else tf_pct < 0
                fixed_tf[tf][source]["total"] += 1
                if tf_win: fixed_tf[tf][source]["wins"] += 1

    def safe_wr(d):
        if d["total"] >= MIN_SAMPLES:
            return {
                "total": d["total"],
                "wins": d["wins"],
                "losses": d["total"] - d["wins"],
                "win_rate": round(d["wins"]/d["total"]*100, 1),
                "avg_pct": round(statistics.mean(d["pct_changes"]), 4) if d["pct_changes"] else 0,
                "median_pct": round(statistics.median(d["pct_changes"]), 4) if d["pct_changes"] else 0,
            }
        else:
            return {"total": d["total"], "insufficient_data": True}

    return {
        "by_signal_type": {k: safe_wr(v) for k, v in sorted(by_type.items())},
        "by_direction_window": {k: safe_wr(v) for k, v in sorted(by_dir_window.items())},
        "by_regime_direction": {k: safe_wr(v) for k, v in sorted(by_regime_dir.items())},
        # New architecture filter stats
        "filter_stats": {
            "total_signals": len(signals),
            "ensemble_blocked": sum(1 for s in signals if not s.get("ensemble_passes", True)),
            "sweep_blocked": sum(1 for s in signals if s.get("sweep_blocked", False)),
            "m20_blocked": sum(1 for s in signals if s.get("m20_blocked", False)),
            "confirmed": sum(1 for s in signals if s.get("confirmation_status") == "CONFIRMED"),
            "pending": sum(1 for s in signals if s.get("confirmation_status") == "PENDING"),
            "expired": sum(1 for s in signals if s.get("confirmation_status") == "EXPIRED"),
        },
        "ensemble_stats": {
            "consensus_distribution": dict(Counter(s.get("ensemble_consensus", "NONE") for s in signals)),
            "avg_agree_count": round(sum(s.get("ensemble_agree_count", 0) for s in signals) / max(len(signals), 1), 2),
            "avg_conviction": round(sum(s.get("ensemble_conviction", 0) for s in signals) / max(len(signals), 1), 3),
        },
        "regime_distribution": dict(Counter(s.get("regime", "UNKNOWN") for s in signals)),
        "by_ics_bucket_window": {k: safe_wr(v) for k, v in sorted(by_ics_bucket.items())},
        "by_direction_ics": {k: safe_wr(v) for k, v in sorted(by_dir_ics.items())},
        "fixed_timeframe_by_source": {
            tf: {src: {"total": d["total"], "wins": d["wins"], "win_rate": round(d["wins"]/d["total"]*100, 1) if d["total"] >= MIN_SAMPLES else "insufficient"}
                 for src, d in sorted(srcs.items())}
            for tf, srcs in fixed_tf.items()
        },
    }

def compute_module_stats(scans):
    module_ids = ["m1", "m2", "m3", "m4", "m5", "m7", "m8", "m9", "m10", "m11", "m12", "m13", "m14", "m17", "m20", "m21", "m22", "m23", "m72"]
    module_stats = {}
    for mid in module_ids:
        scores = []
        statuses = Counter()
        for s in scans:
            mod = s.get(mid)
            if not mod or not isinstance(mod, dict): continue
            score = mod.get("score")
            status = mod.get("status", "UNKNOWN")
            statuses[status] += 1
            if score is not None: scores.append(score)
        if scores:
            module_stats[mid] = {
                "count": len(scores),
                "mean": round(statistics.mean(scores), 4),
                "median": round(statistics.median(scores), 4),
                "stdev": round(statistics.stdev(scores), 4) if len(scores) > 1 else 0,
                "min": round(min(scores), 4),
                "max": round(max(scores), 4),
                "status_counts": dict(statuses),
                "pass_rate": round(statuses.get("PASS", 0) / len(scores) * 100, 1) if scores else 0,
            }
    agree_matrix = defaultdict(lambda: {"agree": 0, "disagree": 0, "total": 0})
    dir_modules = ["m1", "m13", "m17", "m20"]
    for s in scans:
        dirs = {}
        for mid in dir_modules:
            mod = s.get(mid, {})
            if isinstance(mod, dict) and "direction" in mod:
                dirs[mid] = mod["direction"]
        for a in dir_modules:
            for b in dir_modules:
                if a >= b: continue
                if a in dirs and b in dirs:
                    key = f"{a}_vs_{b}"
                    agree_matrix[key]["total"] += 1
                    if dirs[a] == dirs[b]: agree_matrix[key]["agree"] += 1
                    else: agree_matrix[key]["disagree"] += 1
    correlation = {}
    for key, v in agree_matrix.items():
        if v["total"] > 0:
            correlation[key] = {"total": v["total"], "agree_rate": round(v["agree"]/v["total"]*100, 1)}
    return {"modules": module_stats, "correlation": correlation}

def compute_regime_stats(scans):
    """Performance segmented by market regime."""
    regime_counts = Counter()
    regime_dir = defaultdict(lambda: Counter())
    for s in scans:
        regime = classify_regime(s)
        regime_counts[regime] += 1
        regime_dir[regime][s.get("direction", "UNKNOWN")] += 1
    return {
        "regime_counts": dict(regime_counts),
        "regime_pcts": {k: round(v/len(scans)*100, 1) for k, v in regime_counts.items()},
        "direction_by_regime": {k: dict(v) for k, v in regime_dir.items()},
    }

def compute_squeeze_stats(scans):
    squeeze_types = Counter()
    squeeze_dirs = Counter()
    triggered = 0
    total = 0
    for s in scans:
        sq = s.get("squeeze", {})
        if not sq or not isinstance(sq, dict): continue
        total += 1
        st = sq.get("squeeze_type", "NONE")
        squeeze_types[st] += 1
        if sq.get("entry_triggered"): triggered += 1
        d = sq.get("direction")
        if d: squeeze_dirs[d] += 1
    return {"total_scans_with_squeeze": total, "squeeze_types": dict(squeeze_types), "squeeze_directions": dict(squeeze_dirs), "entry_triggered_count": triggered, "entry_triggered_rate": round(triggered/total*100, 1) if total else 0}

def compute_derivatives_stats(scans):
    positioning = Counter()
    whale_signals = Counter()
    ls_ratios = []
    funding_rates = []
    for s in scans:
        deriv = s.get("derivatives", {})
        if not deriv: continue
        positioning[deriv.get("positioning", "UNKNOWN")] += 1
        whale_signals[deriv.get("whale_signal", "UNKNOWN")] += 1
        ls = deriv.get("ls_ratio")
        if ls: ls_ratios.append(ls)
        fr = deriv.get("funding_rate")
        if fr is not None: funding_rates.append(fr)
    return {
        "positioning_counts": dict(positioning),
        "whale_signal_counts": dict(whale_signals),
        "ls_ratio": {"mean": round(statistics.mean(ls_ratios), 4) if ls_ratios else None, "median": round(statistics.median(ls_ratios), 4) if ls_ratios else None, "min": round(min(ls_ratios), 4) if ls_ratios else None, "max": round(max(ls_ratios), 4) if ls_ratios else None},
        "funding_rate": {"mean": round(statistics.mean(funding_rates), 8) if funding_rates else None, "min": round(min(funding_rates), 8) if funding_rates else None, "max": round(max(funding_rates), 8) if funding_rates else None},
    }

def compute_conflict_stats(scans):
    conflicts = 0
    total = 0
    for s in scans:
        c = s.get("conflict", {})
        if not c: continue
        total += 1
        if c.get("is_conflict"): conflicts += 1
    return {"total": total, "conflicts": conflicts, "conflict_rate": round(conflicts/total*100, 1) if total else 0}

def compute_strategy_stats(scans):
    strategy_counts = Counter()
    strategy_dirs = Counter()
    convictions = []
    for s in scans:
        ms = s.get("multi_strategy", {})
        if not ms: continue
        best = ms.get("best", {})
        if best:
            strategy_counts[best.get("strategy", "unknown")] += 1
            strategy_dirs[best.get("direction", "UNKNOWN")] += 1
            c = best.get("conviction")
            if c is not None: convictions.append(c)
        for sig in ms.get("all_signals", []):
            strategy_counts[sig.get("strategy", "unknown")] += 1
    return {"strategy_frequency": dict(strategy_counts.most_common(20)), "direction_distribution": dict(strategy_dirs), "conviction": {"mean": round(statistics.mean(convictions), 4) if convictions else None, "median": round(statistics.median(convictions), 4) if convictions else None}}

def compute_price_context(scans):
    trend_dirs = Counter()
    swing_biases = Counter()
    prices = []
    for s in scans:
        trend_dirs[s.get("trend_dir", "UNKNOWN")] += 1
        swing_biases[s.get("swing_bias", "UNKNOWN")] += 1
        p = s.get("price")
        if p: prices.append(p)
    price_range = max(prices) - min(prices) if prices else 0
    return {"trend_direction_counts": dict(trend_dirs), "swing_bias_counts": dict(swing_biases), "price_range": {"min": round(min(prices), 2) if prices else None, "max": round(max(prices), 2) if prices else None, "range_usd": round(price_range, 2), "range_pct": round(price_range / min(prices) * 100, 2) if prices else None}, "total_scans": len(scans)}

def compute_timeframe_stats(scans):
    by_hour = defaultdict(lambda: {"signals": 0, "total": 0, "ics_sum": 0})
    by_dow = defaultdict(lambda: {"signals": 0, "total": 0, "ics_sum": 0})
    for s in scans:
        ts = s.get("timestamp")
        if not ts: continue
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            hour = dt.hour
            dow = dt.strftime("%A")
            ics = s.get("ics", 0)
            by_hour[hour]["total"] += 1
            by_hour[hour]["ics_sum"] += ics
            if s.get("status") == "SIGNAL": by_hour[hour]["signals"] += 1
            by_dow[dow]["total"] += 1
            by_dow[dow]["ics_sum"] += ics
            if s.get("status") == "SIGNAL": by_dow[dow]["signals"] += 1
        except: pass
    hour_stats = {}
    for h in sorted(by_hour.keys()):
        v = by_hour[h]
        hour_stats[str(h)] = {"total": v["total"], "signals": v["signals"], "signal_rate": round(v["signals"]/v["total"]*100, 1) if v["total"] else 0, "avg_ics": round(v["ics_sum"]/v["total"], 4) if v["total"] else 0}
    dow_stats = {}
    for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        if d in by_dow:
            v = by_dow[d]
            dow_stats[d] = {"total": v["total"], "signals": v["signals"], "signal_rate": round(v["signals"]/v["total"]*100, 1) if v["total"] else 0, "avg_ics": round(v["ics_sum"]/v["total"], 4) if v["total"] else 0}
    return {"by_hour_utc": hour_stats, "by_day_of_week": dow_stats}

def main():
    print("Loading scans...")
    scans = load_scans()
    print(f"Loaded {len(scans)} scans")
    if not scans:
        print("No scans found!")
        return
    timestamps = [s.get("timestamp", "") for s in scans if s.get("timestamp")]
    date_range = {"first": min(timestamps), "last": max(timestamps)}
    print(f"Range: {date_range['first']} to {date_range['last']}")

    print("Computing direction stats...")
    direction_stats = compute_direction_stats(scans)
    signals = direction_stats.pop("signals")  # Extract signals for accuracy calc

    print(f"Computing signal accuracy ({len(signals)} signals, hold-window-aware)...")
    signal_accuracy = compute_signal_accuracy(scans, signals)

    print("Computing regime stats...")
    regime_stats = compute_regime_stats(scans)

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "scan_count": len(scans),
        "date_range": date_range,
        "min_samples_threshold": MIN_SAMPLES,
        "hold_windows": HOLD_WINDOWS,
        "ics_stats": compute_ics_stats(scans),
        "direction_stats": direction_stats,
        "signal_accuracy": signal_accuracy,
        "regime_stats": regime_stats,
        "module_stats": compute_module_stats(scans),
        "squeeze_stats": compute_squeeze_stats(scans),
        "derivatives_stats": compute_derivatives_stats(scans),
        "conflict_stats": compute_conflict_stats(scans),
        "strategy_stats": compute_strategy_stats(scans),
        "price_context": compute_price_context(scans),
        "timeframe_stats": compute_timeframe_stats(scans),
    }
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(summary, f, indent=2)
    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"Summary written to {OUTPUT} ({size_kb:.1f} KB)")
    print(f"{len(scans)} scans analyzed, {len(signals)} signals evaluated")

if __name__ == "__main__":
    main()
