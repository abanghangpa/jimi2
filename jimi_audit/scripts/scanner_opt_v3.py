#!/usr/bin/env python3
"""
Per-Strategy TP/SL Optimizer V3 — FIXED simulation
Uses actual TP/SL percentages for PnL (not rr1 from signal).
Timeout exits use actual price movement.
"""
import json, os, glob, sys, time
from datetime import datetime, timedelta
from collections import defaultdict

t0 = time.time()

ETH_CSV = "/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv"
SIGNALS_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"
START_DATE = "2026-06-22"
END_DATE = "2026-07-05"

# =====================================================================
# LOAD PRICE DATA + ATR
# =====================================================================
print("Loading price data + ATR...")
prices = []
with open(ETH_CSV) as f:
    header = f.readline()
    for line in f:
        parts = line.strip().split(",")
        ts_str = parts[0]
        if ts_str >= START_DATE and ts_str <= END_DATE:
            prices.append({
                "ts": ts_str,
                "o": float(parts[1]), "h": float(parts[2]),
                "l": float(parts[3]), "c": float(parts[4]),
            })

# ATR(14)
for i in range(len(prices)):
    if i < 14:
        prices[i]["atr"] = abs(prices[i]["h"] - prices[i]["l"])
    else:
        trs = []
        for j in range(i-13, i+1):
            h, l = prices[j]["h"], prices[j]["l"]
            pc = prices[j-1]["c"] if j > 0 else prices[j]["o"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        prices[i]["atr"] = sum(trs) / len(trs)

price_by_ts = {p["ts"]: p for p in prices}
price_timeline = [p["ts"] for p in prices]
print(f"  {len(prices)} bars")

# =====================================================================
# LOAD SIGNALS
# =====================================================================
print("Loading signals...")
signals = []
count = 0
with open(SIGNALS_FILE) as f:
    for line in f:
        count += 1
        if count > 3000000: break
        try:
            d = json.loads(line)
            ts = d.get("timestamp", "")
            if ts < START_DATE or ts >= END_DATE: continue
            if d.get("fired") and d.get("direction") and d.get("conviction", 0) > 0:
                signals.append(d)
        except: continue

seen = set(); unique = []
for s in signals:
    key = (s["strategy"], s["timestamp"])
    if key not in seen:
        seen.add(key); unique.append(s)
signals = sorted(unique, key=lambda x: x["timestamp"])
print(f"  {len(signals)} unique signals")

# =====================================================================
# HELPERS
# =====================================================================
def find_bar_idx(ts_str):
    prefix = ts_str[:16]
    for i, t in enumerate(price_timeline):
        if t[:16] == prefix: return i
    return None

def calc_levels(sig, tp_method, sl_method, tp_val, sl_val):
    """Calculate TP and SL prices based on method."""
    entry = sig.get("entry", sig.get("price", 0))
    if not entry: return 0, 0

    idx = find_bar_idx(sig["timestamp"])
    if idx is None: return 0, 0
    atr = prices[idx].get("atr", 0) if idx < len(prices) else 0
    direction = sig["direction"]

    # TP
    if tp_method == "original":
        tp = sig.get("tp1", 0)
    elif tp_method == "fixed_pct":
        tp = entry * (1 + tp_val/100) if direction == "LONG" else entry * (1 - tp_val/100)
    elif tp_method == "atr_mult":
        tp = entry + atr * tp_val if direction == "LONG" else entry - atr * tp_val
    else:
        tp = sig.get("tp1", 0)

    # SL
    if sl_method == "original":
        sl = sig.get("sl", 0)
    elif sl_method == "fixed_pct":
        sl = entry * (1 - sl_val/100) if direction == "LONG" else entry * (1 + sl_val/100)
    elif sl_method == "atr_mult":
        sl = entry - atr * sl_val if direction == "LONG" else entry + atr * sl_val
    else:
        sl = sig.get("sl", 0)

    return tp, sl

def check_outcome(sig, hold_bars, tp_method, sl_method, tp_val, sl_val):
    """Returns (outcome, pnl_pct) where pnl_pct is actual % gain/loss on entry."""
    idx = find_bar_idx(sig["timestamp"])
    if idx is None: return None, 0

    entry = sig.get("entry", sig.get("price", 0))
    tp, sl = calc_levels(sig, tp_method, sl_method, tp_val, sl_val)
    if not entry or not tp or not sl or tp == sl: return None, 0

    direction = sig["direction"]
    end_idx = min(idx + hold_bars, len(price_timeline))

    for j in range(idx + 1, end_idx):
        bar = price_by_ts[price_timeline[j]]
        h, l = bar["h"], bar["l"]

        if direction == "LONG":
            if h >= tp:
                pnl_pct = (tp - entry) / entry
                return "WIN", pnl_pct
            if l <= sl:
                pnl_pct = (sl - entry) / entry  # negative
                return "LOSS", pnl_pct
        else:
            if l <= tp:
                pnl_pct = (entry - tp) / entry
                return "WIN", pnl_pct
            if h >= sl:
                pnl_pct = (entry - sl) / entry  # negative
                return "LOSS", pnl_pct

    # Timeout: exit at close
    if end_idx > idx:
        exit_price = price_by_ts[price_timeline[end_idx - 1]]["c"]
        if direction == "LONG":
            pnl_pct = (exit_price - entry) / entry
        else:
            pnl_pct = (entry - exit_price) / entry
        return "TIMEOUT", pnl_pct

    return None, 0

def simulate(filtered, hold_bars, risk_pct, leverage, tp_method, sl_method, tp_val, sl_val):
    """Simulate with actual PnL percentages."""
    cap = 200
    peak = cap
    max_dd = 0
    wins = 0; losses = 0; timeouts = 0; total = 0

    for sig in filtered:
        outcome, pnl_pct = check_outcome(sig, hold_bars, tp_method, sl_method, tp_val, sl_val)
        if not outcome: continue
        total += 1

        # PnL = capital * risk * leverage * pnl_pct / sl_pct
        # But simpler: just use pnl_pct * leverage * capital * risk_factor
        # where risk_factor scales so that a full SL hit = -risk_pct * capital
        entry = sig.get("entry", sig.get("price", 0))
        _, sl = calc_levels(sig, tp_method, sl_method, tp_val, sl_val)
        sl_dist_pct = abs(entry - sl) / entry if entry and sl else 0.01

        if sl_dist_pct > 0:
            # Normalize: if pnl_pct = sl_dist_pct, we lose risk_pct * cap
            pnl = cap * risk_pct * (pnl_pct / sl_dist_pct)
        else:
            pnl = 0

        cap += pnl
        if outcome == "WIN": wins += 1
        elif outcome == "LOSS": losses += 1
        else: timeouts += 1

        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
        if cap <= 0: cap = 0; break

    return cap, max_dd, total, wins, losses, timeouts

def calc_pf(wins, losses):
    return wins / losses if losses > 0 else (999 if wins > 0 else 0)

# =====================================================================
# PER-STRATEGY OPTIMIZATION
# =====================================================================
strats = sorted(set(s["strategy"] for s in signals))

print(f"\n{'='*120}")
print(f"PER-STRATEGY TP/SL OPTIMIZATION (V3 — actual PnL)")
print(f"Period: {START_DATE} to {END_DATE}")
print(f"{'='*120}")

final_summary = []

for strat_name in strats:
    strat_signals = [s for s in signals if s["strategy"] == strat_name]
    if len(strat_signals) < 20:
        print(f"\n--- {strat_name}: {len(strat_signals)} signals (too few) ---")
        continue

    print(f"\n{'='*120}")
    print(f"STRATEGY: {strat_name} ({len(strat_signals)} signals)")
    print(f"{'='*120}")

    # Test configs
    configs = [
        ("original/original", "original", "original", 0, 0),
    ]
    # Fixed pct
    for tp in [0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
        for sl in [0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]:
            configs.append((f"fixed TP={tp}% SL={sl}%", "fixed_pct", "fixed_pct", tp, sl))
    # ATR mult
    for tp in [0.5, 1.0, 1.5, 2.0]:
        for sl in [0.5, 1.0, 1.5, 2.0, 3.0]:
            configs.append((f"ATR TP={tp}x SL={sl}x", "atr_mult", "atr_mult", tp, sl))

    for direction_filter in [None, "LONG", "SHORT"]:
        dir_label = f" [{direction_filter}]" if direction_filter else ""

        if direction_filter:
            filtered = [s for s in strat_signals if s["direction"] == direction_filter]
        else:
            filtered = strat_signals

        if len(filtered) < 10:
            continue

        top_results = []

        for label, tp_m, sl_m, tp_v, sl_v in configs:
            for hold_h in [2, 4, 8, 12, 24]:
                hold_bars = hold_h * 4
                cap, dd, total, wins, losses, timeouts = simulate(
                    filtered, hold_bars, 0.02, 10, tp_m, sl_m, tp_v, sl_v)
                if total < 15: continue
                pf = calc_pf(wins, losses)
                wr = wins / total * 100

                top_results.append({
                    "label": label + f" {hold_h}h{dir_label}",
                    "pf": pf, "wr": wr, "total": total, "wins": wins,
                    "losses": losses, "timeouts": timeouts, "dd": dd, "cap": cap,
                    "hold": hold_h, "dir": direction_filter
                })

        # Sort by PF, then by WR as tiebreaker
        top_results.sort(key=lambda x: (-x["pf"], -x["wr"]))

        print(f"\n  Top 10{dir_label} (by PF, then WR):")
        print(f"  {'Config':<55} {'H':>3} {'Tr':>5} {'W':>5} {'L':>5} {'TO':>4} {'WR%':>6} {'PF':>7} {'DD%':>6} {'Cap$':>10}")
        print(f"  {'-'*115}")
        for r in top_results[:10]:
            marker = " <<<" if r["pf"] >= 2.0 and r["total"] >= 30 else ""
            print(f"  {r['label']:<55} {r['hold']:>2}h {r['total']:>5} {r['wins']:>5} {r['losses']:>5} {r['timeouts']:>4} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['dd']:>5.1f}% ${r['cap']:>9,.0f}{marker}")

        # Save best
        best = top_results[0] if top_results else None
        if best:
            final_summary.append({
                "strategy": strat_name, "direction": direction_filter,
                "best_pf": best["pf"], "wr": best["wr"], "total": best["total"],
                "config": best["label"], "dd": best["dd"]
            })

# =====================================================================
# FINAL SUMMARY
# =====================================================================
print(f"\n\n{'='*120}")
print(f"FINAL SUMMARY — BEST PER STRATEGY (min 30 trades)")
print(f"{'='*120}")
print(f"\n{'Strategy':<25} {'Dir':>6} {'PF':>7} {'WR%':>7} {'Trades':>7} {'DD%':>7} {'Config':<55}")
print(f"{'-'*120}")

for r in sorted(final_summary, key=lambda x: -x["best_pf"]):
    if r["total"] < 30: continue
    dir_label = r["direction"] or "ALL"
    marker = " PF>=2.0" if r["best_pf"] >= 2.0 else ""
    print(f"{r['strategy']:<25} {dir_label:>6} {r['best_pf']:>6.2f} {r['wr']:>6.1f}% {r['total']:>7} {r['dd']:>6.1f}% {r['config']:<55}{marker}")

# =====================================================================
# COMBINED OPTIMAL CONFIG
# =====================================================================
print(f"\n{'='*120}")
print(f"COMBINED OPTIMAL (best per strategy, all signals)")
print(f"{'='*120}")

# Pick best config per strategy and simulate combined
combined = []
for strat_name in strats:
    strat_signals = [s for s in signals if s["strategy"] == strat_name]
    if len(strat_signals) < 20: continue

    best_entry = None
    for r in final_summary:
        if r["strategy"] == strat_name and r["direction"] is None and r["total"] >= 30:
            if best_entry is None or r["best_pf"] > best_entry["best_pf"]:
                best_entry = r
    if best_entry:
        combined.append((strat_name, best_entry))

if combined:
    print(f"\n  Using best config per strategy:")
    for name, entry in combined:
        print(f"    {name}: {entry['config']} (PF={entry['best_pf']:.2f}, WR={entry['wr']:.1f}%)")

elapsed = time.time() - t0
print(f"\nCompleted in {elapsed:.1f}s")
