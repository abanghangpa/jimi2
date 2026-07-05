#!/usr/bin/env python3
"""
Outcome Tracker — matches strategy signals against actual price moves.
Usage:
  python3 scripts/outcome_tracker.py
  python3 scripts/outcome_tracker.py --strategy structural_break
  python3 scripts/outcome_tracker.py --hold-window 8 --since 2026-06-27
"""

import json, os, sys, argparse, glob
from datetime import datetime, timedelta, timezone
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SIGNALS_FILE = os.path.join(DATA_DIR, "strategy_signals.jsonl")
SCANS_DIR = os.path.join(DATA_DIR, "scans")

DEFAULT_HOLD_WINDOWS = {
    "main_pipeline": 2, "failed_breakout": 8, "funding_arb": 4,
    "orderbook_imbalance": 2, "trade_flow": 2, "cross_asset": 4,
    "mtf_confluence": 4, "structural_break": 8, "scalp_v2": 1,
    "momentum_v2": 4, "squeeze_breakout": 4, "positioning_fade": 2,
    "kill_zone": 4, "liquidity_grab": 4, "taker_flow": 2,
    "regime_switch": 4, "power_of_3": 4, "cascade": 4,
    "macro_surprise": 8, "whale_watch": 4, "vol_rotation": 4,
    "liquidation_cascade": 4, "judas_sweep": 4,
}


def load_signals(strategy_filter=None, since_date=None):
    signals = []
    if not os.path.exists(SIGNALS_FILE):
        print(f"Signal file not found: {SIGNALS_FILE}")
        return signals
    with open(SIGNALS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: d = json.loads(line)
            except: continue
            if not d.get("fired"): continue
            if strategy_filter and d.get("strategy") != strategy_filter: continue
            if since_date:
                ts = str(d.get("timestamp", ""))
                if ts[:10] < since_date: continue
            signals.append(d)
    return signals


def load_price_data():
    prices = []
    for f in sorted(glob.glob(os.path.join(SCANS_DIR, "*.json"))):
        try:
            with open(f) as fh: data = json.load(fh)
            ts = str(data.get("timestamp", ""))
            price = data.get("price")
            if isinstance(price, (int, float)) and ts:
                prices.append({"timestamp": ts, "price": float(price)})
        except: continue
    return prices


def evaluate_signal(signal, price_data, hold_hours=None):
    strategy = signal.get("strategy", "unknown")
    direction = signal.get("direction", "")
    entry_price = signal.get("entry", signal.get("price", 0))
    sl = signal.get("sl", 0)
    tp1 = signal.get("tp1", 0)
    signal_ts = str(signal.get("timestamp", ""))
    if not entry_price or not direction: return None
    if hold_hours is None:
        hold_hours = DEFAULT_HOLD_WINDOWS.get(strategy, 2)
    try:
        signal_dt = datetime.fromisoformat(signal_ts.replace("Z", "+00:00"))
    except:
        try: signal_dt = datetime.strptime(signal_ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except: return None
    exit_dt = signal_dt + timedelta(hours=hold_hours)
    window_prices = []
    for p in price_data:
        try:
            p_dt = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
        except:
            try: p_dt = datetime.strptime(p["timestamp"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except: continue
        if signal_dt <= p_dt <= exit_dt:
            window_prices.append(p["price"])
    if not window_prices: return None
    if direction == "LONG":
        max_p, min_p, exit_p = max(window_prices), min(window_prices), window_prices[-1]
        pnl = (exit_p - entry_price) / entry_price * 100
        mfe = (max_p - entry_price) / entry_price * 100
        mae = (entry_price - min_p) / entry_price * 100
        hit_tp1 = max_p >= tp1 if tp1 > 0 else False
        hit_sl = min_p <= sl if sl > 0 else False
    elif direction == "SHORT":
        max_p, min_p, exit_p = max(window_prices), min(window_prices), window_prices[-1]
        pnl = (entry_price - exit_p) / entry_price * 100
        mfe = (entry_price - min_p) / entry_price * 100
        mae = (max_p - entry_price) / entry_price * 100
        hit_tp1 = min_p <= tp1 if tp1 > 0 else False
        hit_sl = max_p >= sl if sl > 0 else False
    else: return None
    if hit_tp1 and not hit_sl: outcome = "WIN"
    elif hit_sl and not hit_tp1: outcome = "LOSS"
    elif pnl > 0: outcome = "WIN"
    elif pnl < 0: outcome = "LOSS"
    else: outcome = "BREAKEVEN"
    return {"strategy": strategy, "direction": direction, "entry": entry_price,
            "exit": exit_p, "sl": sl, "tp1": tp1, "hold_hours": hold_hours,
            "pnl_pct": round(pnl, 4), "max_favorable": round(mfe, 4),
            "max_adverse": round(mae, 4), "hit_tp1": hit_tp1, "hit_sl": hit_sl,
            "outcome": outcome, "signal_time": signal_ts, "bars": len(window_prices)}


def print_summary(results, group_by="strategy"):
    groups = defaultdict(list)
    for r in results: groups[r[group_by]].append(r)
    print(f"\n{'='*80}")
    print(f"  OUTCOME TRACKER RESULTS")
    print(f"{'='*80}")
    for key in sorted(groups.keys()):
        items = groups[key]
        wins = sum(1 for i in items if i["outcome"] == "WIN")
        losses = sum(1 for i in items if i["outcome"] == "LOSS")
        be = sum(1 for i in items if i["outcome"] == "BREAKEVEN")
        n = len(items)
        if n == 0: continue
        wr = wins / n * 100
        avg_pnl = sum(i["pnl_pct"] for i in items) / n
        avg_win = sum(i["pnl_pct"] for i in items if i["outcome"] == "WIN") / wins if wins else 0
        avg_loss = sum(i["pnl_pct"] for i in items if i["outcome"] == "LOSS") / losses if losses else 0
        longs = [i for i in items if i["direction"] == "LONG"]
        shorts = [i for i in items if i["direction"] == "SHORT"]
        lwr = sum(1 for i in longs if i["outcome"] == "WIN") / len(longs) * 100 if longs else 0
        swr = sum(1 for i in shorts if i["outcome"] == "WIN") / len(shorts) * 100 if shorts else 0
        print(f"\n  {key} (n={n}, hold={items[0]["hold_hours"]}h)")
        print(f"  {chr(8212)*60}")
        print(f"    Win Rate:    {wr:.1f}% ({wins}W / {losses}L / {be}BE)")
        print(f"    LONG WR:     {lwr:.1f}% (n={len(longs)})")
        print(f"    SHORT WR:    {swr:.1f}% (n={len(shorts)})")
        print(f"    Avg PnL:     {avg_pnl:+.3f}%")
        print(f"    Avg Win:     {avg_win:+.3f}%")
        print(f"    Avg Loss:    {avg_loss:+.3f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", "-s")
    parser.add_argument("--hold-window", "-w", type=int)
    parser.add_argument("--since")
    parser.add_argument("--group-by", default="strategy", choices=["strategy", "direction", "all"])
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    print("Loading signals...")
    signals = load_signals(strategy_filter=args.strategy, since_date=args.since)
    print(f"Found {len(signals)} fired signals")
    if not signals: return
    print("Loading price data...")
    prices = load_price_data()
    print(f"Found {len(prices)} price data points")
    if not prices: return
    print("Evaluating outcomes...")
    results = []
    for sig in signals:
        r = evaluate_signal(sig, prices, hold_hours=args.hold_window)
        if r: results.append(r)
    print(f"Evaluated {len(results)} signals ({len(signals)-len(results)} skipped)")
    if args.verbose:
        for r in results:
            icon = "W" if r["outcome"] == "WIN" else "L" if r["outcome"] == "LOSS" else "B"
            print(f"  [{icon}] {r["strategy"]:20s} {r["direction"]:5s} @ ${r["entry"]:.2f} -> ${r["exit"]:.2f} ({r["pnl_pct"]:+.2f}%)")
    print_summary(results, group_by=args.group_by)

if __name__ == "__main__": main()
