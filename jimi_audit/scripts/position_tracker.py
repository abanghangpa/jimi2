#!/usr/bin/env python3
"""
ETH Position Tracker - Uses framework metrics for direction.
"""
import json
import os
import requests
from datetime import datetime, timezone

DATA_DIR = "/root/.openclaw/workspace/jimi_audit/data"
POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
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
    """Get direction from latest scan data."""
    import glob
    scans = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
    if not scans:
        return "LONG", "No scan data"
    
    d = json.load(open(scans[-1]))
    
    # Metrics to consider
    direction = d.get("direction", "NEUTRAL")
    swing_bias = d.get("swing_bias", "NEUTRAL")
    trend_dir = d.get("trend_dir", "NEUTRAL")
    phase0 = d.get("phase0", 0.5)
    m22_regime = d.get("m22", {}).get("regime", "UNKNOWN")
    m9_regime = d.get("m9", {}).get("regime", "UNKNOWN")
    ensemble = d.get("ensemble", {})
    consensus = ensemble.get("consensus", "NONE")
    derivatives = d.get("derivatives", {})
    ls_ratio = derivatives.get("ls_ratio", 1.0)
    whale_signal = derivatives.get("whale_signal", "NEUTRAL")
    
    # Decision logic
    score = 0
    reasons = []
    
    # Swing bias (strong signal)
    if swing_bias == "BULLISH":
        score += 2
        reasons.append("swing_bullish")
    elif swing_bias == "BEARISH":
        score -= 2
        reasons.append("swing_bearish")
    
    # Trend direction
    if "UP" in trend_dir:
        score += 1
        reasons.append("trend_up")
    elif "DOWN" in trend_dir:
        score -= 1
        reasons.append("trend_down")
    
    # Phase0 (momentum)
    if phase0 > 0.5:
        score += 1
        reasons.append("phase0_strong")
    elif phase0 < 0.15:
        score -= 1
        reasons.append("phase0_weak")
    
    # Whale signal
    if whale_signal == "WHALE_BULLISH":
        score += 1
        reasons.append("whale_bull")
    elif whale_signal == "WHALE_BEARISH":
        score -= 1
        reasons.append("whale_bear")
    
    # L/S ratio (contrarian)
    if ls_ratio > 1.5:
        score -= 1
        reasons.append("crowded_long")
    elif ls_ratio < 0.7:
        score += 1
        reasons.append("crowded_short")
    
    # Regime
    if "BULL" in m22_regime or "MARKUP" in m22_regime:
        score += 1
        reasons.append("regime_bull")
    elif "BEAR" in m22_regime or "MARKDOWN" in m22_regime:
        score -= 1
        reasons.append("regime_bear")
    
    # Decision
    if score >= 2:
        direction = "LONG"
    elif score <= -2:
        direction = "SHORT"
    elif score > 0:
        direction = "LONG"
    elif score < 0:
        direction = "SHORT"
    else:
        # Neutral - use recent price action
        try:
            r = requests.get("https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit=3", timeout=5)
            data = r.json()
            if len(data) >= 2:
                price_2h = float(data[0][4])
                price_now = float(data[-1][4])
                direction = "LONG" if price_now > price_2h else "SHORT"
        except:
            direction = "LONG"
    
    reason_str = ", ".join(reasons) if reasons else "neutral"
    return direction, reason_str

def check_positions(data, current_price):
    still_open = []
    newly_closed = []
    
    for pos in data["positions"]:
        entry = pos["entry"]
        direction = pos["direction"]
        
        if direction == "LONG":
            if current_price >= entry + TP:
                pos["exit"] = current_price
                pos["pnl"] = TP
                pos["outcome"] = "WIN"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos)
                data["total_pnl"] += TP
            elif current_price <= entry - SL:
                pos["exit"] = current_price
                pos["pnl"] = -SL
                pos["outcome"] = "LOSS"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos)
                data["total_pnl"] -= SL
            else:
                pos["current"] = current_price
                pos["unrealized"] = current_price - entry
                still_open.append(pos)
        
        elif direction == "SHORT":
            if current_price <= entry - TP:
                pos["exit"] = current_price
                pos["pnl"] = TP
                pos["outcome"] = "WIN"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos)
                data["total_pnl"] += TP
            elif current_price >= entry + SL:
                pos["exit"] = current_price
                pos["pnl"] = -SL
                pos["outcome"] = "LOSS"
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                newly_closed.append(pos)
                data["total_pnl"] -= SL
            else:
                pos["current"] = current_price
                pos["unrealized"] = entry - current_price
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
    
    msg = "📊 *ETH Position Update*\n"
    msg += "🕐 %s\n" % now
    msg += "💰 Price: *$%.2f*\n" % current_price
    msg += "📈 Direction: *%s*\n" % direction
    msg += "🔍 Reason: %s\n\n" % reason
    
    # Open positions
    if data["positions"]:
        msg += "*📋 Open Positions:*\n"
        for pos in data["positions"]:
            d = pos["direction"]
            entry = pos["entry"]
            tp = pos["tp"]
            sl = pos["sl"]
            unrealized = pos.get("unrealized", 0)
            icon = "🟢" if unrealized >= 0 else "🔴"
            pnl_pct = unrealized / entry * 100
            r = pos.get("reason", "")
            
            msg += "%s *%s* (%s)\n" % (icon, d, r)
            msg += "  Entry: $%.2f\n" % entry
            msg += "  TP: $%.2f (+$%d)\n" % (tp, TP)
            msg += "  SL: $%.2f (-$%d)\n" % (sl, SL)
            msg += "  P&L: %+.2f (%+.2f%%)\n\n" % (unrealized, pnl_pct)
    else:
        msg += "*📋 Open Positions:* None\n\n"
    
    # Recently closed
    if newly_closed:
        msg += "*✅ Closed:*\n"
        for pos in newly_closed:
            icon = "🟢" if pos["outcome"] == "WIN" else "🔴"
            msg += "%s %s | $%.2f → $%.2f | *%s$%d*\n" % (
                icon, pos["direction"],
                pos["entry"], pos["exit"],
                "+" if pos["pnl"] > 0 else "", pos["pnl"]
            )
        msg += "\n"
    
    # Summary
    wins = sum(1 for c in data["closed"] if c["outcome"] == "WIN")
    losses = sum(1 for c in data["closed"] if c["outcome"] == "LOSS")
    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    
    msg += "*📊 Overall:*\n"
    msg += "  P&L: *$%d*\n" % data["total_pnl"]
    msg += "  Trades: %d (%dW/%dL)\n" % (total, wins, losses)
    msg += "  WR: %.0f%%\n" % wr
    
    return msg

def main():
    current_price = get_current_price()
    if not current_price:
        print("Failed to get price")
        return
    
    data = load_positions()
    data, newly_closed = check_positions(data, current_price)
    
    # Only enter if no open positions
    if not data["positions"]:
        direction, reason = get_framework_direction()
        data = enter_position(data, current_price, direction, reason)
    else:
        direction = data["positions"][0]["direction"]
        reason = data["positions"][0].get("reason", "")
    
    save_positions(data)
    msg = format_message(data, current_price, newly_closed, direction, reason)
    print(msg)

if __name__ == "__main__":
    main()
