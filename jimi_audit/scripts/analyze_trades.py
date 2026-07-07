#!/usr/bin/env python3
import json
from collections import defaultdict

with open("/root/.openclaw/workspace/jimi_audit/data/backtest_trades.json") as f:
    trades = json.load(f)

print(f"Total trades: {len(trades)}")

strats = defaultdict(lambda: {"trades": [], "wins": 0, "losses": 0, "pnl": 0, 
    "directions": defaultdict(int), "hours": defaultdict(int), "dates": defaultdict(int)})

for t in trades:
    s = t.get("sn", "unknown")
    strats[s]["trades"].append(t)
    strats[s]["pnl"] += t.get("pnl", 0)
    if t.get("o") == "WIN":
        strats[s]["wins"] += 1
    else:
        strats[s]["losses"] += 1
    strats[s]["directions"][t.get("d", "?")] += 1
    ts = t.get("ts", "")
    if len(ts) >= 13:
        try:
            hour = int(ts[11:13])
            strats[s]["hours"][hour] += 1
        except: pass
    if len(ts) >= 10:
        strats[s]["dates"][ts[:10]] += 1

for s, v in sorted(strats.items(), key=lambda x: x[1]["pnl"]):
    n = len(v["trades"])
    w = v["wins"]
    l = v["losses"]
    wr = w/n*100 if n > 0 else 0
    pnl = v["pnl"]
    
    print(f"\n{'='*60}")
    print(f"STRATEGY: {s}")
    print(f"{'='*60}")
    print(f"Trades: {n} | W: {w} | L: {l} | WR: {wr:.1f}% | PnL: ${pnl:.2f}")
    print(f"Directions: {dict(v['directions'])}")
    
    if v["hours"]:
        peak = sorted(v["hours"].items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"Peak hours (UTC): {peak}")
    
    if v["dates"]:
        print(f"Active dates: {len(v['dates'])} days")
        for d in sorted(v["dates"])[:5]:
            print(f"  {d}: {v['dates'][d]} trades")
    
    max_loss_streak = 0
    cur = 0
    for t in v["trades"]:
        if t.get("o") == "LOSS":
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0
    print(f"Max consecutive losses: {max_loss_streak}")
    
    wins = [t for t in v["trades"] if t.get("o") == "WIN"]
    losses = [t for t in v["trades"] if t.get("o") == "LOSS"]
    avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0
    print(f"Avg win: ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}")
    if avg_loss != 0:
        print(f"Actual R:R: {abs(avg_win/avg_loss):.2f}x")
    
    timeout_losses = [t for t in losses if t.get("bh", 0) >= 24]
    sl_losses = [t for t in losses if t.get("bh", 0) < 24]
    print(f"Timeout losses: {len(timeout_losses)} | SL losses: {len(sl_losses)}")
    
    if losses:
        print(f"Sample losses:")
        for t in losses[:5]:
            d = t.get("d", "?")
            entry = t.get("e", 0)
            exit_p = t.get("x", 0)
            pnl = t.get("pnl", 0)
            bh = t.get("bh", 0)
            ts = t.get("ts", "")[:16]
            pct = (exit_p - entry) / entry * 100 if d == "LONG" else (entry - exit_p) / entry * 100
            print(f"  {ts} {d} entry={entry} exit={exit_p} ({pct:+.2f}%) pnl=${pnl:.2f} bars={bh}")
