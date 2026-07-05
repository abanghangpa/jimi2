#!/usr/bin/env python3
"""
Scanner Walk-Forward Validation
Train: 2021-01 to 2024-06 (in-sample)
Test:  2024-07 to 2026-07 (out-of-sample)

Uses optimized TP/SL per strategy from fee-adjusted backtest.
Tests: consistency, degradation, regime robustness.
"""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

t0 = time.time()

ETH_CSV = "/root/.openclaw/workspace/jimi_audit/eth_15m_merged.csv"
SIGNALS_FILE = "/root/.openclaw/workspace/jimi_audit/data/strategy_signals.jsonl"

# =====================================================================
# LOAD FULL PRICE DATA
# =====================================================================
print("Loading full ETH price data + ATR...")
prices_full = []
with open(ETH_CSV) as f:
    header = f.readline()
    for line in f:
        parts = line.strip().split(",")
        ts_str = parts[0]
        prices_full.append({
            "ts": ts_str, "o": float(parts[1]), "h": float(parts[2]),
            "l": float(parts[3]), "c": float(parts[4]),
        })

# ATR(14)
for i in range(len(prices_full)):
    if i < 14:
        prices_full[i]["atr"] = abs(prices_full[i]["h"] - prices_full[i]["l"])
    else:
        trs = []
        for j in range(i-13, i+1):
            h, l = prices_full[j]["h"], prices_full[j]["l"]
            pc = prices_full[j-1]["c"] if j > 0 else prices_full[j]["o"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        prices_full[i]["atr"] = sum(trs) / len(trs)

print(f"  {len(prices_full)} bars: {prices_full[0]['ts']} -> {prices_full[-1]['ts']}")

# =====================================================================
# LOAD ALL SIGNALS
# =====================================================================
print("Loading signals...")
signals_all = []
count = 0
with open(SIGNALS_FILE) as f:
    for line in f:
        count += 1
        if count > 10000000: break
        try:
            d = json.loads(line)
            if d.get("fired") and d.get("direction") and d.get("conviction", 0) > 0:
                signals_all.append(d)
        except: continue

# Dedup
seen = set(); unique = []
for s in signals_all:
    key = (s["strategy"], s["timestamp"])
    if key not in seen:
        seen.add(key); unique.append(s)
signals_all = sorted(unique, key=lambda x: x["timestamp"])
print(f"  {len(signals_all)} unique signals total")

# =====================================================================
# HELPERS
# =====================================================================
def price_at(ts_str, prices):
    prefix = ts_str[:16]
    for p in prices:
        if p["ts"][:16] == prefix:
            return p
    return None

def find_bar_idx(ts_str, timeline):
    prefix = ts_str[:16]
    for i, t in enumerate(timeline):
        if t[:16] == prefix: return i
    return None

def slice_prices(start, end, prices):
    return [p for p in prices if p["ts"] >= start and p["ts"] < end]

def slice_signals(start, end, signals):
    return [s for s in signals if s["timestamp"] >= start and s["timestamp"] < end]

# =====================================================================
# OPTIMIZED CONFIGS (from fee-adjusted backtest)
# =====================================================================
STRATEGY_CONFIGS = {
    "trade_flow": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_h": 12, "dir": "LONG"},
    "funding_arb": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_h": 12, "dir": None},
    "orderbook_imbalance": {"tp_pct": 2.0, "sl_pct": 1.5, "hold_h": 12, "dir": "LONG"},
    "failed_breakout": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_h": 12, "dir": "LONG"},
    "cross_asset": {"tp_pct": 1.0, "sl_pct": 1.5, "hold_h": 4, "dir": None},
    "structural_break": {"tp_pct": 0.5, "sl_pct": 0.5, "hold_h": 8, "dir": "SHORT"},
    "mtf_confluence": {"tp_pct": 2.0, "sl_pct": 3.0, "hold_h": 8, "dir": None},
    "regime_switch": {"tp_pct": 2.0, "sl_pct": 3.0, "hold_h": 12, "dir": None},
    "scalp_v2": {"tp_pct": 2.0, "sl_pct": 2.0, "hold_h": 12, "dir": "LONG"},
}

FEE_PCT = 0.001  # 0.10% round trip

def check_outcome(sig, hold_bars, tp_pct, sl_pct, prices_slice, timeline):
    idx = find_bar_idx(sig["timestamp"], timeline)
    if idx is None: return None, 0

    entry = sig.get("entry", sig.get("price", 0))
    if not entry: return None, 0
    direction = sig["direction"]

    if direction == "LONG":
        tp = entry * (1 + tp_pct/100)
        sl = entry * (1 - sl_pct/100)
    else:
        tp = entry * (1 - tp_pct/100)
        sl = entry * (1 + sl_pct/100)

    end_idx = min(idx + hold_bars, len(timeline))
    for j in range(idx + 1, end_idx):
        bar = prices_slice[j] if j < len(prices_slice) else None
        if not bar: break
        h, l = bar["h"], bar["l"]
        if direction == "LONG":
            if h >= tp: return "WIN", (tp - entry) / entry
            if l <= sl: return "LOSS", (sl - entry) / entry
        else:
            if l <= tp: return "WIN", (entry - tp) / entry
            if h >= sl: return "LOSS", (entry - sl) / entry

    if end_idx > idx and end_idx <= len(prices_slice):
        exit_price = prices_slice[end_idx - 1]["c"]
        pnl = (exit_price - entry) / entry if direction == "LONG" else (entry - exit_price) / entry
        return "TIMEOUT", pnl
    return None, 0

def simulate(signals_slice, prices_slice, strategy_configs, fee_pct):
    cap = 200
    peak = cap; max_dd = 0
    wins = 0; losses = 0; timeouts = 0; total = 0
    timeline = [p["ts"] for p in prices_slice]

    for sig in signals_slice:
        strat = sig["strategy"]
        cfg = strategy_configs.get(strat)
        if not cfg: continue
        if cfg["dir"] and sig["direction"] != cfg["dir"]: continue

        hold_bars = cfg["hold_h"] * 4
        outcome, pnl_pct = check_outcome(sig, hold_bars, cfg["tp_pct"], cfg["sl_pct"], prices_slice, timeline)
        if not outcome: continue
        total += 1

        entry = sig.get("entry", sig.get("price", 0))
        sl_dist = cfg["sl_pct"] / 100
        if sl_dist > 0:
            gross_pnl = cap * 0.02 * (pnl_pct / sl_dist)
        else:
            gross_pnl = 0

        position_size = cap * 0.02 * 10  # 2% risk, 10x leverage
        fee = position_size * fee_pct
        net_pnl = gross_pnl - fee
        cap += net_pnl

        if outcome == "WIN": wins += 1
        elif outcome == "LOSS": losses += 1
        else: timeouts += 1

        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
        if cap <= 0: cap = 0; break

    pf = wins / losses if losses > 0 else (999 if wins > 0 else 0)
    wr = wins / total * 100 if total > 0 else 0
    return {"cap": cap, "dd": max_dd, "total": total, "wins": wins, "losses": losses,
            "timeouts": timeouts, "pf": pf, "wr": wr}

# =====================================================================
# WALK-FORWARD TESTS
# =====================================================================
TRAIN_START = "2021-01-01"
TRAIN_END = "2024-07-01"
TEST_START = "2024-07-01"
TEST_END = "2026-07-05"

train_prices = slice_prices(TRAIN_START, TRAIN_END, prices_full)
test_prices = slice_prices(TEST_START, TEST_END, prices_full)
train_signals = slice_signals(TRAIN_START, TRAIN_END, signals_all)
test_signals = slice_signals(TEST_START, TEST_END, signals_all)

print(f"\n  Train: {len(train_prices)} bars, {len(train_signals)} signals")
print(f"  Test:  {len(test_prices)} bars, {len(test_signals)} signals")

# =====================================================================
# TEST 1: IN-SAMPLE vs OUT-OF-SAMPLE
# =====================================================================
print(f"\n{'='*110}")
print("TEST 1: WALK-FORWARD (Train 2021-2024 vs Test 2024-2026)")
print(f"{'='*110}")

print(f"\n  {'Strategy':<25} {'Period':<12} {'Trades':>7} {'WR%':>7} {'PF':>7} {'DD%':>7} {'Final$':>10} {'NetRet%':>8}")
print(f"  {'-'*100}")

train_results = {}
test_results = {}

for strat_name, cfg in STRATEGY_CONFIGS.items():
    # Train
    strat_train = [s for s in train_signals if s["strategy"] == strat_name]
    if cfg["dir"]:
        strat_train = [s for s in strat_train if s["direction"] == cfg["dir"]]
    if len(strat_train) >= 20:
        r = simulate(strat_train, train_prices, STRATEGY_CONFIGS, FEE_PCT)
        train_results[strat_name] = r
        print(f"  {strat_name:<25} {'TRAIN':<12} {r['total']:>7} {r['wr']:>6.1f}% {r['pf']:>6.2f} {r['dd']:>6.1f}% ${r['cap']:>9,.0f} {(r['cap']-200)/200*100:>7.0f}%")

    # Test
    strat_test = [s for s in test_signals if s["strategy"] == strat_name]
    if cfg["dir"]:
        strat_test = [s for s in strat_test if s["direction"] == cfg["dir"]]
    if len(strat_test) >= 20:
        r = simulate(strat_test, test_prices, STRATEGY_CONFIGS, FEE_PCT)
        test_results[strat_name] = r
        marker = " PF>=2.0" if r["pf"] >= 2.0 else ""
        print(f"  {strat_name:<25} {'TEST':<12} {r['total']:>7} {r['wr']:>6.1f}% {r['pf']:>6.2f} {r['dd']:>6.1f}% ${r['cap']:>9,.0f} {(r['cap']-200)/200*100:>7.0f}%{marker}")

    # Degradation
    if strat_name in train_results and strat_name in test_results:
        tr = train_results[strat_name]
        te = test_results[strat_name]
        pf_chg = te["pf"] - tr["pf"]
        wr_chg = te["wr"] - tr["wr"]
        status = "OK" if te["pf"] >= 2.0 else "DEGRADED" if te["pf"] >= 1.5 else "FAILED"
        print(f"  {'':25} {'DELTA':<12} {'':>7} {wr_chg:>+6.1f}% {pf_chg:>+6.2f} {'':>7} {'':>10} {status:>8}")
        print(f"  {'-'*100}")

# =====================================================================
# TEST 2: ROLLING 12-MONTH WINDOWS
# =====================================================================
print(f"\n{'='*110}")
print("TEST 2: ROLLING 12-MONTH WINDOWS (combined all strategies)")
print(f"{'='*110}")
print(f"\n  {'Window':<25} {'Trades':>7} {'WR%':>7} {'PF':>7} {'DD%':>7} {'Final$':>10} {'NetRet%':>8}")
print(f"  {'-'*80}")

# Generate 12-month rolling windows
from datetime import datetime, timedelta
start_dt = datetime(2021, 1, 1)
end_dt = datetime(2026, 7, 1)
window_months = 12

current = start_dt
while current + timedelta(days=365) <= end_dt:
    w_start = current.strftime("%Y-%m-%d")
    w_end = (current + timedelta(days=365)).strftime("%Y-%m-%d")

    w_prices = slice_prices(w_start, w_end, prices_full)
    w_signals = slice_signals(w_start, w_end, signals_all)

    if len(w_signals) >= 30:
        r = simulate(w_signals, w_prices, STRATEGY_CONFIGS, FEE_PCT)
        marker = " GOOD" if r["pf"] >= 2.0 else " OK" if r["pf"] >= 1.5 else " BAD"
        print(f"  {w_start}->{w_end} {r['total']:>7} {r['wr']:>6.1f}% {r['pf']:>6.2f} {r['dd']:>6.1f}% ${r['cap']:>9,.0f} {(r['cap']-200)/200*100:>7.0f}%{marker}")

    current += timedelta(days=90)  # quarterly steps

# =====================================================================
# TEST 3: PER-STRATEGY OUT-OF-SAMPLE DEEP DIVE
# =====================================================================
print(f"\n{'='*110}")
print("TEST 3: PER-STRATEGY TEST PERIOD DEEP DIVE")
print(f"{'='*110}")
print(f"\n  {'Strategy':<25} {'Dir':>6} {'Trades':>7} {'WR%':>7} {'PF':>7} {'Wins':>6} {'Loss':>6} {'TO':>6} {'DD%':>7}")
print(f"  {'-'*90}")

for strat_name, cfg in STRATEGY_CONFIGS.items():
    strat_test = [s for s in test_signals if s["strategy"] == strat_name]
    if cfg["dir"]:
        strat_test = [s for s in strat_test if s["direction"] == cfg["dir"]]
    if len(strat_test) < 10: continue

    r = simulate(strat_test, test_prices, STRATEGY_CONFIGS, FEE_PCT)
    dir_label = cfg["dir"] or "ALL"
    marker = " PF>=2.0" if r["pf"] >= 2.0 else ""
    print(f"  {strat_name:<25} {dir_label:>6} {r['total']:>7} {r['wr']:>6.1f}% {r['pf']:>6.2f} {r['wins']:>6} {r['losses']:>6} {r['timeouts']:>6} {r['dd']:>6.1f}%{marker}")

# =====================================================================
# TEST 4: COMBINED PORTFOLIO (all strategies together)
# =====================================================================
print(f"\n{'='*110}")
print("TEST 4: COMBINED PORTFOLIO PERFORMANCE")
print(f"{'='*110}")

# Combined test
r_combined = simulate(test_signals, test_prices, STRATEGY_CONFIGS, FEE_PCT)
print(f"\n  Test Period (2024-07 to 2026-07):")
print(f"    Trades: {r_combined['total']}")
print(f"    WR: {r_combined['wr']:.1f}%")
print(f"    PF: {r_combined['pf']:.2f}")
print(f"    Max DD: {r_combined['dd']:.1f}%")
print(f"    Final: ${r_combined['cap']:,.0f}")
print(f"    Net Return: {(r_combined['cap']-200)/200*100:.0f}%")
print(f"    Wins: {r_combined['wins']} | Losses: {r_combined['losses']} | Timeouts: {r_combined['timeouts']}")

# Combined train for comparison
r_train_combined = simulate(train_signals, train_prices, STRATEGY_CONFIGS, FEE_PCT)
print(f"\n  Train Period (2021-01 to 2024-07):")
print(f"    Trades: {r_train_combined['total']}")
print(f"    WR: {r_train_combined['wr']:.1f}%")
print(f"    PF: {r_train_combined['pf']:.2f}")
print(f"    Final: ${r_train_combined['cap']:,.0f}")

# =====================================================================
# VERDICT
# =====================================================================
print(f"\n{'='*110}")
print("WALK-FORWARD VERDICT")
print(f"{'='*110}")

pf_train = r_train_combined["pf"]
pf_test = r_combined["pf"]
degradation = pf_test - pf_train

print(f"""
  IN-SAMPLE (2021-2024):
    WR={r_train_combined['wr']:.1f}% | PF={pf_train:.2f} | DD={r_train_combined['dd']:.1f}% | Final=${r_train_combined['cap']:,.0f}
    Trades: {r_train_combined['total']}

  OUT-OF-SAMPLE (2024-2026):
    WR={r_combined['wr']:.1f}% | PF={pf_test:.2f} | DD={r_combined['dd']:.1f}% | Final=${r_combined['cap']:,.0f}
    Trades: {r_combined['total']}

  Degradation:
    PF: {pf_train:.2f} -> {pf_test:.2f} ({degradation:+.2f})
    WR: {r_train_combined['wr']:.1f}% -> {r_combined['wr']:.1f}% ({r_combined['wr']-r_train_combined['wr']:+.1f}%)

  {"PASS: Scanner strategies perform similarly out-of-sample. Deploy with confidence." if pf_test >= 2.0 else "MARGINAL: PF dropped below 2.0 out-of-sample. Reduce position size." if pf_test >= 1.5 else "FAIL: Significant degradation. Do not deploy these configs."}
""")

# Per-strategy verdict
print("  Per-Strategy Verdict:")
for strat_name in STRATEGY_CONFIGS:
    if strat_name in train_results and strat_name in test_results:
        tr = train_results[strat_name]
        te = test_results[strat_name]
        status = "PASS" if te["pf"] >= 2.0 else "MARGINAL" if te["pf"] >= 1.5 else "FAIL"
        print(f"    {strat_name:<25} PF: {tr['pf']:.2f} -> {te['pf']:.2f} ({te['pf']-tr['pf']:+.2f}) {status}")

elapsed = time.time() - t0
print(f"\n  Completed in {elapsed:.1f}s")
