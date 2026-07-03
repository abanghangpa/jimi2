#!/usr/bin/env python3
"""
ETH Position Tracker - Sends WhatsApp updates every 2h.
Enters LONG + SHORT at market, tracks open positions.
"""
import json
import os
from datetime import datetime, timezone

DATA_DIR = "/root/.openclaw/workspace/jimi_audit/data"
POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
PNL_FILE = os.path.join(DATA_DIR, "positions_pnl.json")

TP = 10
SL = 30

def load_positions():
    """Load open positions."""
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {"positions": [], "closed": [], "total_pnl": 0}

def save_positions(data):
    """Save positions."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def get_current_price():
    """Fetch current ETH price."""
    import requests
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=5)
        return float(r.json()["price"])
    except:
        return None

def check_positions(data, current_price):
    """Check if any positions hit TP or SL."""
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

def enter_positions(data, current_price):
    """Enter new LONG and SHORT positions."""
    now = datetime.now(timezone.utc).isoformat()
    
    long_pos = {
        "id": "L_%s" % now[:19],
        "direction": "LONG",
        "entry": current_price,
        "tp": current_price + TP,
        "sl": current_price - SL,
        "opened_at": now,
        "current": current_price,
        "unrealized": 0,
    }
    
    short_pos = {
        "id": "S_%s" % now[:19],
        "direction": "SHORT",
        "entry": current_price,
        "tp": current_price - TP,
        "sl": current_price + SL,
        "opened_at": now,
        "current": current_price,
        "unrealized": 0,
    }
    
    data["positions"].append(long_pos)
    data["positions"].append(short_pos)
    return data

def format_message(data, current_price, newly_closed):
    """Format WhatsApp message."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    msg = "📊 *ETH Position Update*\n"
    msg += "🕐 %s\n" % now
    msg += "💰 Current: *$%.2f*\n\n" % current_price
    
    # Open positions
    if data["positions"]:
        msg += "*📋 Open Positions:*\n"
        for pos in data["positions"]:
            direction = pos["direction"]
            entry = pos["entry"]
            tp = pos["tp"]
            sl = pos["sl"]
            unrealized = pos.get("unrealized", 0)
            icon = "🟢" if unrealized >= 0 else "🔴"
            
            msg += "%s *%s*\n" % (icon, direction)
            msg += "  Entry: $%.2f\n" % entry
            msg += "  TP: $%.2f (+$%d)\n" % (tp, TP)
            msg += "  SL: $%.2f (-$%d)\n" % (sl, SL)
            msg += "  Unrealized: %+.2f\n\n" % unrealized
    else:
        msg += "*📋 Open Positions:* None\n\n"
    
    # Recently closed
    if newly_closed:
        msg += "*✅ Recently Closed:*\n"
        for pos in newly_closed:
            icon = "🟢" if pos["outcome"] == "WIN" else "🔴"
            msg += "%s %s %s | $%.2f → $%.2f | %s$%d\n" % (
                icon, pos["direction"], pos["outcome"],
                pos["entry"], pos["exit"],
                "+" if pos["pnl"] > 0 else "", pos["pnl"]
            )
        msg += "\n"
    
    # Summary
    wins = sum(1 for c in data["closed"] if c["outcome"] == "WIN")
    losses = sum(1 for c in data["closed"] if c["outcome"] == "LOSS")
    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    
    msg += "*📊 Summary:*\n"
    msg += "  Total PnL: *$%d*\n" % data["total_pnl"]
    msg += "  Closed: %d trades (%dW/%dL)\n" % (total, wins, losses)
    msg += "  Win Rate: %.0f%%\n" % wr
    msg += "  Open: %d positions\n" % len(data["positions"])
    
    return msg

def main():
    """Main function."""
    import requests
    
    # Get current price
    current_price = get_current_price()
    if not current_price:
        print("Failed to get price")
        return
    
    # Load positions
    data = load_positions()
    
    # Check existing positions
    data, newly_closed = check_positions(data, current_price)
    
    # Enter new positions
    data = enter_positions(data, current_price)
    
    # Save positions
    save_positions(data)
    
    # Format message
    msg = format_message(data, current_price, newly_closed)
    
    # Output message for cron job to send
    print(msg)
    
    # Also save to file for reference
    with open(PNL_FILE, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": current_price,
            "total_pnl": data["total_pnl"],
            "open_positions": len(data["positions"]),
            "closed_trades": len(data["closed"]),
            "message": msg,
        }, f, indent=2)

if __name__ == "__main__":
    main()
