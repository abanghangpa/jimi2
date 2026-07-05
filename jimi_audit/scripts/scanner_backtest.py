#!/usr/bin/env python3
"""
Scanner Strategy Performance Analysis
Period: 2026-06-22 to 2026-07-04
Analyzes all 22 strategies in scanner.py for WR, PF, DD, capital growth.
Also tests: conviction filters, regime filters, strategy combos.
"""
import json, os, glob, sys, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import sqlite3

t0 = time.time()

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
SIGNALS_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"
OUTCOMES_DB = "/root/.openclaw/workspace/jimi_audit/data/outcomes.db"
ETH_CSV = "/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv"

START_DATE = "2026-06-22"
END_DATE = "2026-07-05"

# =====================================================================
# 1) LOAD PRICE DATA from CSV
# =====================================================================
print("Loading ETH price data...")
price_by_ts = {}
price_timeline = []
with open(ETH_CSV) as f:
    header = f.readline()
    for line in f:
        parts = line.strip().split(",")
        ts_str = parts[0]
        if ts_str >= START_DATE and ts_str <= END_DATE:
            o, h, l, c = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            price_by_ts[ts_str] = {"open": o, "high": h, "low": l, "close": c}
            price_timeline.append(ts_str)
price_timeline.sort()
print(f"  Loaded {len(price_by_ts)} bars from {price_timeline[0]} to {price_timeline[-1]}")

# =====================================================================
# 2) LOAD SCAN SIGNALS (from scan JSON files, Jun 22 - Jul 4)
# =====================================================================
print("Loading scan signals...")
scan_files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
signals = []  # [{strategy, timestamp, price, direction, conviction, entry, sl, tp1, rr1}]

for sf in scan_files:
    fname = os.path.basename(sf)
    # Extract date from filename: scan_20260622_084452.json
    date_str = fname[5:15]  # 20260622
    if date_str < START_DATE.replace("-", "") or date_str >= END_DATE.replace("-", ""):
        continue
    try:
        with open(sf) as f:
            data = json.load(f)
    except:
        continue

    ts = data.get("timestamp", "")
    price = data.get("price", 0)

    # Extract strategies from the scan
    strategies = data.get("strategies", data.get("strategy_results", {}))
    if isinstance(strategies, dict):
        for strat_name, strat_data in strategies.items():
            if not isinstance(strat_data, dict):
                continue
            direction = strat_data.get("direction")
            conviction = strat_data.get("conviction", 0)
            entry = strat_data.get("entry", price)
            sl = strat_data.get("sl", 0)
            tp1 = strat_data.get("tp1", 0)
            rr1 = strat_data.get("rr1", 0)
            fired = strat_data.get("fired", True)
            if fired and direction and conviction > 0:
                signals.append({
                    "strategy": strat_name,
                    "timestamp": ts,
                    "price": price,
                    "direction": direction,
                    "conviction": conviction,
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "rr1": rr1,
                })

print(f"  Loaded {len(signals)} fired signals from {len(scan_files)} scan files")

# Also try loading from strategy_signals.jsonl (has more detail)
print("Loading from strategy_signals.jsonl...")
jsonl_signals = []
jsonl_count = 0
with open(SIGNALS_FILE) as f:
    for line in f:
        jsonl_count += 1
        if jsonl_count > 2000000:  # Limit for performance
            break
        try:
            d = json.loads(line)
            ts = d.get("timestamp", "")
            if ts < START_DATE or ts >= END_DATE:
                continue
            if d.get("fired") and d.get("direction") and d.get("conviction", 0) > 0:
                jsonl_signals.append(d)
        except:
            continue

print(f"  Loaded {len(jsonl_signals)} fired signals from JSONL (scanned {jsonl_count} lines)")

# Merge: prefer JSONL (has more detail), supplement with scan JSON
signal_map = {}  # key = (strategy, timestamp) -> signal
for s in jsonl_signals:
    key = (s["strategy"], s["timestamp"])
    signal_map[key] = s
for s in signals:
    key = (s["strategy"], s["timestamp"])
    if key not in signal_map:
        signal_map[key] = s

all_signals = sorted(signal_map.values(), key=lambda x: x["timestamp"])
print(f"  Total unique signals: {len(all_signals)}")

# =====================================================================
# 3) CHECK OUTCOMES
# =====================================================================
print("\nChecking outcomes against price data...")

def find_bar_idx(ts_str):
    """Find the bar index for a given timestamp."""
    # Try exact match first
    if ts_str in price_by_ts:
        try:
            return price_timeline.index(ts_str)
        except ValueError:
            pass
    # Try prefix match
    prefix = ts_str[:16]
    for i, t in enumerate(price_timeline):
        if t.startswith(prefix):
            return i
    return None

def check_outcome(sig, hold_bars=32):
    """Check if TP or SL hit within hold_bars (8h = 32 x 15min)."""
    idx = find_bar_idx(sig["timestamp"])
    if idx is None:
        return None, 0

    direction = sig["direction"]
    entry = sig.get("entry", sig.get("price", 0))
    sl = sig.get("sl", 0)
    tp1 = sig.get("tp1", 0)

    if not sl or not tp1 or sl == tp1:
        return None, 0

    end_idx = min(idx + hold_bars, len(price_timeline))
    for j in range(idx + 1, end_idx):
        bar = price_by_ts[price_timeline[j]]
        high = bar["high"]
        low = bar["low"]

        if direction == "LONG":
            if high >= tp1:
                return "WIN", j - idx
            if low <= sl:
                return "LOSS", j - idx
        else:  # SHORT
            if low <= tp1:
                return "WIN", j - idx
            if high >= sl:
                return "LOSS", j - idx

    # Timeout - exit at close
    if end_idx > idx:
        return "TIMEOUT", end_idx - idx
    return None, 0

# Process all signals
results = []
for i, sig in enumerate(all_signals):
    outcome, bars_held = check_outcome(sig)
    if outcome:
        rr1 = sig.get("rr1", 1.0) or 1.0
        entry = sig.get("entry", sig.get("price", 0))
        sl = sig.get("sl", 0)
        tp1 = sig.get("tp1", 0)
        sl_pct = abs(entry - sl) / entry * 100 if entry else 0
        tp_pct = abs(tp1 - entry) / entry * 100 if entry else 0

        results.append({
            "strategy": sig["strategy"],
            "timestamp": sig["timestamp"],
            "direction": sig["direction"],
            "conviction": sig.get("conviction", 0),
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "rr1": rr1,
            "outcome": outcome,
            "bars_held": bars_held,
        })

    if (i + 1) % 5000 == 0:
        print(f"  Processed {i+1}/{len(all_signals)} signals...", flush=True)

print(f"  Evaluated {len(results)} signals with outcomes")

# =====================================================================
# 4) COMPUTE PER-STRATEGY STATS
# =====================================================================
print("\n" + "=" * 100)
print("SCANNER STRATEGY PERFORMANCE ANALYSIS")
print(f"Period: {START_DATE} to {END_DATE}")
print("=" * 100)

strat_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "timeout": 0, "total": 0,
                                     "win_pnl": 0, "loss_pnl": 0, "rr_sum": 0,
                                     "convictions": [], "directions": {"LONG": {"w": 0, "l": 0, "t": 0},
                                                                        "SHORT": {"w": 0, "l": 0, "t": 0}}})

for r in results:
    s = strat_stats[r["strategy"]]
    s["total"] += 1
    s["convictions"].append(r["conviction"])
    s["rr_sum"] += r["rr1"]

    dir_key = r["direction"]
    if dir_key not in s["directions"]:
        s["directions"][dir_key] = {"w": 0, "l": 0, "t": 0}

    if r["outcome"] == "WIN":
        s["wins"] += 1
        s["win_pnl"] += r["rr1"]
        s["directions"][dir_key]["w"] += 1
    elif r["outcome"] == "LOSS":
        s["losses"] += 1
        s["loss_pnl"] += 1  # 1R loss
        s["directions"][dir_key]["l"] += 1
    else:
        s["timeout"] += 1
        s["directions"][dir_key]["t"] += 1

# Print header
print(f"\n{'Strategy':<30} {'Total':>6} {'Win':>6} {'Loss':>6} {'TO':>6} {'WR%':>7} {'PF':>7} {'AvgRR':>7} {'Conv%':>7}")
print("-" * 100)

strat_results = []
for name, s in sorted(strat_stats.items(), key=lambda x: -x[1]["wins"] / max(x[1]["total"], 1)):
    t = s["total"]
    if t < 5:
        continue
    w = s["wins"]
    l = s["losses"]
    to = s["timeout"]
    wr = w / t * 100 if t else 0
    pf = s["win_pnl"] / s["loss_pnl"] if s["loss_pnl"] > 0 else (999 if w > 0 else 0)
    avg_rr = s["rr_sum"] / t if t else 0
    avg_conv = sum(s["convictions"]) / len(s["convictions"]) if s["convictions"] else 0

    print(f"{name:<30} {t:>6} {w:>6} {l:>6} {to:>6} {wr:>6.1f}% {pf:>6.2f} {avg_rr:>6.3f} {avg_conv*100:>6.1f}%")
    strat_results.append({"name": name, "total": t, "wins": w, "losses": l, "timeout": to,
                          "wr": wr, "pf": pf, "avg_rr": avg_rr, "avg_conv": avg_conv})

# =====================================================================
# 5) CAPITAL SIMULATION PER STRATEGY
# =====================================================================
print(f"\n{'='*100}")
print("CAPITAL SIMULATION (per strategy, $200 start, 5% risk, 20x lev)")
print(f"{'='*100}")
print(f"\n{'Strategy':<30} {'Final$':>10} {'Return%':>10} {'MaxDD%':>10} {'Trades':>8} {'MoM WR':>8}")
print("-" * 100)

for sr in sorted(strat_results, key=lambda x: -x["pf"]):
    name = sr["name"]
    # Simulate capital
    cap = 200
    peak = cap
    max_dd = 0
    strat_trades = [r for r in results if r["strategy"] == name]

    for r in strat_trades:
        risk_pct = 0.05
        if r["outcome"] == "WIN":
            pnl = cap * risk_pct * r["rr1"] * 20  # 20x leverage
        elif r["outcome"] == "LOSS":
            pnl = -cap * risk_pct * 20
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

    ret = (cap - 200) / 200 * 100

    # Monthly win rate
    monthly = defaultdict(lambda: {"w": 0, "l": 0})
    for r in strat_trades:
        month = r["timestamp"][:7]
        if r["outcome"] == "WIN":
            monthly[month]["w"] += 1
        elif r["outcome"] == "LOSS":
            monthly[month]["l"] += 1
    months_profitable = sum(1 for m in monthly.values() if m["w"] > m["l"])
    months_total = len(monthly)
    mom_wr = f"{months_profitable}/{months_total}" if months_total else "N/A"

    print(f"{name:<30} ${cap:>9,.0f} {ret:>9.0f}% {max_dd:>9.1f}% {len(strat_trades):>8} {mom_wr:>8}")

# =====================================================================
# 6) COMBINATION ANALYSIS (top 3 strategies only)
# =====================================================================
print(f"\n{'='*100}")
print("TOP 3 STRATEGIES COMBO ANALYSIS")
print(f"{'='*100}")

top3 = sorted(strat_results, key=lambda x: x["pf"], reverse=True)[:3]
top3_names = [s["name"] for s in top3]
print(f"Top 3 by PF: {', '.join(top3_names)}")

# Simulate combined (best signal wins)
combo_trades = []
for ts_str in sorted(set(r["timestamp"] for r in results)):
    ts_trades = [r for r in results if r["timestamp"] == ts_str and r["strategy"] in top3_names]
    if ts_trades:
        # Pick highest conviction
        best = max(ts_trades, key=lambda x: x["conviction"])
        combo_trades.append(best)

cap = 200
peak = cap
max_dd = 0
for r in combo_trades:
    if r["outcome"] == "WIN":
        pnl = cap * 0.05 * r["rr1"] * 20
    elif r["outcome"] == "LOSS":
        pnl = -cap * 0.05 * 20
    else:
        pnl = 0
    cap += pnl
    if cap > peak: peak = cap
    dd = (peak - cap) / peak * 100 if peak > 0 else 0
    if dd > max_dd: max_dd = dd
    if cap <= 0: cap = 0; break

combo_wins = sum(1 for r in combo_trades if r["outcome"] == "WIN")
combo_losses = sum(1 for r in combo_trades if r["outcome"] == "LOSS")
combo_wr = combo_wins / len(combo_trades) * 100 if combo_trades else 0
combo_pf = combo_wins / combo_losses if combo_losses > 0 else 999

print(f"\nCombo (top3, best conviction): {len(combo_trades)} trades")
print(f"  WR: {combo_wr:.1f}% | PF: {combo_pf:.2f} | Final: ${cap:,.0f} | DD: {max_dd:.1f}%")

# =====================================================================
# 7) CONVICTION FILTER SWEEP
# =====================================================================
print(f"\n{'='*100}")
print("CONVICTION FILTER SWEEP (all strategies)")
print(f"{'='*100}")
print(f"\n{'MinConv':>8} {'Trades':>8} {'WR%':>7} {'PF':>7} {'Final$':>10} {'DD%':>7}")
print("-" * 60)

for min_conv in [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
    filtered = [r for r in results if r["conviction"] >= min_conv]
    if not filtered:
        continue
    w = sum(1 for r in filtered if r["outcome"] == "WIN")
    l = sum(1 for r in filtered if r["outcome"] == "LOSS")
    t = len(filtered)
    wr = w / t * 100 if t else 0
    pf = w / l if l > 0 else 999

    cap = 200
    peak = cap
    max_dd = 0
    for r in filtered:
        if r["outcome"] == "WIN":
            pnl = cap * 0.05 * r["rr1"] * 20
        elif r["outcome"] == "LOSS":
            pnl = -cap * 0.05 * 20
        else:
            pnl = 0
        cap += pnl
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
        if cap <= 0: cap = 0; break

    print(f"{min_conv:>7.1f} {t:>8} {wr:>6.1f}% {pf:>6.2f} ${cap:>9,.0f} {max_dd:>6.1f}%")

# =====================================================================
# 8) DIRECTION FILTER
# =====================================================================
print(f"\n{'='*100}")
print("DIRECTION FILTER ANALYSIS")
print(f"{'='*100}")

for direction in ["LONG", "SHORT"]:
    filtered = [r for r in results if r["direction"] == direction]
    w = sum(1 for r in filtered if r["outcome"] == "WIN")
    l = sum(1 for r in filtered if r["outcome"] == "LOSS")
    t = len(filtered)
    wr = w / t * 100 if t else 0
    pf = w / l if l > 0 else 999
    print(f"{direction}: {t} trades, WR={wr:.1f}%, PF={pf:.2f}")

# =====================================================================
# 9) REGIME ANALYSIS (by week)
# =====================================================================
print(f"\n{'='*100}")
print("WEEKLY PERFORMANCE BREAKDOWN")
print(f"{'='*100}")
print(f"\n{'Week':>12} {'Trades':>8} {'WR%':>7} {'PF':>7} {'Best Strategy':>25}")
print("-" * 70)

weekly = defaultdict(list)
for r in results:
    # Group by week
    dt = datetime.strptime(r["timestamp"][:10], "%Y-%m-%d")
    week_start = dt - timedelta(days=dt.weekday())
    weekly[week_start.strftime("%Y-%m-%d")].append(r)

for week, trades in sorted(weekly.items()):
    w = sum(1 for r in trades if r["outcome"] == "WIN")
    l = sum(1 for r in trades if r["outcome"] == "LOSS")
    t = len(trades)
    wr = w / t * 100 if t else 0
    pf = w / l if l > 0 else 999

    # Best strategy this week
    week_strats = defaultdict(lambda: {"w": 0, "l": 0})
    for r in trades:
        if r["outcome"] == "WIN":
            week_strats[r["strategy"]]["w"] += 1
        elif r["outcome"] == "LOSS":
            week_strats[r["strategy"]]["l"] += 1
    best_strat = max(week_strats.items(), key=lambda x: x[1]["w"] / max(x[1]["w"] + x[1]["l"], 1))
    best_name = best_strat[0]

    print(f"{week:>12} {t:>8} {wr:>6.1f}% {pf:>6.2f} {best_name:>25}")

# =====================================================================
# 10) FIND PF 2.0 CONFIGURATION
# =====================================================================
print(f"\n{'='*100}")
print("PF 2.0 TARGET: WHAT CHANGES ARE NEEDED?")
print(f"{'='*100}")

# Try: disable worst strategies + conviction filter
worst_strats = sorted(strat_results, key=lambda x: x["pf"])[:5]
best_strats = sorted(strat_results, key=lambda x: x["pf"], reverse=True)[:5]

print("\nBest 5 strategies:")
for s in best_strats:
    print(f"  {s['name']:<30} PF={s['pf']:.2f} WR={s['wr']:.1f}% n={s['total']}")

print("\nWorst 5 strategies:")
for s in worst_strats:
    print(f"  {s['name']:<30} PF={s['pf']:.2f} WR={s['wr']:.1f}% n={s['total']}")

# Test: only best 3 + conviction 0.5
for min_conv in [0.0, 0.3, 0.5, 0.6]:
    for n_best in [3, 4, 5]:
        top_n = [s["name"] for s in sorted(strat_results, key=lambda x: x["pf"], reverse=True)[:n_best]]
        filtered = [r for r in results if r["strategy"] in top_n and r["conviction"] >= min_conv]
        if not filtered:
            continue
        w = sum(1 for r in filtered if r["outcome"] == "WIN")
        l = sum(1 for r in filtered if r["outcome"] == "LOSS")
        t = len(filtered)
        wr = w / t * 100 if t else 0
        pf = w / l if l > 0 else 999
        marker = " <-- PF 2.0!" if pf >= 2.0 else ""
        if t >= 30:
            print(f"\n  Top{n_best} + conv>={min_conv:.1f}: {t} trades, WR={wr:.1f}%, PF={pf:.2f}{marker}")

elapsed = time.time() - t0
print(f"\n\nCompleted in {elapsed:.1f}s")
print(f"Total signals analyzed: {len(all_signals)}")
print(f"Total outcomes: {len(results)}")
