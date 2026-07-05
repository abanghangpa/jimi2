#!/usr/bin/env python3
"""
JIMI Deep Analysis Pre-Processor v3
Signal direction accuracy with honest data quality reporting.
"""

import json
import glob
import os
import sys
import math
import bisect
import statistics
from datetime import datetime, timedelta
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outcome_calculator import load_price_series, load_fired_signals, check_outcome, wilson_interval, compute_outcomes_summary

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
SIGNAL_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"
OUTPUT = "/root/.openclaw/workspace/jimi_audit/data/deep_analysis_summary.json"
MIN_SAMPLES = 30
CONFIDENCE_MIN = 50

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

EXPECTED_FILTER_FIELDS = ["ensemble_passes", "sweep_blocked", "m20_blocked", "confirmation_status"]


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


def load_actual_signals():
    signals = []
    if not os.path.exists(SIGNAL_FILE):
        return signals
    with open(SIGNAL_FILE) as f:
        for line in f:
            try:
                signals.append(json.loads(line.strip()))
            except:
                pass
    return signals


def get_hold_window(source):
    return HOLD_WINDOWS.get(source, 4)


def classify_regime(scan):
    trend = scan.get("trend_dir", "UNKNOWN")
    if "STRONG_DOWN" in trend or "DOWN" in trend:
        return "trending_down"
    elif "STRONG_UP" in trend or "UP" in trend:
        return "trending_up"
    else:
        return "ranging"


def wilson_lower(wins, total, z=1.96):
    if total == 0:
        return 0
    p = wins / total
    denom = 1 + z**2 / total
    center = p + z**2 / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    return round((center - spread) / denom * 100, 1)


def wilson_upper(wins, total, z=1.96):
    if total == 0:
        return 0
    p = wins / total
    denom = 1 + z**2 / total
    center = p + z**2 / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    return round((center + spread) / denom * 100, 1)


def check_filter_data_quality(scans):
    field_presence = {field: 0 for field in EXPECTED_FILTER_FIELDS}
    total = len(scans)
    for s in scans:
        for field in EXPECTED_FILTER_FIELDS:
            if field in s:
                field_presence[field] += 1
    return {
        field: {
            "present_in": count,
            "missing_from": total - count,
            "coverage_pct": round(count / total * 100, 1) if total else 0,
            "status": "tracked" if count > total * 0.5 else "not_tracked"
        }
        for field, count in field_presence.items()
    }


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
    price_by_ts = {}
    for s in scans:
        ts = s.get("timestamp")
        price = s.get("price")
        if ts and price:
            price_by_ts[ts] = price
    sorted_ts = sorted(price_by_ts.keys())
    sorted_prices = [price_by_ts[t] for t in sorted_ts]

    def find_price_at_offset(base_ts, hours):
        try:
            base_dt = datetime.strptime(base_ts, "%Y-%m-%d %H:%M:%S")
            target = base_dt + timedelta(hours=hours)
            target_str = target.strftime("%Y-%m-%d %H:%M:%S")
            idx = bisect.bisect_left(sorted_ts, target_str)
            best = None
            best_diff = timedelta(hours=999)
            for candidate in [idx - 1, idx, idx + 1]:
                if 0 <= candidate < len(sorted_ts):
                    dt = datetime.strptime(sorted_ts[candidate], "%Y-%m-%d %H:%M:%S")
                    diff = abs(dt - target)
                    if diff < best_diff:
                        best_diff = diff
                        best = sorted_prices[candidate]
            if best_diff < timedelta(hours=2):
                return best
        except: pass
        return None

    by_type = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    by_dir_window = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    by_regime_dir = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    by_ics_bucket = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
    by_dir_ics = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0, "pct_changes": []})
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

        if ics < 0.40: bucket = "<0.40"
        elif ics < 0.50: bucket = "0.40-0.50"
        elif ics < 0.55: bucket = "0.50-0.55"
        elif ics < 0.60: bucket = "0.55-0.60"
        elif ics < 0.65: bucket = "0.60-0.65"
        else: bucket = "0.65+"

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

        for tf, hours in [("1h", 1), ("4h", 4), ("24h", 24)]:
            tf_future = find_price_at_offset(ts, hours)
            if tf_future is not None:
                tf_pct = (tf_future - price) / price * 100
                tf_win = tf_pct > 0 if direction == "LONG" else tf_pct < 0
                fixed_tf[tf][source]["total"] += 1
                if tf_win: fixed_tf[tf][source]["wins"] += 1

    def safe_wr(d):
        n = d["total"]
        if n >= MIN_SAMPLES:
            wr = round(d["wins"]/n*100, 1)
            result = {
                "n": n,
                "wins": d["wins"],
                "losses": n - d["wins"],
                "win_rate": wr,
                "avg_pct": round(statistics.mean(d["pct_changes"]), 4) if d["pct_changes"] else 0,
                "median_pct": round(statistics.median(d["pct_changes"]), 4) if d["pct_changes"] else 0,
            }
            if n >= CONFIDENCE_MIN:
                result["wr_95ci"] = [wilson_lower(d["wins"], n), wilson_upper(d["wins"], n)]
            return result
        else:
            return {"n": n, "insufficient_data": True, "note": f"Need {MIN_SAMPLES - n} more samples"}

    filter_quality = check_filter_data_quality(scans)

    return {
        "by_signal_type": {k: safe_wr(v) for k, v in sorted(by_type.items())},
        "by_direction_window": {k: safe_wr(v) for k, v in sorted(by_dir_window.items())},
        "by_regime_direction": {k: safe_wr(v) for k, v in sorted(by_regime_dir.items())},
        "filter_data_quality": filter_quality,
        "filter_stats": {
            "total_signals": len(signals),
            "ensemble_blocked": sum(1 for s in signals if not s.get("ensemble_passes", True)),
            "sweep_blocked": sum(1 for s in signals if s.get("sweep_blocked", False)),
            "m20_blocked": sum(1 for s in signals if s.get("m20_blocked", False)),
            "confirmed": sum(1 for s in signals if s.get("confirmation_status") == "CONFIRMED"),
            "pending": sum(1 for s in signals if s.get("confirmation_status") == "PENDING"),
            "expired": sum(1 for s in signals if s.get("confirmation_status") == "EXPIRED"),
            "_note": "If all values are 0, check filter_data_quality — fields may not be persisted in scan files"
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
            tf: {src: {"n": d["total"], "wins": d["wins"],
                        "win_rate": round(d["wins"]/d["total"]*100, 1) if d["total"] >= MIN_SAMPLES else None,
                        "insufficient": d["total"] < MIN_SAMPLES}
                 for src, d in sorted(srcs.items())}
            for tf, srcs in fixed_tf.items()
        },
    }


def compute_actual_signal_stats(actual_signals):
    fired = [s for s in actual_signals if s.get("fired")]
    by_strategy = defaultdict(lambda: {"fired": 0, "total": 0, "convictions": []})
    for s in actual_signals:
        strat = s.get("strategy", "unknown")
        by_strategy[strat]["total"] += 1
        if s.get("fired"):
            by_strategy[strat]["fired"] += 1
            if s.get("conviction"):
                by_strategy[strat]["convictions"].append(s["conviction"])
    result = {}
    for strat, d in sorted(by_strategy.items()):
        entry = {"total_evaluated": d["total"], "fired": d["fired"]}
        if d["fired"] > 0:
            entry["fire_rate"] = round(d["fired"] / d["total"] * 100, 1)
        if d["convictions"]:
            entry["avg_conviction"] = round(statistics.mean(d["convictions"]), 3)
            entry["median_conviction"] = round(statistics.median(d["convictions"]), 3)
        result[strat] = entry
    return {
        "total_signals": len(actual_signals),
        "total_fired": len(fired),
        "overall_fire_rate": round(len(fired) / len(actual_signals) * 100, 1) if actual_signals else 0,
        "by_strategy": result,
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
    for s in scans:
        deriv = s.get("derivatives", {})
        if not deriv or not isinstance(deriv, dict): continue
        pos = deriv.get("positioning")
        if pos: positioning[pos] += 1
        whale = deriv.get("whale_signal")
        if whale: whale_signals[whale] += 1
    return {"positioning_counts": dict(positioning), "whale_signal_counts": dict(whale_signals)}


def compute_conflict_stats(scans):
    conflicts = Counter()
    for s in scans:
        c = s.get("conflict")
        if c:
            key = json.dumps(c, sort_keys=True) if isinstance(c, dict) else str(c)
            conflicts[key] += 1
    return {"conflict_counts": dict(conflicts)}


def compute_strategy_stats(scans):
    strategies = defaultdict(lambda: {"total": 0, "wins": 0, "losses": 0, "pct_changes": []})
    for s in scans:
        strat = s.get("strategy")
        if not strat or not isinstance(strat, dict): continue
        name = strat.get("name", "unknown")
        strategies[name]["total"] += 1
        outcome = strat.get("outcome")
        if outcome == "WIN": strategies[name]["wins"] += 1
        elif outcome == "LOSS": strategies[name]["losses"] += 1
        pct = strat.get("pct_change")
        if pct is not None: strategies[name]["pct_changes"].append(pct)
    result = {}
    for name, d in sorted(strategies.items()):
        entry = {"total": d["total"]}
        if d["total"] >= MIN_SAMPLES:
            entry["win_rate"] = round(d["wins"]/d["total"]*100, 1)
            entry["avg_pct"] = round(statistics.mean(d["pct_changes"]), 4) if d["pct_changes"] else 0
            entry["median_pct"] = round(statistics.median(d["pct_changes"]), 4) if d["pct_changes"] else 0
        else:
            entry["insufficient_data"] = True
        result[name] = entry
    return result


def compute_price_context(scans):
    prices = [s.get("price") for s in scans if s.get("price")]
    trend_dirs = Counter()
    swing_biases = Counter()
    for s in scans:
        td = s.get("trend_dir")
        if td: trend_dirs[td] += 1
        sb = s.get("swing_bias")
        if sb: swing_biases[sb] += 1
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

    print("Loading actual signals from strategy_signals.jsonl...")
    actual_signals = load_actual_signals()
    print(f"Loaded {len(actual_signals)} actual signal records")

    print("Computing direction stats...")
    direction_stats = compute_direction_stats(scans)
    signals = direction_stats.pop("signals")

    print(f"Computing signal accuracy ({len(signals)} signals)...")
    signal_accuracy = compute_signal_accuracy(scans, signals)

    print("Computing actual signal cross-reference...")
    actual_signal_stats = compute_actual_signal_stats(actual_signals)

    print("Computing regime stats...")
    regime_stats = compute_regime_stats(scans)

    print("Computing trade outcomes (signal=trade)...")
    try:
        ts_list, price_list = load_price_series()
        fired = load_fired_signals()
        outcome_results = compute_outcomes_summary(ts_list, price_list, fired)
        print(f"  {outcome_results['total_trades_evaluated']} trades evaluated")
    except Exception as e:
        outcome_results = {"error": str(e)}
        print(f"  Outcome calculation failed: {e}")

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "scan_count": len(scans),
        "date_range": date_range,
        "min_samples_threshold": MIN_SAMPLES,
        "confidence_min": CONFIDENCE_MIN,
        "hold_windows": HOLD_WINDOWS,
        "data_quality_notes": [
            f"MIN_SAMPLES = {MIN_SAMPLES} (metrics below this threshold are marked insufficient)",
            f"CONFIDENCE_MIN = {CONFIDENCE_MIN} (95% Wilson CI only shown for n >= this)",
            "filter_stats: check filter_data_quality first — 0 values may mean 'not tracked', not 'not blocking'",
            "signal_accuracy: measures direction prediction from scan signals, not actual trade P&L",
            "actual_signal_stats: cross-reference with strategy_signals.jsonl for actual fired signals",
        ],
        "ics_stats": compute_ics_stats(scans),
        "direction_stats": direction_stats,
        "signal_accuracy": signal_accuracy,
        "actual_signal_stats": actual_signal_stats,
        "trade_outcomes": outcome_results,
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
    print(f"Filter data quality: {json.dumps(check_filter_data_quality(scans), indent=2)}")

if __name__ == "__main__":
    main()
