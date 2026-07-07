#!/usr/bin/env python3
"""
WhatsApp Status Reporter — EVENT-ONLY mode.
Only sends a message when a position opens or closes.
Silent otherwise.
"""
import json, os
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
    """Standard JIMI LIVE TRADER report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    capital = state.get("capital", 0)
    peak = state.get("peak_capital", capital)
    dd_pct = ((peak - capital) / peak * 100) if peak > 0 else 0
    ret = (capital - 200) / 200 * 100
    t = state.get("trades_count", 0)
    w = state.get("wins", 0)
    wr = (w / t * 100) if t > 0 else 0

    msg = "JIMI LIVE TRADER\n"
    msg += f"Time: {now}\n"
    msg += "Strategy: BB Mean Rev + mom6\n"
    msg += f"Capital: ${capital:,.2f} ({ret:+.1f}%) | Peak: ${peak:,.2f} | DD: {dd_pct:.1f}%\n"
    msg += f"P&L: ${state.get('total_pnl', 0):+,.4f} | Fees: ${state.get('total_fees', 0):.4f}\n"
    msg += f"Total Withdrawn: ${state.get('total_withdrawn', 0):,.0f}\n"
    msg += f"Trades: {t} ({w}W/{t-w}L) WR {wr:.0f}% | DD triggers: {state.get('dd_triggered_count', 0)}\n"
    msg += f"Vol Gate Skips: {state.get('vol_gate_skips', 0)}\n"

    positions = state.get("positions", [])
    if positions:
        for pos in positions:
            d = pos.get("direction", "?")
            entry = pos.get("entry", 0)
            tp = pos.get("tp", 0)
            sl = pos.get("sl", 0)
            reason = pos.get("reason", "")
            msg += f"\nOPEN: {d} ETH @ ${entry:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}\n"
            if reason:
                msg += f"Reason: {reason}\n"
    else:
        msg += "\nNo open positions."

    return msg

def main():
    state = load_json(STATE_FILE)
    if not state:
        return  # No state, no message

    prev = load_json(MONITOR_STATE) or {
        "trades_count": 0, "positions_count": 0,
        "seen_trade_ids": [], "seen_position_ids": []
    }

    has_event = False

    # Check: New positions opened
    for pos in state.get("positions", []):
        if pos["id"] not in prev.get("seen_position_ids", []):
            has_event = True
            break

    # Check: Trades closed
    if not has_event:
        closed_trades = state.get("closed_trades", [])
        seen_ids = set(prev.get("seen_trade_ids", []))
        for trade in closed_trades:
            tid = f"{trade.get('id','')}_{trade.get('closed_at','')}"
            if tid not in seen_ids:
                has_event = True
                break

    # Update monitor state (always, to track what we've seen)
    prev["trades_count"] = state.get("trades_count", 0)
    prev["positions_count"] = len(state.get("positions", []))
    prev["seen_position_ids"] = [p["id"] for p in state.get("positions", [])]
    closed_ids = set()
    for trade in state.get("closed_trades", []):
        closed_ids.add(f"{trade.get('id','')}_{trade.get('closed_at','')}")
    prev["seen_trade_ids"] = list(closed_ids)
    save_json(MONITOR_STATE, prev)

    # Only output if there was an event
    if has_event:
        print(format_report(state))
    # else: output nothing = no WhatsApp message

if __name__ == "__main__":
    main()
