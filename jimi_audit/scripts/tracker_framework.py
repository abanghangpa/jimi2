#!/usr/bin/env python3
"""
ETH Position Tracker - Framework Metrics Direction
Uses swing bias, trend, phase0, whale, L/S ratio.
"""
import json, os, requests, glob
from datetime import datetime, timezone

DATA_DIR = "/root/.openclaw/workspace/jimi_audit/data"
POSITIONS_FILE = os.path.join(DATA_DIR, "positions_framework.json")
SCAN_DIR = os.path.join(DATA_DIR, "scans")

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

def get_framework_direction():
    scans = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    if not scans:
        return None, "no_scan"
    d = json.load(open(scans[-1]))
    score = 0
    reasons = []
    sb = d.get("swing_bias", "NEUTRAL")
    if sb == "BULLISH": score += 2; reasons.append("swing_bull")
    elif sb == "BEARISH": score -= 2; reasons.append("swing_bear")
    td = d.get("trend_dir", "NEUTRAL")
    if "UP" in td: score += 1; reasons.append("trend_up")
    elif "DOWN" in td: score -= 1; reasons.append("trend_down")
    p0 = d.get("phase0") or 0.5
    if p0 > 0.5: score += 1; reasons.append("p0_strong")
    elif p0 < 0.15: score -= 1; reasons.append("p0_weak")
    ws = d.get("derivatives", {}).get("whale_signal", "NEUTRAL")
    if ws == "WHALE_BULLISH": score += 1; reasons.append("whale_bull")
    elif ws == "WHALE_BEARISH": score -= 1; reasons.append("whale_bear")
    ls = d.get("derivatives", {}).get("ls_ratio") or 1.0
    if ls > 1.5: score -= 1; reasons.append("crowded_long")
    elif ls < 0.7: score += 1; reasons.append("crowded_short")
    if score >= 2: return "LONG", ",".join(reasons)
    elif score <= -2: return "SHORT", ",".join(reasons)
    return None, "neutral(%d)" % score

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
    msg = "🧠 *FRAMEWORK METRICS*\n"
    msg += "🕐 %s\n" % now
    msg += "💰 Price: *$%.2f*\n" % current_price
    msg += "📈 Direction: *%s*\n" % (direction or "NEUTRAL")
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
        direction, reason = get_framework_direction()
        if direction:
            data = enter_position(data, current_price, direction, reason)
        else:
            direction, reason = "NEUTRAL", "no_signal"
    else:
        direction = data["positions"][0]["direction"]
        reason = data["positions"][0].get("reason", "")
    save_positions(data)
    print(format_message(data, current_price, newly_closed, direction, reason))

if __name__ == "__main__":
    main()
