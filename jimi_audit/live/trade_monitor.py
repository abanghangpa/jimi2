#!/usr/bin/env python3
"""
JIMI Trade Monitor — Checks trader state and sends WhatsApp notifications
Tracks: trade opens, trade closes, daily summary
Run via cron every 2-5 minutes
"""
import json, os, sys
from datetime import datetime, timezone

BASE = "/root/.openclaw/workspace/jimi_audit"
STATE_FILE = os.path.join(BASE, "live", "data", "state.json")
MONITOR_STATE = os.path.join(BASE, "live", "data", "monitor_state.json")
TRADE_LOG = os.path.join(BASE, "live", "data", "trades.json")

def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def main():
    state = load_json(STATE_FILE)
    if not state:
        print("NO_STATE")
        return

    prev = load_json(MONITOR_STATE) or {
        "trades_count": 0, "positions_count": 0, "last_daily": None,
        "seen_trade_ids": [], "seen_position_ids": []
    }

    events = []
    now = datetime.now(timezone.utc)

    # === CHECK: New positions opened ===
    current_pos_ids = [p["id"] for p in state.get("positions", [])]
    for pos in state.get("positions", []):
        if pos["id"] not in prev.get("seen_position_ids", []):
            direction = pos["direction"]
            entry = pos["entry"]
            tp = pos["tp"]
            sl = pos["sl"]
            reason = pos.get("reason", "")
            cap = state["capital"]
            events.append({
                "type": "OPEN",
                "msg": f"🔔 TRADE OPENED\n{direction} ETH @ ${entry:,.2f}\nTP: ${tp:,.2f} | SL: ${sl:,.2f}\nReason: {reason}\nCapital: ${cap:,.2f}"
            })

    # === CHECK: Trades closed ===
    closed_trades = state.get("closed_trades", [])
    seen_ids = set(prev.get("seen_trade_ids", []))
    for trade in closed_trades:
        tid = f"{trade.get('id','')}_{trade.get('closed_at','')}"
        if tid not in seen_ids:
            outcome = trade.get("outcome", "?")
            pnl = trade.get("pnl", 0)
            entry = trade.get("entry", 0)
            exit_p = trade.get("exit", 0)
            direction = trade.get("direction", "?")
            cap = state["capital"]
            emoji = "✅" if outcome == "WIN" else "❌"
            events.append({
                "type": "CLOSE",
                "msg": f"{emoji} TRADE CLOSED\n{direction} ${entry:,.2f} → ${exit_p:,.2f}\nPnL: ${pnl:+,.2f}\nCapital: ${cap:,.2f}\nTrades: {state['trades_count']} ({state['wins']}W/{state['losses']}L)"
            })
            seen_ids.add(tid)

    # === CHECK: Daily summary (once per day at UTC 00:00-00:05 or forced) ===
    today = now.strftime("%Y-%m-%d")
    hour = now.hour
    if prev.get("last_daily") != today and hour == 0:
        cap = state["capital"]
        pk = state.get("peak_capital", 200)
        dd = ((pk - cap) / pk * 100) if pk > 0 else 0
        ret = (cap - 200) / 200 * 100
        trades = state["trades_count"]
        wins = state["wins"]
        losses = state["losses"]
        wr = (wins / trades * 100) if trades > 0 else 0
        pnl = state["total_pnl"]
        fees = state["total_fees"]
        withdrawn = state.get("total_withdrawn", 0)
        vol_skips = state.get("vol_gate_skips", 0)
        pos_count = len(state.get("positions", []))

        events.append({
            "type": "DAILY",
            "msg": f"📊 JIMI DAILY SUMMARY\n{today} UTC\n\nCapital: ${cap:,.2f} ({ret:+.1f}%)\nPeak: ${pk:,.2f} | DD: {dd:.1f}%\nPnL: ${pnl:+,.2f} | Fees: ${fees:,.2f}\nTrades: {trades} ({wins}W/{losses}L) WR={wr:.0f}%\nWithdrawn: ${withdrawn:,.0f}\nVol Gate Skips: {vol_skips}\nOpen Positions: {pos_count}\nStrategy: {state.get('current_strategy','?')}"
        })
        prev["last_daily"] = today

    # === UPDATE MONITOR STATE ===
    prev["trades_count"] = state.get("trades_count", 0)
    prev["positions_count"] = len(state.get("positions", []))
    prev["seen_position_ids"] = current_pos_ids
    prev["seen_trade_ids"] = list(seen_ids)
    save_json(MONITOR_STATE, prev)

    # === OUTPUT EVENTS ===
    if events:
        for e in events:
            print(f"EVENT:{e['type']}:{e['msg']}")
    else:
        print("NO_NEW_EVENTS")

if __name__ == "__main__":
    main()
