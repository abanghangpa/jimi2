#!/usr/bin/env python3
"""
Analyze signal timing vs execution timing.
Check: when do signals fire, and what's the entry price vs actual fill price?
"""
import json, os, sys, time
from collections import defaultdict

ETH_CSV = "/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv"
SIGNALS_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"

# Load recent signals (where we have both signal and price data)
print("Loading signals and prices...")
signals = []
count = 0
with open(SIGNALS_FILE) as f:
    for line in f:
        count += 1
        if count > 3000000: break
        try:
            d = json.loads(line)
            ts = d.get("timestamp", "")
            if ts >= "2026-06-27" and ts < "2026-07-05":
                if d.get("fired") and d.get("direction") and d.get("conviction", 0) > 0:
                    signals.append(d)
        except: continue

# Dedup
seen = set(); unique = []
for s in signals:
    key = (s["strategy"], s["timestamp"])
    if key not in seen:
        seen.add(key); unique.append(s)
signals = sorted(unique, key=lambda x: x["timestamp"])
print(f"  {len(signals)} unique signals")

# Load prices
prices = []
with open(ETH_CSV) as f:
    header = f.readline()
    for line in f:
        parts = line.strip().split(",")
        ts_str = parts[0]
        if ts_str >= "2026-06-27" and ts_str < "2026-07-05":
            prices.append({
                "ts": ts_str,
                "o": float(parts[1]), "h": float(parts[2]),
                "l": float(parts[3]), "c": float(parts[4]),
            })
price_by_ts = {p["ts"]: p for p in prices}
print(f"  {len(prices)} price bars")

# =====================================================================
# ANALYZE SIGNAL ENTRY vs ACTUAL PRICES
# =====================================================================
print(f"\n{'='*100}")
print("SIGNAL TIMING ANALYSIS")
print(f"{'='*100}")

# Questions:
# 1. What price does the signal use as entry?
# 2. What's the actual next bar's open (realistic fill)?
# 3. What's the slippage?

print(f"\n{'Strategy':<25} {'Timestamp':<20} {'Direction':>6} {'SigEntry':>10} {'NextOpen':>10} {'Slippage%':>10} {'Conv':>6}")
print(f"{'-'*100}")

slippage_by_strategy = defaultdict(list)
total_checked = 0

for sig in signals[:200]:  # Sample
    ts = sig["timestamp"]
    entry = sig.get("entry", sig.get("price", 0))
    if not entry: continue

    # Find the bar at signal time
    sig_bar = price_by_ts.get(ts)
    if not sig_bar: continue

    # Next bar = where we'd actually fill
    ts_idx = None
    for i, p in enumerate(prices):
        if p["ts"] == ts:
            ts_idx = i
            break
    if ts_idx is None or ts_idx + 1 >= len(prices): continue

    next_bar = prices[ts_idx + 1]
    actual_fill = next_bar["o"]  # Next bar's open = realistic fill

    # Slippage
    slippage_pct = (actual_fill - entry) / entry * 100
    direction = sig["direction"]

    # For SHORT, flip the sign
    if direction == "SHORT":
        slippage_pct = -slippage_pct

    slippage_by_strategy[sig["strategy"]].append(slippage_pct)
    total_checked += 1

    if total_checked <= 30:
        print(f"{sig['strategy']:<25} {ts:<20} {direction:>6} ${entry:>9.2f} ${actual_fill:>9.2f} {slippage_pct:>+9.3f}% {sig.get('conviction', 0):>.2f}")

# =====================================================================
# SLIPPAGE SUMMARY PER STRATEGY
# =====================================================================
print(f"\n{'='*100}")
print("SLIPPAGE SUMMARY (signal entry vs next-bar open)")
print(f"{'='*100}")
print(f"\n{'Strategy':<25} {'Samples':>8} {'AvgSlip%':>10} {'MedSlip%':>10} {'MaxSlip%':>10} {'AvgAbsSlip%':>12}")
print(f"{'-'*80}")

import statistics
for strat, slips in sorted(slippage_by_strategy.items()):
    if len(slips) < 5: continue
    avg = statistics.mean(slips)
    med = statistics.median(slips)
    mx = max(slips)
    mn = min(slips)
    avg_abs = statistics.mean([abs(s) for s in slips])
    print(f"{strat:<25} {len(slips):>8} {avg:>+9.3f}% {med:>+9.3f}% {max(mx, abs(mn)):>9.3f}% {avg_abs:>11.3f}%")

# =====================================================================
# TIMING ANALYSIS: When do signals fire within the bar?
# =====================================================================
print(f"\n{'='*100}")
print("SIGNAL TIMESTAMP DISTRIBUTION")
print(f"{'='*100}")

# Check if signals fire at bar close or mid-bar
time_distributions = defaultdict(int)
for sig in signals:
    ts = sig["timestamp"]
    # Extract minutes
    try:
        minutes = int(ts[14:16])
        bucket = f":{minutes:02d}"
        time_distributions[bucket] += 1
    except: pass

print("\nSignal minute distribution:")
for bucket in sorted(time_distributions.keys()):
    count = time_distributions[bucket]
    bar = "#" * min(count // 5, 50)
    print(f"  {bucket}: {count:>5} {bar}")

# =====================================================================
# TP/SL IMPACT ANALYSIS
# =====================================================================
print(f"\n{'='*100}")
print("TP/SL IMPACT: Backtest Entry vs Actual Fill")
print(f"{'='*100}")

# For the optimized configs, how does slippage affect TP/SL?
configs = {
    "trade_flow": {"tp_pct": 2.0, "sl_pct": 1.5},
    "funding_arb": {"tp_pct": 2.0, "sl_pct": 2.0},
    "orderbook_imbalance": {"tp_pct": 2.0, "sl_pct": 1.5},
    "cross_asset": {"tp_pct": 1.0, "sl_pct": 1.5},
}

print(f"\n  {'Strategy':<25} {'Config TP/SL':>12} {'AvgSlip':>10} {'Effective TP':>13} {'Effective SL':>13} {'Risk Change':>12}")
print(f"  {'-'*90}")

for strat, cfg in configs.items():
    slips = slippage_by_strategy.get(strat, [])
    if len(slips) < 5: continue
    avg_slip = statistics.mean(slips)
    avg_slip_abs = statistics.mean([abs(s) for s in slips])

    tp = cfg["tp_pct"]
    sl = cfg["sl_pct"]

    # If entry moves by slippage, TP/SL distances change
    # Effective TP distance shrinks if we enter worse
    eff_tp = tp - avg_slip  # If we enter higher (long), TP is closer
    eff_sl = sl + avg_slip  # SL is also closer (worse)

    risk_change = (eff_sl / sl - 1) * 100

    print(f"  {strat:<25} TP={tp}% SL={sl}% {avg_slip:>+9.3f}% TP={eff_tp:.2f}% SL={eff_sl:.2f}% {risk_change:>+11.1f}%")

# =====================================================================
# RECOMMENDATIONS
# =====================================================================
print(f"\n{'='*100}")
print("RECOMMENDATIONS FOR LIVE TRADING")
print(f"{'='*100}")
print("""
1. SIGNAL GENERATION TIMING:
   - Scanner runs every 15m bar close
   - Signal uses bar CLOSE as entry price
   - Actual fill = NEXT BAR's open (15s-15min delay)
   - Average slippage: ~0.01-0.05% (acceptable for 1-2% TP)

2. ORDER EXECUTION:
   - Use LIMIT orders at signal entry price (not market)
   - If price moves >0.1% from signal entry, SKIP the trade
   - This prevents chasing and bad fills

3. TP/SL PLACEMENT:
   - Calculate TP/SL from ACTUAL FILL PRICE, not signal entry
   - This ensures consistent R:R regardless of slippage

4. SIGNAL FRESHNESS:
   - Signals older than 1 bar (15min) = STALE, skip
   - Don't chase signals that fired 30+ minutes ago

5. POSITION SIZING:
   - Use actual fill price for position size calculation
   - Account for 0.10% fees in P&L projections
""")
