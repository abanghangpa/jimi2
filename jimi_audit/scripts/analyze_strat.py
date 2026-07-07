#!/usr/bin/env python3
"""
Strategy Failure Analysis - Uses existing scan files + signals log.
No heavy computation. Run per strategy.
Usage: python3 analyze_strat.py <strategy_name>
"""
import sys, os, json, glob
import numpy as np
from datetime import datetime
from collections import defaultdict

STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "failed_breakout"
BASE = "/root/.openclaw/workspace/jimi_audit"
SCAN_DIR = os.path.join(BASE, "data", "scans")
SIGNALS_FILE = os.path.join(BASE, "data", "strategy_signals.jsonl")
OUTPUT = os.path.join(BASE, "data", f"analysis_{STRATEGY}.json")

SCONFIGS = {
    "failed_breakout": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.7, "direction": "SHORT"},
    "squeeze_breakout": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "cascade": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "positioning_fade": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": "LONG"},
    "kill_zone": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "liquidity_grab": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "taker_flow": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "regime_switch": {"tp_pct": 1.0, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": "SHORT"},
    "power_of_3": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "structural_break": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8, "min_conv": 0.5, "direction": "SHORT"},
    "cross_asset": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 4, "min_conv": 0.5, "direction": None},
    "macro_surprise": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "funding_arb": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12, "min_conv": 0.5, "direction": None},
    "whale_watch": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 8, "min_conv": 0.5, "direction": "LONG"},
    "vol_rotation": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "mtf_confluence": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "scalp_v2": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "momentum_v2": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "orderbook_imbalance": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5, "direction": "LONG"},
    "liquidation_cascade": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "trade_flow": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12, "min_conv": 0.5, "direction": "LONG"},
    "judas_sweep": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
    "bb_mom6": {"tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8, "min_conv": 0.5, "direction": None},
}

scfg = SCONFIGS.get(STRATEGY)
if not scfg:
    print(f"Unknown strategy: {STRATEGY}")
    sys.exit(1)

print(f"=== {STRATEGY} ===")
print(f"Config: {json.dumps(scfg)}")

# --- Phase 1: Scan files ---
print("\n[1/3] Reading scan files...")
scan_files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
signals_from_scans = []

for sf in scan_files:
    try:
        with open(sf) as f:
            data = json.load(f)
    except:
        continue
    
    ts = data.get("timestamp", "")
    price = data.get("price", 0)
    status = data.get("status", "")
    swing = data.get("swing_bias", "")
    trend = data.get("trend_dir", "")
    
    multi = data.get("multi_strategy") or {}
    all_sigs = multi.get("all_signals", [])
    
    for sig in all_sigs:
        if not isinstance(sig, dict): continue
        if sig.get("strategy") != STRATEGY: continue
        
        direction = sig.get("direction")
        conviction = sig.get("conviction", 0) or 0
        entry = sig.get("entry", price)
        sl = sig.get("sl", 0)
        tp1 = sig.get("tp1", 0)
        reason = sig.get("reason", "")
        
        fired = bool(direction and conviction >= (scfg["min_conv"] if scfg else 0.5))
        if scfg and scfg["direction"] and direction and direction != scfg["direction"]:
            fired = False
        
        signals_from_scans.append({
            "ts": ts, "price": price, "direction": direction,
            "conviction": conviction, "entry": entry, "sl": sl, "tp1": tp1,
            "reason": reason, "fired": fired,
            "swing_bias": swing, "trend_dir": trend, "scan_status": status,
        })

total_scans = len(scan_files)
fired_count = sum(1 for s in signals_from_scans if s["fired"])
not_fired = sum(1 for s in signals_from_scans if not s["fired"])
direction_blocked = sum(1 for s in signals_from_scans if s["direction"] and scfg and scfg["direction"] and s["direction"] != scfg["direction"])
low_conviction = sum(1 for s in signals_from_scans if s["direction"] and s["conviction"] < (scfg["min_conv"] if scfg else 0.5))
no_direction = sum(1 for s in signals_from_scans if not s["direction"])

print(f"  Scans: {total_scans}")
print(f"  Strategy appeared in: {len(signals_from_scans)}")
print(f"  Fired (after filters): {fired_count}")
print(f"  Blocked: direction_mismatch={direction_blocked} low_conviction={low_conviction} no_direction={no_direction}")

# --- Phase 2: Strategy signals log ---
print("\n[2/3] Reading signals log...")
log_fired = 0
log_not_fired = 0
log_signals = []

try:
    with open(SIGNALS_FILE) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
            except:
                continue
            if d.get("strategy") != STRATEGY: continue
            if d.get("fired"):
                log_fired += 1
                log_signals.append(d)
            else:
                log_not_fired += 1
except Exception as e:
    print(f"  Error reading signals log: {e}")

print(f"  Total entries: {log_fired + log_not_fired}")
print(f"  Fired: {log_fired} | Not fired: {log_not_fired}")

# --- Phase 3: Outcome analysis from deep_analysis ---
print("\n[3/3] Loading deep analysis summary...")
deep = {}
try:
    with open(os.path.join(BASE, "data", "deep_analysis_summary.json")) as f:
        deep = json.load(f)
except:
    pass

trade_outcomes = deep.get("trade_outcomes", {}).get("by_strategy", {}).get(STRATEGY, {})
signal_accuracy = {}
for k, v in deep.get("signal_accuracy", {}).get("by_signal_type", {}).items():
    if STRATEGY in k:
        signal_accuracy[k] = v

print(f"  Trade outcomes: {json.dumps(trade_outcomes, indent=4)[:500]}")
print(f"  Signal accuracy keys: {list(signal_accuracy.keys())}")

# --- Build failure analysis ---
# Classify fired signals by market context
fired_sigs = [s for s in signals_from_scans if s["fired"]]

# Direction distribution
dir_counts = defaultdict(int)
for s in fired_sigs:
    dir_counts[s["direction"]] += 1

# Conviction distribution
conv_buckets = {"0.5-0.6": 0, "0.6-0.7": 0, "0.7-0.8": 0, "0.8-0.9": 0, "0.9-1.0": 0}
for s in fired_sigs:
    c = s["conviction"]
    if c < 0.6: conv_buckets["0.5-0.6"] += 1
    elif c < 0.7: conv_buckets["0.6-0.7"] += 1
    elif c < 0.8: conv_buckets["0.7-0.8"] += 1
    elif c < 0.9: conv_buckets["0.8-0.9"] += 1
    else: conv_buckets["0.9-1.0"] += 1

# Swing bias at signal time
bias_counts = defaultdict(int)
for s in fired_sigs:
    bias_counts[s["swing_bias"]] += 1

# Trend at signal time
trend_counts = defaultdict(int)
for s in fired_sigs:
    trend_counts[s["trend_dir"]] += 1

# Monthly distribution
monthly = defaultdict(int)
for s in fired_sigs:
    monthly[s["ts"][:7]] += 1

# Sample losing signals (from scan files that have outcome via trade_outcomes)
# We can reconstruct some from signals log
log_losses = [s for s in log_signals if s.get("outcome") == "LOSS" or (s.get("direction") and not s.get("outcome"))]
log_wins = [s for s in log_signals if s.get("outcome") == "WIN"]

output = {
    "strategy": STRATEGY,
    "config": scfg,
    "scan_period": f"{scan_files[0].split('_')[-1].replace('.json','')[:8] if scan_files else '?'} to {scan_files[-1].split('_')[-1].replace('.json','')[:8] if scan_files else '?'}",
    "total_scans": total_scans,
    "strategy_appeared": len(signals_from_scans),
    "signals_fired": fired_count,
    "signals_blocked": {
        "direction_mismatch": direction_blocked,
        "low_conviction": low_conviction,
        "no_direction": no_direction,
    },
    "direction_distribution": dict(dir_counts),
    "conviction_distribution": conv_buckets,
    "swing_bias_at_signal": dict(bias_counts),
    "trend_at_signal": dict(trend_counts),
    "monthly_signals": dict(sorted(monthly.items())),
    "deep_analysis_outcomes": trade_outcomes,
    "deep_analysis_accuracy": signal_accuracy,
    "signals_log_fired": log_fired,
    "signals_log_not_fired": log_not_fired,
    "sample_fired_signals": fired_sigs[-20:],
    "sample_log_signals": log_signals[-20:],
}

with open(OUTPUT, "w") as f:
    json.dump(output, f, indent=2, default=str)

# Print summary
print(f"\n{'=' * 70}")
print(f"  {STRATEGY.upper()} — FAILURE ANALYSIS")
print(f"{'=' * 70}")
print(f"  Scan period: {output['scan_period']}")
print(f"  Total scans: {total_scans}")
print(f"  Strategy appeared in: {len(signals_from_scans)} scans")
print(f"  Signals fired: {fired_count}")
print(f"  Blocked: dir_mismatch={direction_blocked} low_conv={low_conviction} no_dir={no_direction}")
print(f"\n  Direction: {dict(dir_counts)}")
print(f"  Conviction: {conv_buckets}")
print(f"  Swing bias at signal: {dict(bias_counts)}")
print(f"  Trend at signal: {dict(trend_counts)}")
print(f"\n  Monthly signals: {dict(sorted(monthly.items()))}")

if trade_outcomes:
    print(f"\n  Deep Analysis Outcomes (Jun 7 - Jul 4):")
    print(f"    Trades: {trade_outcomes.get('n', 0)}")
    print(f"    Wins: {trade_outcomes.get('wins', 0)} | Losses: {trade_outcomes.get('losses', 0)} | Timeouts: {trade_outcomes.get('timeouts', 0)}")
    print(f"    Win Rate: {trade_outcomes.get('win_rate', '?')}%")
    print(f"    Avg RR: {trade_outcomes.get('avg_rr', '?')}")
    print(f"    Avg Conviction: {trade_outcomes.get('avg_conviction', '?')}")

if signal_accuracy:
    print(f"\n  Signal Accuracy:")
    for k, v in signal_accuracy.items():
        print(f"    {k}: n={v.get('n',0)} WR={v.get('win_rate','?')}% avg={v.get('avg_pct','?')}%")

print(f"\n  Last 10 fired signals:")
for s in fired_sigs[-10:]:
    print(f"    {s['ts']} | {s['direction']} conv={s['conviction']:.2f} entry={s['entry']} | bias={s['swing_bias']} trend={s['trend_dir']}")

print(f"\n✅ Saved to {OUTPUT}")
