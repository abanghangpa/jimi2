#!/usr/bin/env python3
"""
Strategy Analysis - ONE strategy at a time.
Usage: python3 analyze_single_strategy.py <strategy_name>
Reads existing scan files first, then backtests missing period in batches.
"""
import sys, os, json, time, glob
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "failed_breakout"

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data
from scripts.scanner import scan_signal, compute_indicators

SCAN_DIR = "data/scans"
OUTPUT_FILE = f"data/analysis_{STRATEGY}.json"
START_DATE = "2026-02-02"
END_DATE = "2026-07-05"
BATCH_SIZE = 50  # bars per batch
PAUSE_SEC = 2    # pause between batches

ALL_STRATEGIES = {
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

sconfig = ALL_STRATEGIES.get(STRATEGY)
if not sconfig:
    print(f"Unknown strategy: {STRATEGY}")
    sys.exit(1)

print(f"=== Analyzing: {STRATEGY} ===")
print(f"Config: TP={sconfig['tp_pct']}% SL={sconfig['sl_pct']}% Hold={sconfig['hold_hours']}h MinConv={sconfig['min_conv']} Dir={sconfig['direction']}")

# --- Phase 1: Extract from existing scan files (Jun 7 - Jul 5) ---
print("\nPhase 1: Reading existing scan files...")
scan_files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
phase1_trades = []
phase1_signals = 0

for sf in scan_files:
    try:
        with open(sf) as f:
            data = json.load(f)
    except:
        continue
    
    ts = data.get("timestamp", "")
    price = data.get("price", 0)
    multi = data.get("multi_strategy") or {}
    all_sigs = multi.get("all_signals", [])
    
    for sig in all_sigs:
        if not isinstance(sig, dict):
            continue
        if sig.get("strategy") != STRATEGY:
            continue
        
        direction = sig.get("direction")
        conviction = sig.get("conviction", 0) or 0
        
        if not direction or conviction < sconfig["min_conv"]:
            continue
        if sconfig["direction"] and direction != sconfig["direction"]:
            continue
        
        phase1_signals += 1
        entry = sig.get("entry", price)
        sl = sig.get("sl", 0)
        tp1 = sig.get("tp1", 0)
        
        if not entry or not sl or not tp1:
            continue
        
        phase1_trades.append({
            "ts": ts, "direction": direction,
            "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp1, 2),
            "conviction": round(conviction, 4), "price": round(price, 2),
            "source": "scan_file",
        })

print(f"  Found {phase1_signals} signals from {len(scan_files)} scan files")
print(f"  Tradable: {len(phase1_trades)}")

# --- Phase 2: Backtest Feb 2 - Jun 7 in batches ---
print("\nPhase 2: Backtesting Feb 2 - Jun 7 (batched)...")

df_raw = load_data("eth_15m_merged.csv")
df_raw['Open time'] = pd.to_datetime(df_raw['Open time'])
cfg = CONFIG

print("  Computing indicators...")
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_raw.copy(), config=cfg)

mask = (df_15m['Open time'] >= START_DATE) & (df_15m['Open time'] < "2026-06-07")
indices = df_15m[mask].index.tolist()
start_idx = max(indices[0], 500) if indices else 500
end_idx = indices[-1] if indices else len(df_15m) - 1
step = 4  # every 1h

print(f"  Bars: {start_idx} to {end_idx} (step={step})")
total_bars = (end_idx - start_idx) // step
print(f"  Total iterations: ~{total_bars}")

phase2_trades = []
phase2_signals = 0
batches_done = 0
t0 = time.time()

for batch_start in range(start_idx, end_idx + 1, BATCH_SIZE * step):
    batch_end = min(batch_start + BATCH_SIZE * step, end_idx + 1)
    
    for i in range(batch_start, batch_end, step):
        try:
            result = scan_signal(df_15m.iloc[:i+1], df_1h, df_2h, df_4h, df_1d, config=cfg)
        except:
            continue
        
        multi = result.get("multi_strategy") or {}
        all_sigs = multi.get("all_signals", [])
        price = float(df_15m.iloc[i]["Close"])
        ts = df_15m.iloc[i]["Open time"]
        
        for sig in all_sigs:
            if not isinstance(sig, dict):
                continue
            if sig.get("strategy") != STRATEGY:
                continue
            
            direction = sig.get("direction")
            conviction = sig.get("conviction", 0) or 0
            
            if not direction or conviction < sconfig["min_conv"]:
                continue
            if sconfig["direction"] and direction != sconfig["direction"]:
                continue
            
            phase2_signals += 1
            entry = sig.get("entry", price)
            sl = sig.get("sl", 0)
            tp1 = sig.get("tp1", 0)
            
            if not entry or not sl or not tp1:
                continue
            
            # Simulate outcome
            hold_bars = sconfig["hold_hours"] * 4
            outcome = "TIMEOUT"
            exit_price = entry
            
            for j in range(1, min(hold_bars + 1, len(df_15m) - i)):
                bar = df_15m.iloc[i + j]
                h = float(bar["High"])
                l = float(bar["Low"])
                
                if direction == "LONG":
                    if h >= tp1:
                        outcome = "WIN"; exit_price = tp1; break
                    if l <= sl:
                        outcome = "LOSS"; exit_price = sl; break
                else:
                    if l <= tp1:
                        outcome = "WIN"; exit_price = tp1; break
                    if h >= sl:
                        outcome = "LOSS"; exit_price = sl; break
            
            if outcome == "TIMEOUT" and i + hold_bars < len(df_15m):
                exit_price = float(df_15m.iloc[i + hold_bars]["Close"])
            
            pnl_pct = ((exit_price - entry) / entry * 100) if direction == "LONG" else ((entry - exit_price) / entry * 100)
            
            phase2_trades.append({
                "ts": str(ts), "direction": direction,
                "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp1, 2),
                "exit": round(exit_price, 2), "outcome": outcome,
                "pnl_pct": round(pnl_pct, 4), "conviction": round(conviction, 4),
                "source": "backtest",
            })
    
    batches_done += 1
    elapsed = time.time() - t0
    pct = (batch_end - start_idx) / (end_idx - start_idx) * 100
    print(f"  Batch {batches_done} | {pct:.0f}% | signals={phase2_signals} | {elapsed:.0f}s | pause...")
    time.sleep(PAUSE_SEC)  # CPU cooldown

# --- Combine & Analyze ---
all_trades = phase1_trades + phase2_trades

# Simulate outcomes for phase1 trades (scan files don't have outcome)
print("\nSimulating outcomes for scan-file trades...")
# We need price data after each signal to check TP/SL
# Load full price data for this
for t in phase1_trades:
    ts_str = t["ts"]
    try:
        sig_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except:
        continue
    
    # Find the bar index
    mask_idx = df_15m['Open time'] >= pd.Timestamp(sig_dt)
    if not mask_idx.any():
        continue
    idx = df_15m[mask_idx].index[0]
    
    direction = t["direction"]
    entry = t["entry"]
    sl = t["sl"]
    tp = t["tp"]
    hold_bars = sconfig["hold_hours"] * 4
    outcome = "TIMEOUT"
    exit_price = entry
    
    for j in range(1, min(hold_bars + 1, len(df_15m) - idx)):
        bar = df_15m.iloc[idx + j]
        h = float(bar["High"])
        l = float(bar["Low"])
        
        if direction == "LONG":
            if h >= tp: outcome = "WIN"; exit_price = tp; break
            if l <= sl: outcome = "LOSS"; exit_price = sl; break
        else:
            if l <= tp: outcome = "WIN"; exit_price = tp; break
            if h >= sl: outcome = "LOSS"; exit_price = sl; break
    
    if outcome == "TIMEOUT" and idx + hold_bars < len(df_15m):
        exit_price = float(df_15m.iloc[idx + hold_bars]["Close"])
    
    pnl_pct = ((exit_price - entry) / entry * 100) if direction == "LONG" else ((entry - exit_price) / entry * 100)
    t["exit"] = round(exit_price, 2)
    t["outcome"] = outcome
    t["pnl_pct"] = round(pnl_pct, 4)

# Final stats
wins = [t for t in all_trades if t["outcome"] == "WIN"]
losses = [t for t in all_trades if t["outcome"] == "LOSS"]
timeouts = [t for t in all_trades if t["outcome"] == "TIMEOUT"]

wr = len(wins) / len(all_trades) * 100 if all_trades else 0
avg_pnl = np.mean([t["pnl_pct"] for t in all_trades]) if all_trades else 0
avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0

# Direction breakdown
long_w = [t for t in wins if t["direction"] == "LONG"]
long_l = [t for t in losses if t["direction"] == "LONG"]
short_w = [t for t in wins if t["direction"] == "SHORT"]
short_l = [t for t in losses if t["direction"] == "SHORT"]

# Monthly
monthly = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pnl": 0})
for t in all_trades:
    m = t["ts"][:7]
    if t["outcome"] == "WIN": monthly[m]["w"] += 1
    elif t["outcome"] == "LOSS": monthly[m]["l"] += 1
    else: monthly[m]["t"] += 1
    monthly[m]["pnl"] += t.get("pnl_pct", 0)

# Consecutive losses
max_consec = 0
curr = 0
for t in all_trades:
    if t["outcome"] == "LOSS":
        curr += 1
        max_consec = max(max_consec, curr)
    else:
        curr = 0

output = {
    "strategy": STRATEGY,
    "config": sconfig,
    "period": f"{START_DATE} to {END_DATE}",
    "total_signals": phase1_signals + phase2_signals,
    "total_trades": len(all_trades),
    "wins": len(wins),
    "losses": len(losses),
    "timeouts": len(timeouts),
    "win_rate": round(wr, 1),
    "avg_pnl_pct": round(avg_pnl, 4),
    "avg_win_pct": round(avg_win, 4),
    "avg_loss_pct": round(avg_loss, 4),
    "max_consec_losses": max_consec,
    "direction_breakdown": {
        "long": {"wins": len(long_w), "losses": len(long_l)},
        "short": {"wins": len(short_w), "losses": len(short_l)},
    },
    "monthly": {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in sorted(monthly.items())},
    "losing_trades": losses[-30:],
    "winning_trades": wins[-15:],
    "all_trades": all_trades,
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2, default=str)

# Print summary
print(f"\n{'=' * 70}")
print(f"  {STRATEGY.upper()} — RESULTS")
print(f"{'=' * 70}")
print(f"  Period: {START_DATE} to {END_DATE}")
print(f"  Signals: {output['total_signals']} | Trades: {output['total_trades']}")
print(f"  W: {len(wins)} | L: {len(losses)} | T: {len(timeouts)}")
print(f"  Win Rate: {wr:.1f}%")
print(f"  Avg PnL: {avg_pnl:.2f}% | Avg Win: {avg_win:.2f}% | Avg Loss: {avg_loss:.2f}%")
print(f"  Max Consec Losses: {max_consec}")
print(f"  LONG: {len(long_w)}W/{len(long_l)}L | SHORT: {len(short_w)}W/{len(short_l)}L")
print(f"\n  Monthly:")
for m, v in sorted(monthly.items()):
    print(f"    {m}: {v['w']}W/{v['l']}L/{v['t']}T | PnL: {v['pnl']:.2f}%")

print(f"\n  Last 10 Losses:")
for t in losses[-10:]:
    print(f"    {t['ts']} | {t['direction']} | entry={t['entry']} sl={t['sl']} tp={t['tp']} exit={t['exit']} | {t['pnl_pct']:.2f}%")

print(f"\n✅ Saved to {OUTPUT_FILE}")
