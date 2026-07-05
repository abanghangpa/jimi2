#!/usr/bin/env python3
"""
Per-Strategy TP/SL Optimizer
For each scanner strategy, tests multiple TP/SL methods to find PF 2.0.
Methods: liquidity (original), fixed_pct, atr_mult, trailing, rr_ratio
Also: conviction filters, direction filters, hold time sweeps.
"""
import json, os, glob, sys, time
from datetime import datetime, timedelta
from collections import defaultdict
import math

t0 = time.time()

ETH_CSV = "/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv"
SIGNALS_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"
START_DATE = "2026-06-22"
END_DATE = "2026-07-05"

# =====================================================================
# LOAD PRICE DATA + ATR
# =====================================================================
print("Loading price data + computing ATR...")
prices = []  # [{ts, o, h, l, c, v, atr}]
raw_prices = []
with open(ETH_CSV) as f:
    header = f.readline()
    for line in f:
        parts = line.strip().split(",")
        ts_str = parts[0]
        if ts_str >= START_DATE and ts_str <= END_DATE:
            raw_prices.append({
                "ts": ts_str,
                "o": float(parts[1]), "h": float(parts[2]),
                "l": float(parts[3]), "c": float(parts[4]),
                "v": float(parts[5]) if len(parts) > 5 else 0
            })

# Compute ATR(14)
for i in range(len(raw_prices)):
    if i < 14:
        raw_prices[i]["atr"] = abs(raw_prices[i]["h"] - raw_prices[i]["l"])
    else:
        trs = []
        for j in range(i-13, i+1):
            h, l = raw_prices[j]["h"], raw_prices[j]["l"]
            pc = raw_prices[j-1]["c"] if j > 0 else raw_prices[j]["o"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        raw_prices[i]["atr"] = sum(trs) / len(trs)

prices = raw_prices
price_by_ts = {p["ts"]: p for p in prices}
price_timeline = [p["ts"] for p in prices]
print(f"  {len(prices)} bars, ATR computed")

# =====================================================================
# LOAD SIGNALS
# =====================================================================
print("Loading signals...")
signals = []
count = 0
with open(SIGNALS_FILE) as f:
    for line in f:
        count += 1
        if count > 3000000:
            break
        try:
            d = json.loads(line)
            ts = d.get("timestamp", "")
            if ts < START_DATE or ts >= END_DATE:
                continue
            if d.get("fired") and d.get("direction") and d.get("conviction", 0) > 0:
                signals.append(d)
        except:
            continue

# Dedup
seen = set()
unique = []
for s in signals:
    key = (s["strategy"], s["timestamp"])
    if key not in seen:
        seen.add(key)
        unique.append(s)
signals = sorted(unique, key=lambda x: x["timestamp"])
print(f"  {len(signals)} unique signals")

# =====================================================================
# FIND BAR INDEX
# =====================================================================
def find_bar_idx(ts_str):
    prefix = ts_str[:16]
    for i, t in enumerate(price_timeline):
        if t[:16] == prefix:
            return i
    return None

# =====================================================================
# CHECK OUTCOME with custom TP/SL
# =====================================================================
def check_outcome_custom(sig, hold_bars, tp_method, sl_method, tp_val, sl_val, trail_pct=0):
    """Check outcome with custom TP/SL.
    tp_method/sl_method: 'original', 'fixed_pct', 'atr_mult', 'rr_ratio'
    """
    idx = find_bar_idx(sig["timestamp"])
    if idx is None:
        return None, 0

    direction = sig["direction"]
    entry = sig.get("entry", sig.get("price", 0))
    if not entry:
        return None, 0

    bar_entry = price_by_ts.get(price_timeline[idx]) if idx < len(price_timeline) else None
    if not bar_entry:
        return None, 0

    atr = bar_entry.get("atr", 0)

    # Calculate TP/SL based on method
    if tp_method == "original":
        tp = sig.get("tp1", 0)
    elif tp_method == "fixed_pct":
        if direction == "LONG":
            tp = entry * (1 + tp_val / 100)
        else:
            tp = entry * (1 - tp_val / 100)
    elif tp_method == "atr_mult":
        if direction == "LONG":
            tp = entry + atr * tp_val
        else:
            tp = entry - atr * tp_val
    elif tp_method == "rr_ratio":
        # TP = entry + sl_distance * rr_ratio
        sl_dist = abs(entry - (sig.get("sl", entry * 0.99)))
        if direction == "LONG":
            tp = entry + sl_dist * tp_val
        else:
            tp = entry - sl_dist * tp_val
    else:
        tp = sig.get("tp1", 0)

    if sl_method == "original":
        sl = sig.get("sl", 0)
    elif sl_method == "fixed_pct":
        if direction == "LONG":
            sl = entry * (1 - sl_val / 100)
        else:
            sl = entry * (1 + sl_val / 100)
    elif sl_method == "atr_mult":
        if direction == "LONG":
            sl = entry - atr * sl_val
        else:
            sl = entry + atr * sl_val
    elif sl_method == "rr_ratio":
        sl_dist = abs(tp - entry) / sl_val if sl_val > 0 else abs(entry * 0.01)
        if direction == "LONG":
            sl = entry - sl_dist
        else:
            sl = entry + sl_dist
    else:
        sl = sig.get("sl", 0)

    if not sl or not tp or sl == tp:
        return None, 0

    end_idx = min(idx + hold_bars, len(price_timeline))
    peak_price = entry
    trail_hit = False

    for j in range(idx + 1, end_idx):
        bar = price_by_ts[price_timeline[j]]
        high, low = bar["h"], bar["l"]

        # Trailing stop logic
        if trail_pct > 0:
            if direction == "LONG":
                if high > peak_price:
                    peak_price = high
                trail_sl = peak_price * (1 - trail_pct / 100)
                if trail_sl > sl:
                    sl = trail_sl
            else:
                if low < peak_price:
                    peak_price = low
                trail_sl = peak_price * (1 + trail_pct / 100)
                if trail_sl < sl:
                    sl = trail_sl

        if direction == "LONG":
            if high >= tp:
                return "WIN", j - idx
            if low <= sl:
                return "LOSS", j - idx
        else:
            if low <= tp:
                return "WIN", j - idx
            if high >= sl:
                return "LOSS", j - idx

    return "TIMEOUT", end_idx - idx

# =====================================================================
# SIMULATE
# =====================================================================
def simulate(filtered, hold_bars, risk_pct, leverage, tp_method, sl_method, tp_val, sl_val, trail_pct=0):
    cap = 200
    peak = cap
    max_dd = 0
    wins = 0
    losses = 0
    total = 0

    for sig in filtered:
        outcome, bars = check_outcome_custom(sig, hold_bars, tp_method, sl_method, tp_val, sl_val, trail_pct)
        if not outcome:
            continue
        total += 1

        rr1 = sig.get("rr1", 1.0) or 1.0
        if outcome == "WIN":
            pnl = cap * risk_pct * rr1 * leverage
            wins += 1
        elif outcome == "LOSS":
            pnl = -cap * risk_pct * leverage
            losses += 1
        else:
            pnl = 0

        cap += pnl
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if cap <= 0:
            cap = 0
            break

    return cap, max_dd, total, wins, losses

def calc_pf(wins, losses):
    return wins / losses if losses > 0 else (999 if wins > 0 else 0)

# =====================================================================
# PER-STRATEGY OPTIMIZATION
# =====================================================================
strats = sorted(set(s["strategy"] for s in signals))

print(f"\n{'='*120}")
print(f"PER-STRATEGY TP/SL OPTIMIZATION — {START_DATE} to {END_DATE}")
print(f"{'='*120}")

results_summary = []

for strat_name in strats:
    strat_signals = [s for s in signals if s["strategy"] == strat_name]
    if len(strat_signals) < 20:
        print(f"\n--- {strat_name}: {len(strat_signals)} signals (too few, skipping) ---")
        continue

    print(f"\n{'='*120}")
    print(f"STRATEGY: {strat_name} ({len(strat_signals)} signals)")
    print(f"{'='*120}")

    # Test configs
    configs = []

    # 1) Original TP/SL
    configs.append(("original/original", "original", "original", 0, 0, 0))

    # 2) Fixed pct TP/SL sweep
    for tp_pct in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
        for sl_pct in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]:
            configs.append((f"fixed TP={tp_pct}% SL={sl_pct}%", "fixed_pct", "fixed_pct", tp_pct, sl_pct, 0))

    # 3) ATR multiplier sweep
    for tp_atr in [0.5, 1.0, 1.5, 2.0, 3.0]:
        for sl_atr in [0.5, 1.0, 1.5, 2.0, 3.0]:
            configs.append((f"ATR TP={tp_atr}x SL={sl_atr}x", "atr_mult", "atr_mult", tp_atr, sl_atr, 0))

    # 4) RR ratio sweep (SL from signal, TP = SL * rr)
    for rr in [1.5, 2.0, 2.5, 3.0, 4.0]:
        configs.append((f"RR {rr}:1 (orig SL)", "rr_ratio", "original", rr, 0, 0))

    # 5) Trailing stop sweep
    for trail in [0.3, 0.5, 0.8, 1.0]:
        configs.append((f"fixed TP=1.0% SL=1.5% trail={trail}%", "fixed_pct", "fixed_pct", 1.0, 1.5, trail))

    # Direction filter
    for direction_filter in [None, "LONG", "SHORT"]:
        dir_label = f" [{direction_filter}]" if direction_filter else ""

        best_pf = 0
        best_config = None
        best_stats = None
        top5 = []

        for label, tp_m, sl_m, tp_v, sl_v, trail in configs:
            if direction_filter:
                filtered = [s for s in strat_signals if s["direction"] == direction_filter]
            else:
                filtered = strat_signals

            # Test multiple hold times
            for hold_h in [4, 8, 12]:
                hold_bars = hold_h * 4
                # Use 2% risk, 10x for comparison
                cap, dd, total, wins, losses = simulate(filtered, hold_bars, 0.02, 10,
                                                         tp_m, sl_m, tp_v, sl_v, trail)
                if total < 20:
                    continue
                pf = calc_pf(wins, losses)
                wr = wins / total * 100

                entry = {"label": label + f" {hold_h}h{dir_label}", "pf": pf, "wr": wr,
                         "total": total, "dd": dd, "cap": cap,
                         "tp_m": tp_m, "sl_m": sl_m, "tp_v": tp_v, "sl_v": sl_v,
                         "trail": trail, "hold": hold_h, "dir": direction_filter}
                top5.append(entry)

                if pf > best_pf:
                    best_pf = pf
                    best_config = entry

        # Sort by PF, show top 10
        top5.sort(key=lambda x: -x["pf"])
        print(f"\n  Top 10 configs{dir_label}:")
        print(f"  {'Config':<50} {'Hold':>5} {'Trades':>7} {'WR%':>7} {'PF':>7} {'DD%':>7}")
        print(f"  {'-'*90}")
        for entry in top5[:10]:
            marker = " <-- PF 2.0!" if entry["pf"] >= 2.0 else ""
            print(f"  {entry['label']:<50} {entry['hold']:>4}h {entry['total']:>7} {entry['wr']:>6.1f}% {entry['pf']:>6.2f} {entry['dd']:>6.1f}%{marker}")

        if best_config:
            results_summary.append({
                "strategy": strat_name,
                "direction": direction_filter,
                "best_pf": best_pf,
                "config": best_config["label"],
                "wr": best_config["wr"],
                "total": best_config["total"],
                "dd": best_config["dd"],
                "tp_m": best_config["tp_m"],
                "sl_m": best_config["sl_m"],
                "tp_v": best_config["tp_v"],
                "sl_v": best_config["sl_v"],
                "trail": best_config["trail"],
                "hold": best_config["hold"],
            })

# =====================================================================
# FINAL SUMMARY
# =====================================================================
print(f"\n\n{'='*120}")
print(f"FINAL SUMMARY — BEST CONFIG PER STRATEGY")
print(f"{'='*120}")
print(f"\n{'Strategy':<25} {'Dir':>6} {'BestPF':>7} {'WR%':>7} {'Trades':>7} {'DD%':>7} {'Config':<50}")
print(f"{'-'*120}")

for r in sorted(results_summary, key=lambda x: -x["best_pf"]):
    dir_label = r["direction"] or "ALL"
    marker = " PF>=2.0!" if r["best_pf"] >= 2.0 else ""
    print(f"{r['strategy']:<25} {dir_label:>6} {r['best_pf']:>6.2f} {r['wr']:>6.1f}% {r['total']:>7} {r['dd']:>6.1f}% {r['config']:<50}{marker}")

# Count strategies hitting PF 2.0
pf2_count = sum(1 for r in results_summary if r["best_pf"] >= 2.0)
pf15_count = sum(1 for r in results_summary if r["best_pf"] >= 1.5)
print(f"\n  Strategies at PF >= 2.0: {pf2_count}/{len(results_summary)}")
print(f"  Strategies at PF >= 1.5: {pf15_count}/{len(results_summary)}")

elapsed = time.time() - t0
print(f"\nCompleted in {elapsed:.1f}s")
