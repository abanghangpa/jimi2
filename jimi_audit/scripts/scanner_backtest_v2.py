#!/usr/bin/env python3
"""
Scanner Backtest V2 — deeper analysis with:
- Actual TP/SL from signals (not simulated)
- Leverage sweep (5x, 10x, 20x)
- Risk sweep (1%, 2%, 5%)
- Hold time sweep (2h, 4h, 8h)
- SHORT-only and LONG-only
- Strategy exclusion combos
"""
import json, os, glob, sys, time
from datetime import datetime, timedelta
from collections import defaultdict

t0 = time.time()

SCAN_DIR = "/root/.openclaw/workspace/jimi_audit/data/scans"
SIGNALS_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"
ETH_CSV = "/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv"

START_DATE = "2026-06-22"
END_DATE = "2026-07-05"

# =====================================================================
# 1) LOAD PRICE DATA
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
print(f"  {len(price_by_ts)} bars: {price_timeline[0]} -> {price_timeline[-1]}")

# =====================================================================
# 2) LOAD SIGNALS
# =====================================================================
print("Loading signals from JSONL...")
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

print(f"  {len(signals)} fired signals loaded")

# Dedup by (strategy, timestamp)
seen = set()
unique = []
for s in signals:
    key = (s["strategy"], s["timestamp"])
    if key not in seen:
        seen.add(key)
        unique.append(s)
signals = sorted(unique, key=lambda x: x["timestamp"])
print(f"  {len(signals)} unique signals after dedup")

# =====================================================================
# 3) FIND BAR INDEX
# =====================================================================
def find_bar_idx(ts_str):
    prefix = ts_str[:16]
    for i, t in enumerate(price_timeline):
        if t[:16] == prefix:
            return i
    return None

# =====================================================================
# 4) CHECK OUTCOME with variable hold time
# =====================================================================
def check_outcome(sig, hold_bars=32):
    idx = find_bar_idx(sig["timestamp"])
    if idx is None:
        return None, 0, 0

    direction = sig["direction"]
    entry = sig.get("entry", sig.get("price", 0))
    sl = sig.get("sl", 0)
    tp1 = sig.get("tp1", 0)

    if not sl or not tp1 or sl == tp1:
        return None, 0, 0

    end_idx = min(idx + hold_bars, len(price_timeline))
    for j in range(idx + 1, end_idx):
        bar = price_by_ts[price_timeline[j]]
        high = bar["high"]
        low = bar["low"]

        if direction == "LONG":
            if high >= tp1:
                return "WIN", j - idx, abs(tp1 - entry) / entry
            if low <= sl:
                return "LOSS", j - idx, abs(entry - sl) / entry
        else:
            if low <= tp1:
                return "WIN", j - idx, abs(entry - tp1) / entry
            if high >= sl:
                return "LOSS", j - idx, abs(sl - entry) / entry

    if end_idx > idx:
        bar = price_by_ts[price_timeline[end_idx - 1]]
        exit_price = bar["close"]
        if direction == "LONG":
            pnl_pct = (exit_price - entry) / entry
        else:
            pnl_pct = (entry - exit_price) / entry
        return "TIMEOUT", end_idx - idx, pnl_pct
    return None, 0, 0

# =====================================================================
# 5) SIMULATE with params
# =====================================================================
def simulate(filtered_signals, hold_bars, risk_pct, leverage, use_actual_sl=True):
    """Simulate capital growth. Returns (final_cap, max_dd, trades, wins, losses)."""
    cap = 200
    peak = cap
    max_dd = 0
    wins = 0
    losses = 0
    total = 0

    for sig in filtered_signals:
        outcome, bars, pnl_pct = check_outcome(sig, hold_bars)
        if not outcome:
            continue
        total += 1

        if use_actual_sl and pnl_pct > 0:
            # Use actual TP/SL percentage
            pnl = cap * risk_pct * (pnl_pct / (abs(sig.get("entry", 0) - sig.get("sl", 1)) / sig.get("entry", 1))) * leverage if sig.get("entry") and sig.get("sl") else 0
        else:
            # Simple: WIN = +rr1*R, LOSS = -1*R
            rr1 = sig.get("rr1", 1.0) or 1.0
            if outcome == "WIN":
                pnl = cap * risk_pct * rr1 * leverage
            elif outcome == "LOSS":
                pnl = -cap * risk_pct * leverage
            else:
                pnl = 0

        cap += pnl
        if outcome == "WIN":
            wins += 1
        elif outcome == "LOSS":
            losses += 1

        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if cap <= 0:
            cap = 0
            break

    return cap, max_dd, total, wins, losses

# =====================================================================
# RUN ANALYSIS
# =====================================================================
print(f"\n{'='*110}")
print(f"SCANNER STRATEGY DEEP ANALYSIS — {START_DATE} to {END_DATE}")
print(f"{'='*110}")

# Get strategy list
strats = sorted(set(s["strategy"] for s in signals))
print(f"\nStrategies found: {', '.join(strats)}")

# --- PER-STRATEGY with actual TP/SL ---
print(f"\n{'='*110}")
print("PER-STRATEGY PERFORMANCE (default: 8h hold, actual TP/SL)")
print(f"{'='*110}")
print(f"\n{'Strategy':<30} {'Trades':>7} {'WR%':>7} {'PF':>7} {'AvgRR':>7} {'AvgConv':>8} {'LONG_WR':>8} {'SHORT_WR':>8}")
print("-" * 110)

strat_info = {}
for name in strats:
    strat_signals = [s for s in signals if s["strategy"] == name]
    outcomes = []
    long_w, long_l, short_w, short_l = 0, 0, 0, 0
    for sig in strat_signals:
        o, bars, pnl_pct = check_outcome(sig, 32)
        if o:
            outcomes.append((o, pnl_pct))
            if sig["direction"] == "LONG":
                if o == "WIN": long_w += 1
                elif o == "LOSS": long_l += 1
            else:
                if o == "WIN": short_w += 1
                elif o == "LOSS": short_l += 1

    total = len(outcomes)
    if total < 5:
        continue

    wins = sum(1 for o, _ in outcomes if o == "WIN")
    losses = sum(1 for o, _ in outcomes if o == "LOSS")
    wr = wins / total * 100

    # PF from actual RR
    win_sum = sum(pnl for o, pnl in outcomes if o == "WIN")
    loss_sum = sum(abs(pnl) for o, pnl in outcomes if o == "LOSS" and pnl != 0)
    pf = win_sum / loss_sum if loss_sum > 0 else 999

    avg_rr = sum(pnl for _, pnl in outcomes) / total
    avg_conv = sum(s.get("conviction", 0) for s in strat_signals) / len(strat_signals)

    long_total = long_w + long_l
    short_total = short_w + short_l
    long_wr = long_w / long_total * 100 if long_total else 0
    short_wr = short_w / short_total * 100 if short_total else 0

    print(f"{name:<30} {total:>7} {wr:>6.1f}% {pf:>6.2f} {avg_rr:>7.4f} {avg_conv*100:>7.1f}% {long_wr:>7.1f}% {short_wr:>7.1f}%")
    strat_info[name] = {"pf": pf, "wr": wr, "total": total, "signals": strat_signals}

# --- PARAMETER SWEEP ---
print(f"\n{'='*110}")
print("PARAMETER SWEEP (top3 strategies: orderbook_imbalance, trade_flow, cross_asset)")
print(f"{'='*110}")

top3_names = ["orderbook_imbalance", "trade_flow", "cross_asset"]
top3_signals = [s for s in signals if s["strategy"] in top3_names]

print(f"\n{'Hold':>6} {'Risk%':>6} {'Lev':>5} {'Trades':>7} {'WR%':>7} {'PF':>7} {'Final$':>10} {'DD%':>7} {'Return%':>8}")
print("-" * 80)

for hold_h in [2, 4, 8, 12, 24]:
    hold_bars = hold_h * 4  # 15min bars
    for risk in [0.01, 0.02, 0.05]:
        for lev in [5, 10, 20]:
            cap, dd, total, wins, losses = simulate(top3_signals, hold_bars, risk, lev)
            wr = wins / total * 100 if total else 0
            pf = wins / losses if losses > 0 else 999
            ret = (cap - 200) / 200 * 100
            if total >= 30:
                print(f"{hold_h:>5}h {risk*100:>5.0f}% {lev:>4}x {total:>7} {wr:>6.1f}% {pf:>6.2f} ${cap:>9,.0f} {dd:>6.1f}% {ret:>7.0f}%")

# --- STRATEGY EXCLUSION COMBO ---
print(f"\n{'='*110}")
print("STRATEGY EXCLUSION COMBOS (8h, 2% risk, 10x)")
print(f"{'='*110}")
print(f"\n{'Included Strategies':<70} {'Trades':>7} {'WR%':>7} {'PF':>7} {'Final$':>10} {'DD%':>7}")
print("-" * 110)

worst_to_best = sorted(strat_info.items(), key=lambda x: x[1]["pf"])

# Start with all, then remove worst one by one
excluded = set()
for i in range(len(worst_to_best)):
    if i > 0:
        excluded.add(worst_to_best[i-1][0])
    included = [s for s in strats if s not in excluded]
    filtered = [s for s in signals if s["strategy"] in included]
    if len(filtered) < 30:
        continue

    cap, dd, total, wins, losses = simulate(filtered, 32, 0.02, 10)
    wr = wins / total * 100 if total else 0
    pf = wins / losses if losses > 0 else 999

    names = ", ".join(included)
    if len(names) > 68:
        names = names[:65] + "..."
    marker = " <-- PF 2.0!" if pf >= 2.0 else ""
    print(f"{names:<70} {total:>7} {wr:>6.1f}% {pf:>6.2f} ${cap:>9,.0f} {dd:>6.1f}%{marker}")

# --- SHORT ONLY ---
print(f"\n{'='*110}")
print("SHORT-ONLY ANALYSIS")
print(f"{'='*110}")
short_signals = [s for s in signals if s["direction"] == "SHORT"]
for min_conv in [0.0, 0.5, 0.6, 0.7, 0.8]:
    filtered = [s for s in short_signals if s.get("conviction", 0) >= min_conv]
    if len(filtered) < 20:
        continue
    for lev in [5, 10, 20]:
        cap, dd, total, wins, losses = simulate(filtered, 32, 0.02, lev)
        wr = wins / total * 100 if total else 0
        pf = wins / losses if losses > 0 else 999
        marker = " <-- PF 2.0!" if pf >= 2.0 else ""
        if total >= 20:
            print(f"conv>={min_conv:.1f} {lev:>2}x: {total:>5} trades, WR={wr:.1f}%, PF={pf:.2f}, Final=${cap:,.0f}, DD={dd:.1f}%{marker}")

# --- DIRECTION + STRATEGY ---
print(f"\n{'='*110}")
print("DIRECTION x STRATEGY MATRIX (8h, 2% risk, 10x)")
print(f"{'='*110}")
print(f"\n{'Strategy':<30} {'Dir':>6} {'Trades':>7} {'WR%':>7} {'PF':>7} {'Final$':>10} {'DD%':>7}")
print("-" * 80)

for name in strats:
    for direction in ["LONG", "SHORT"]:
        filtered = [s for s in signals if s["strategy"] == name and s["direction"] == direction]
        if len(filtered) < 10:
            continue
        cap, dd, total, wins, losses = simulate(filtered, 32, 0.02, 10)
        wr = wins / total * 100 if total else 0
        pf = wins / losses if losses > 0 else 999
        marker = " <-- PF 2.0!" if pf >= 2.0 else ""
        print(f"{name:<30} {direction:>6} {total:>7} {wr:>6.1f}% {pf:>6.2f} ${cap:>9,.0f} {dd:>6.1f}%{marker}")

elapsed = time.time() - t0
print(f"\nCompleted in {elapsed:.1f}s")
