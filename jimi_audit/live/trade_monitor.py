#!/usr/bin/env python3
"""
JIMI Trade Monitor — Notifications ONLY on position open/close events.
No spam. No periodic summaries. Just real events.
"""
import json, os, sys
from datetime import datetime, timezone

BASE = "/root/.openclaw/workspace/jimi_audit"
STATE_FILE = os.path.join(BASE, "live", "data", "state.json")
MONITOR_STATE = os.path.join(BASE, "live", "data", "monitor_state.json")

def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def format_report(state):
    """Format the standard JIMI LIVE TRADER report."""
    now = datetime.now(timezone.utc)
    cap = state.get("capital", 200)
    peak = state.get("peak_capital", 200)
    dd = ((peak - cap) / peak * 100) if peak > 0 else 0
    ret = (cap - 200) / 200 * 100
    pnl = state.get("total_pnl", 0)
    fees = state.get("total_fees", 0)
    withdrawn = state.get("total_withdrawn", 0)
    trades = state.get("trades_count", 0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    wr = (wins / trades * 100) if trades > 0 else 0
    dd_triggers = state.get("dd_triggered_count", 0)
    vol_skips = state.get("vol_gate_skips", 0)
    positions = state.get("positions", [])

    lines = [
        "JIMI LIVE TRADER",
        f"Time: {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "Strategy: BB Mean Rev + mom6",
        f"Capital: ${cap:,.2f} ({ret:+.1f}%) | Peak: ${peak:,.2f} | DD: {dd:.1f}%",
        f"P&L: ${pnl:+,.4f} | Fees: ${fees:,.4f}",
        f"Total Withdrawn: ${withdrawn:,.0f}",
        f"Trades: {trades} ({wins}W/{losses}L) WR {wr:.0f}% | DD triggers: {dd_triggers}",
        f"Vol Gate Skips: {vol_skips}",
    ]

    if positions:
        for pos in positions:
            d = pos.get("direction", "?")
            entry = pos.get("entry", 0)
            tp = pos.get("tp", 0)
            sl = pos.get("sl", 0)
            reason = pos.get("reason", "")
            lines.append(f"\nOPEN: {d} ETH @ ${entry:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}")
            if reason:
                lines.append(f"Reason: {reason}")
    else:
        lines.append("\nNo open positions.")

    return "\n".join(lines)

def main():
    state = load_json(STATE_FILE)
    if not state:
        print("NO_STATE")
        return

    prev = load_json(MONITOR_STATE) or {
        "trades_count": 0, "positions_count": 0,
        "seen_trade_ids": [], "seen_position_ids": []
    }

    events = []

    # Check: New positions opened
    for pos in state.get("positions", []):
        if pos["id"] not in prev.get("seen_position_ids", []):
            events.append({"type": "OPEN", "msg": format_report(state)})

    # Check: Trades closed
    closed_trades = state.get("closed_trades", [])
    seen_ids = set(prev.get("seen_trade_ids", []))
    for trade in closed_trades:
        tid = f"{trade.get('id','')}_{trade.get('closed_at','')}"
        if tid not in seen_ids:
            events.append({"type": "CLOSE", "msg": format_report(state)})
            seen_ids.add(tid)

    # Update monitor state
    prev["trades_count"] = state.get("trades_count", 0)
    prev["positions_count"] = len(state.get("positions", []))
    prev["seen_position_ids"] = [p["id"] for p in state.get("positions", [])]
    prev["seen_trade_ids"] = list(seen_ids)
    save_json(MONITOR_STATE, prev)

    # Output events
    if events:
        for ev in events:
            print(ev["msg"])
    else:
        print("NO_EVENT")

if __name__ == "__main__":
    main()
