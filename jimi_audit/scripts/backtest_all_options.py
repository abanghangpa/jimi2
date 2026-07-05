#!/usr/bin/env python3
"""
Comprehensive TP/SL Backtest — All Options
Tests conviction thresholds, ATR multipliers, strategy filters, and dynamic TP.
Uses real signal data + price series from JIMI scanner.
"""

import json
import glob
import os
import bisect
import math
import statistics
from datetime import datetime, timedelta
from collections import defaultdict

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
SIGNAL_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"

# ═══════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════

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

def load_scan_data():
    """Load scan files to get ATR and other indicator data for backtesting."""
    files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    scan_data = {}
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
                ts = d.get("timestamp")
                if ts:
                    scan_data[ts] = d
        except:
            pass
    return scan_data

# ═══════════════════════════════════════════════════════════════
# OUTCOME CHECKER
# ═══════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════
# RECALCULATE TP/SL WITH DIFFERENT MULTIPLIERS
# ═══════════════════════════════════════════════════════════════

def recalc_levels(entry, direction, atr, tp_mult, sl_mult, tp_min=15, sl_min=30):
    """Recalculate TP/SL with different ATR multipliers."""
    tp_dist = max(atr * tp_mult, tp_min)
    sl_dist = max(atr * sl_mult, sl_min)
    if direction == "LONG":
        tp = entry + tp_dist
        sl = entry - sl_dist
    else:
        tp = entry - tp_dist
        sl = entry + sl_dist
    return tp, sl

# ═══════════════════════════════════════════════════════════════
# OPTION A: CONVICTION THRESHOLD SWEEP
# ═══════════════════════════════════════════════════════════════

def test_conviction_thresholds(signals, ts_list, price_list):
    print("\n" + "="*70)
    print("OPTION A: Conviction Threshold Sweep")
    print("="*70)
    
    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    results = {}
    
    for thresh in thresholds:
        by_strat = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
        filtered = 0
        for sig in signals:
            if sig.get("conviction", 0) < thresh:
                filtered += 1
                continue
            outcome = check_outcome(ts_list, price_list, 
                                   sig["entry"], sig["sl"], sig["tp1"],
                                   sig["direction"], sig["timestamp"])
            if outcome is None:
                continue
            strat = sig["strategy"]
            by_strat[strat]["total"] += 1
            if outcome == "WIN": by_strat[strat]["wins"] += 1
            elif outcome == "LOSS": by_strat[strat]["losses"] += 1
        
        total_signals = len(signals) - filtered
        total_wins = sum(d["wins"] for d in by_strat.values())
        total_losses = sum(d["losses"] for d in by_strat.values())
        settled = total_wins + total_losses
        wr = round(total_wins / settled * 100, 1) if settled > 0 else 0
        
        results[thresh] = {
            "signals": total_signals,
            "filtered_pct": round(filtered / len(signals) * 100, 1),
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": wr,
            "by_strategy": {}
        }
        
        for strat, d in sorted(by_strat.items()):
            s = d["wins"] + d["losses"]
            if s >= 20:
                results[thresh]["by_strategy"][strat] = {
                    "n": s, "wr": round(d["wins"]/s*100, 1) if s > 0 else 0
                }
    
    # Print table
    print(f"\n{'Thresh':>8} {'Signals':>8} {'Filter%':>8} {'Wins':>6} {'Loss':>6} {'WR%':>7}")
    print("-" * 50)
    for thresh, d in sorted(results.items()):
        print(f"{thresh:>8.2f} {d['signals']:>8} {d['filtered_pct']:>7.1f}% {d['wins']:>6} {d['losses']:>6} {d['win_rate']:>6.1f}%")
    
    return results

# ═══════════════════════════════════════════════════════════════
# OPTION B: ATR MULTIPLIER SWEEP (per strategy)
# ═══════════════════════════════════════════════════════════════

def test_atr_multipliers(signals, ts_list, price_list, scan_data):
    print("\n" + "="*70)
    print("OPTION B: ATR Multiplier Sweep")
    print("="*70)
    
    # Get ATR values from scan data
    def get_atr(ts):
        scan = scan_data.get(ts, {})
        return scan.get("atr", scan.get("atr_1h", 0))
    
    tp_mults = [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
    sl_mults = [0.8, 1.0, 1.2, 1.5, 2.0]
    
    results = {}
    
    for tp_m in tp_mults:
        for sl_m in sl_mults:
            key = f"TP{tp_m}_SL{sl_m}"
            wins, losses, timeouts = 0, 0, 0
            by_strat = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
            
            for sig in signals:
                atr = get_atr(sig["timestamp"])
                if not atr or atr <= 0:
                    atr = sig["entry"] * 0.01  # fallback 1%
                
                new_tp, new_sl = recalc_levels(
                    sig["entry"], sig["direction"], atr, tp_m, sl_m)
                
                outcome = check_outcome(ts_list, price_list,
                                       sig["entry"], new_sl, new_tp,
                                       sig["direction"], sig["timestamp"])
                if outcome is None:
                    continue
                
                strat = sig["strategy"]
                by_strat[strat]["total"] += 1
                if outcome == "WIN":
                    wins += 1
                    by_strat[strat]["wins"] += 1
                elif outcome == "LOSS":
                    losses += 1
                    by_strat[strat]["losses"] += 1
                else:
                    timeouts += 1
            
            settled = wins + losses
            results[key] = {
                "tp_mult": tp_m, "sl_mult": sl_m,
                "wins": wins, "losses": losses, "timeouts": timeouts,
                "win_rate": round(wins/settled*100, 1) if settled > 0 else 0,
                "settled": settled,
                "rr_ratio": round(tp_m / sl_m, 2) if sl_m > 0 else 0,
                "by_strategy": {}
            }
            
            for strat, d in by_strat.items():
                s = d["wins"] + d["losses"]
                if s >= 20:
                    results[key]["by_strategy"][strat] = {
                        "n": s, "wr": round(d["wins"]/s*100, 1) if s > 0 else 0
                    }
    
    # Print summary table
    print(f"\n{'Config':>15} {'RR':>5} {'Wins':>6} {'Loss':>6} {'WR%':>7} {'Settled':>8}")
    print("-" * 55)
    for key, d in sorted(results.items(), key=lambda x: -x[1]["win_rate"]):
        print(f"{key:>15} {d['rr_ratio']:>5.2f} {d['wins']:>6} {d['losses']:>6} {d['win_rate']:>6.1f}% {d['settled']:>8}")
    
    # Top 5 configs per strategy
    print("\n--- Best Config Per Strategy (min 50 settled) ---")
    strat_configs = defaultdict(list)
    for key, d in results.items():
        for strat, sd in d["by_strategy"].items():
            if sd["n"] >= 50:
                strat_configs[strat].append((key, sd["wr"], sd["n"]))
    
    for strat, configs in sorted(strat_configs.items()):
        configs.sort(key=lambda x: -x[1])
        best = configs[0]
        print(f"  {strat:>25}: {best[0]} → {best[1]}% WR (n={best[2]})")
    
    return results

# ═══════════════════════════════════════════════════════════════
# OPTION C: STRATEGY-SPECIFIC FILTERS
# ═══════════════════════════════════════════════════════════════

def test_strategy_filters(signals, ts_list, price_list, scan_data):
    print("\n" + "="*70)
    print("OPTION C: Strategy-Specific Filters")
    print("="*70)
    
    results = {}
    
    # Filter 1: regime_switch — require vol_regime == TRENDING
    def filter_regime_trending(sig, scan):
        m9 = scan.get("m9", {})
        return m9.get("regime") == "TRENDING"
    
    # Filter 2: failed_breakout — require bars_since < 20
    def filter_fresh_breakout(sig, scan):
        # This info is in the signal details
        details = sig.get("details", {})
        if isinstance(details, str):
            try: details = json.loads(details)
            except: details = {}
        return details.get("bars_since", 99) < 20
    
    # Filter 3: All strategies — require volume > 1.2x average
    def filter_volume(sig, scan):
        vol_ratio = scan.get("vol_ratio", scan.get("volume_ratio", 1.0))
        return vol_ratio > 1.2
    
    # Filter 4: All strategies — require trend alignment (price > EMA200 for LONG)
    def filter_trend(sig, scan):
        price = sig.get("entry", 0)
        ema200 = scan.get("ema200", scan.get("ema_200", 0))
        if not ema200 or not price:
            return True  # no data = don't filter
        if sig["direction"] == "LONG":
            return price > ema200
        else:
            return price < ema200
    
    # Filter 5: regime_switch — raise conviction to 0.55
    def filter_regime_conviction(sig, scan):
        return sig.get("conviction", 0) >= 0.55
    
    filters = {
        "regime_trending": ("regime_switch", filter_regime_trending),
        "breakout_fresh": ("failed_breakout", filter_fresh_breakout),
        "volume_1.2x": ("all", filter_volume),
        "trend_aligned": ("all", filter_trend),
        "regime_high_conv": ("regime_switch", filter_regime_conviction),
    }
    
    for filter_name, (target_strat, filter_fn) in filters.items():
        wins, losses, filtered_out = 0, 0, 0
        by_strat = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
        
        for sig in signals:
            strat = sig["strategy"]
            scan = scan_data.get(sig["timestamp"], {})
            
            # Apply filter only to target strategy
            if target_strat == "all" or strat == target_strat:
                if not filter_fn(sig, scan):
                    filtered_out += 1
                    continue
            
            outcome = check_outcome(ts_list, price_list,
                                   sig["entry"], sig["sl"], sig["tp1"],
                                   sig["direction"], sig["timestamp"])
            if outcome is None:
                continue
            
            by_strat[strat]["total"] += 1
            if outcome == "WIN":
                wins += 1
                by_strat[strat]["wins"] += 1
            elif outcome == "LOSS":
                losses += 1
                by_strat[strat]["losses"] += 1
        
        settled = wins + losses
        results[filter_name] = {
            "target": target_strat,
            "filtered_out": filtered_out,
            "wins": wins, "losses": losses,
            "win_rate": round(wins/settled*100, 1) if settled > 0 else 0,
            "settled": settled,
            "by_strategy": {}
        }
        
        for strat, d in by_strat.items():
            s = d["wins"] + d["losses"]
            if s >= 20:
                results[filter_name]["by_strategy"][strat] = {
                    "n": s, "wr": round(d["wins"]/s*100, 1) if s > 0 else 0
                }
    
    # Baseline (no filter)
    base_wins, base_losses = 0, 0
    base_strat = defaultdict(lambda: {"wins": 0, "losses": 0})
    for sig in signals:
        outcome = check_outcome(ts_list, price_list,
                               sig["entry"], sig["sl"], sig["tp1"],
                               sig["direction"], sig["timestamp"])
        if outcome == "WIN":
            base_wins += 1
            base_strat[sig["strategy"]]["wins"] += 1
        elif outcome == "LOSS":
            base_losses += 1
            base_strat[sig["strategy"]]["losses"] += 1
    base_settled = base_wins + base_losses
    base_wr = round(base_wins/base_settled*100, 1) if base_settled > 0 else 0
    
    print(f"\n{'Filter':>25} {'Target':>18} {'Filtered':>9} {'WR%':>7} {'Δ WR':>7} {'Settled':>8}")
    print("-" * 80)
    print(f"{'BASELINE':>25} {'—':>18} {'—':>9} {base_wr:>6.1f}% {'—':>7} {base_settled:>8}")
    for name, d in sorted(results.items(), key=lambda x: -x[1]["win_rate"]):
        delta = round(d["win_rate"] - base_wr, 1)
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        print(f"{name:>25} {d['target']:>18} {d['filtered_out']:>9} {d['win_rate']:>6.1f}% {delta_str:>7} {d['settled']:>8}")
    
    # Show strategy-level impact
    print("\n--- Strategy-Level Impact ---")
    for name, d in results.items():
        for strat, sd in d["by_strategy"].items():
            base = base_strat.get(strat, {})
            base_s = base.get("wins", 0) + base.get("losses", 0)
            base_wr_s = round(base.get("wins", 0)/base_s*100, 1) if base_s > 0 else 0
            delta = round(sd["wr"] - base_wr_s, 1)
            if abs(delta) >= 3:  # only show meaningful changes
                delta_str = f"+{delta}" if delta > 0 else str(delta)
                print(f"  {name:>25} → {strat:>20}: {sd['wr']}% (Δ{delta_str}) n={sd['n']}")
    
    return results

# ═══════════════════════════════════════════════════════════════
# OPTION D: DYNAMIC TP BASED ON SOURCE
# ═══════════════════════════════════════════════════════════════

def test_dynamic_tp(signals, ts_list, price_list, scan_data):
    print("\n" + "="*70)
    print("OPTION D: Dynamic TP Based on Signal Quality")
    print("="*70)
    
    # We don't have tp_source in signals, but we can simulate:
    # - High conviction (0.7+) → trust original TP (likely better source)
    # - Medium conviction (0.5-0.7) → widen TP by 20%
    # - Low conviction (<0.5) → tighten TP by 20% or skip
    
    scenarios = {
        "baseline": {"tp_adj": 1.0, "min_conviction": 0},
        "skip_low_conv": {"tp_adj": 1.0, "min_conviction": 0.45},
        "widen_high_conv": {"tp_adj": 1.2, "min_conviction": 0.7, "only_high": True},
        "tighten_low": {"tp_adj": 0.8, "min_conviction": 0, "max_conviction": 0.45},
        "widen_all_20pct": {"tp_adj": 1.2, "min_conviction": 0},
        "tighten_all_20pct": {"tp_adj": 0.8, "min_conviction": 0},
        "adaptive": {"adaptive": True},  # different TP adj per conviction bucket
    }
    
    results = {}
    
    for scenario_name, params in scenarios.items():
        wins, losses, skipped = 0, 0, 0
        by_strat = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
        
        for sig in signals:
            conv = sig.get("conviction", 0)
            
            if conv < params.get("min_conviction", 0):
                skipped += 1
                continue
            
            if params.get("max_conviction") and conv > params["max_conviction"]:
                skipped += 1
                continue
            
            # Calculate TP adjustment
            if params.get("adaptive"):
                if conv >= 0.7:
                    tp_adj = 1.3  # widen TP for high conviction
                elif conv >= 0.5:
                    tp_adj = 1.0  # keep original
                else:
                    tp_adj = 0.7  # tighten TP for low conviction
            elif params.get("only_high"):
                if conv >= params["min_conviction"]:
                    tp_adj = params["tp_adj"]
                else:
                    tp_adj = 1.0
            else:
                tp_adj = params["tp_adj"]
            
            # Adjust TP
            entry = sig["entry"]
            original_tp = sig["tp1"]
            tp_dist = abs(original_tp - entry)
            new_tp = entry + tp_dist * tp_adj if sig["direction"] == "LONG" else entry - tp_dist * tp_adj
            
            outcome = check_outcome(ts_list, price_list,
                                   entry, sig["sl"], new_tp,
                                   sig["direction"], sig["timestamp"])
            if outcome is None:
                continue
            
            strat = sig["strategy"]
            by_strat[strat]["total"] += 1
            if outcome == "WIN":
                wins += 1
                by_strat[strat]["wins"] += 1
            elif outcome == "LOSS":
                losses += 1
                by_strat[strat]["losses"] += 1
        
        settled = wins + losses
        results[scenario_name] = {
            "skipped": skipped,
            "wins": wins, "losses": losses,
            "win_rate": round(wins/settled*100, 1) if settled > 0 else 0,
            "settled": settled,
            "by_strategy": {}
        }
        
        for strat, d in by_strat.items():
            s = d["wins"] + d["losses"]
            if s >= 20:
                results[scenario_name]["by_strategy"][strat] = {
                    "n": s, "wr": round(d["wins"]/s*100, 1) if s > 0 else 0
                }
    
    print(f"\n{'Scenario':>25} {'Skipped':>8} {'WR%':>7} {'Settled':>8}")
    print("-" * 55)
    for name, d in sorted(results.items(), key=lambda x: -x[1]["win_rate"]):
        print(f"{name:>25} {d['skipped']:>8} {d['win_rate']:>6.1f}% {d['settled']:>8}")
    
    return results

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("Loading data...")
    ts_list, price_list = load_price_series()
    signals = load_signals()
    scan_data = load_scan_data()
    print(f"Price points: {len(ts_list)}, Signals: {len(signals)}, Scans: {len(scan_data)}")
    
    # Run all tests
    results_a = test_conviction_thresholds(signals, ts_list, price_list)
    results_b = test_atr_multipliers(signals, ts_list, price_list, scan_data)
    results_c = test_strategy_filters(signals, ts_list, price_list, scan_data)
    results_d = test_dynamic_tp(signals, ts_list, price_list, scan_data)
    
    # Save all results
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_points": {"prices": len(ts_list), "signals": len(signals), "scans": len(scan_data)},
        "option_a_conviction": results_a,
        "option_b_atr_multipliers": results_b,
        "option_c_filters": results_c,
        "option_d_dynamic_tp": results_d,
    }
    
    with open("backtest_all_options_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print("\n✅ Results saved to backtest_all_options_results.json")

if __name__ == "__main__":
    main()
