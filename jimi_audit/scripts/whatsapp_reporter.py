#!/usr/bin/env python3
"""
WhatsApp Status Reporter
Reads live trader state and outputs formatted status for OpenClaw announce.
Runs as cron job — does NOT trade, just reports.
"""
import json, os
from datetime import datetime, timezone

BASE = "/root/.openclaw/workspace/jimi_audit"
STATE_FILE = os.path.join(BASE, "live", "data", "state.json")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return None

def format_report(state):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    if not state:
        return f"JIMI LIVE — {now}\nNo state file found. Trader may not be running."
    
    capital = state.get("capital", 0)
    peak = state.get("peak_capital", capital)
    dd_pct = ((peak - capital) / peak * 100) if peak > 0 else 0
    ret = (capital - 200) / 200 * 100
    
    msg = f"JIMI LIVE TRADER\n"
    msg += f"Time: {now}\n"
    msg += f"Strategy: BB Mean Rev + mom6\n"
    msg += f"Capital: ${capital:,.2f} ({ret:+.1f}%) | Peak: ${peak:,.2f} | DD: {dd_pct:.1f}%\n"
    msg += f"P&L: ${state.get('total_pnl', 0):+,.2f} | Fees: ${state.get('total_fees', 0):.4f}\n"
    msg += f"Total Withdrawn: ${state.get('total_withdrawn', 0):,.0f}\n"
    
    t = state.get("trades_count", 0)
    w = state.get("wins", 0)
    wr = (w / t * 100) if t > 0 else 0
    msg += f"Trades: {t} ({w}W/{t-w}L) WR {wr:.0f}% | DD triggers: {state.get('dd_triggered_count', 0)}\n"
    msg += f"Vol Gate Skips: {state.get('vol_gate_skips', 0)}\n"
    
    dd_cd = state.get("dd_cooldown_until")
    if dd_cd:
        msg += f"!! DD COOLDOWN until {dd_cd[:16]}\n"
    
    positions = state.get("positions", [])
    if positions:
        msg += f"\nOpen:\n"
        for pos in positions:
            msg += f"  {pos['direction']} @ ${pos['entry']:.2f} | TP ${pos['tp']:.2f} SL ${pos['sl']:.2f} | {pos.get('reason', '')}\n"
    else:
        msg += "\nNo open positions.\n"
    
    closed = state.get("closed_trades", [])
    if closed:
        msg += f"\nLast 3 trades:\n"
        for trade in closed[-3:]:
            icon = "+" if trade.get("outcome") == "WIN" else "-"
            msg += f"  {icon} {trade['direction']} ${trade['entry']:.2f} -> ${trade['exit']:.2f} | PnL: ${trade.get('pnl', 0):+.2f}\n"
    
    return msg

if __name__ == "__main__":
    state = load_state()
    print(format_report(state))
