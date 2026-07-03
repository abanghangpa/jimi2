#!/usr/bin/env python3
"""
ETH Position Tracker - Random/Price Trend Direction
Simple price vs 2h ago trend.
"""
import json, os, requests
from datetime import datetime, timezone

DATA_DIR = "/root/.openclaw/workspace/jimi_audit/data"
POSITIONS_FILE = os.path.join(DATA_DIR, "positions_random.json")

TP = 10
SL = 30

def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {"positions": [], "closed": [], "total_pnl": 0}

def save_positions(data):
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def get_current_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=5)
        return float(r.json()["price"])
    except:
        return None

def get_trend():
    try:
        r = requests.get("https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit=3", timeout=5)
        data = r.json()
        if len(data) >= 2:
            price_2h = float(data[0][4])
            price_now = float(data[-1][4])
            diff = price_now - price_2h
            if diff > 5:
                return "LONG", "price_up_%.0f" % diff
            elif diff < -5:
                return "SHORT", "price_down_%.0f" % abs(diff)
        return "LONG", "default_long"
    except:
        return "LONG", "fallback"

def check_positions(data, current_price):
    still_open = []
    newly_closed = []
    for pos in data["positions"]:
        entry = pos["entry"]
        direction = pos["direction"]
        if direction == "LONG":
            if current_price >= entry + TP:
                pos["exit"] = current_price; pos["pnl"] = TP; pos["outcome"] = "WIN"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos); data["total_pnl"] += TP
            elif current_price <= entry - SL:
                pos["exit"] = current_price; pos["pnl"] = -SL; pos["outcome"] = "LOSS"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos); data["total_pnl"] -= SL
            else:
                pos["current"] = current_price; pos["unrealized"] = current_price - entry
                still_open.append(pos)
        elif direction == "SHORT":
            if current_price <= entry - TP:
                pos["exit"] = current_price; pos["pnl"] = TP; pos["outcome"] = "WIN"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos); data["total_pnl"] += TP
            elif current_price >= entry + SL:
                pos["exit"] = current_price; pos["pnl"] = -SL; pos["outcome"] = "LOSS"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos); data["total_pnl"] -= SL
            else:
                pos["current"] = current_price; pos["unrealized"] = entry - current_price
                still_open.append(pos)
    data["positions"] = still_open
    data["closed"].extend(newly_closed)
    return data, newly_closed

def enter_position(data, current_price, direction, reason):
    now = datetime.now(timezone.utc).isoformat()
    pos = {
        "id": "%s_%s" % (direction[0], now[:19]),
        "direction": direction,
        "entry": current_price,
        "tp": current_price + TP if direction == "LONG" else current_price - TP,
        "sl": current_price - SL if direction == "LONG" else current_price + SL,
        "opened_at": now,
        "current": current_price,
        "unrealized": 0,
        "reason": reason,
    }
    data["positions"].append(pos)
    return data

def format_message(data, current_price, newly_closed, direction, reason):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = "🎲 *RANDOM/TREND ENTRY*\n"
    msg += "🕐 %s\n" % now
    msg += "💰 Price: *$%.2f*\n" % current_price
    msg += "📈 Direction: *%s*\n" % direction
    msg += "🔍 Reason: %s\n\n" % reason
    if data["positions"]:
        msg += "*📋 Open:*\n"
        for pos in data["positions"]:
            d = pos["direction"]
            entry = pos["entry"]
            tp = pos["tp"]
            sl = pos["sl"]
            unrealized = pos.get("unrealized", 0)
            icon = "🟢" if unrealized >= 0 else "🔴"
            pnl_pct = unrealized / entry * 100
            msg += "%s *%s*\n" % (icon, d)
            msg += "  Entry: $%.2f | TP: $%.2f | SL: $%.2f\n" % (entry, tp, sl)
            msg += "  P&L: %+.2f (%+.2f%%)\n\n" % (unrealized, pnl_pct)
    else:
        msg += "*📋 Open:* None\n\n"
    if newly_closed:
        msg += "*✅ Closed:*\n"
        for pos in newly_closed:
            icon = "🟢" if pos["outcome"] == "WIN" else "🔴"
            msg += "%s %s | $%.2f→$%.2f | *%s$%d*\n" % (icon, pos["direction"], pos["entry"], pos["exit"], "+" if pos["pnl"] > 0 else "", pos["pnl"])
        msg += "\n"
    wins = sum(1 for c in data["closed"] if c["outcome"] == "WIN")
    losses = sum(1 for c in data["closed"] if c["outcome"] == "LOSS")
    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    msg += "*📊 Overall:* PnL *$%d* | %d trades (%dW/%dL) | WR %.0f%%" % (data["total_pnl"], total, wins, losses, wr)
    return msg

def main():
    current_price = get_current_price()
    if not current_price:
        print("Failed to get price"); return
    data = load_positions()
    data, newly_closed = check_positions(data, current_price)
    if not data["positions"]:
        direction, reason = get_trend()
        data = enter_position(data, current_price, direction, reason)
    else:
        direction = data["positions"][0]["direction"]
        reason = data["positions"][0].get("reason", "")
    save_positions(data)
    print(format_message(data, current_price, newly_closed, direction, reason))

if __name__ == "__main__":
    main()
