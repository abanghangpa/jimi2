#!/usr/bin/env python3
"""
Order Book Imbalance Collector
Snapshots OB state every minute to detect:
- Persistence: has imbalance held for 5+ minutes?
- Delta: is imbalance increasing or decreasing?
- Spoofing: did a wall appear and disappear quickly?

Stores to: data/ob_history/ob_snapshots.jsonl
Run via systemd timer (every 60s).
"""

import os, sys, json, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "ob_history")
os.makedirs(DATA_DIR, exist_ok=True)

SNAPSHOTS_FILE = os.path.join(DATA_DIR, "ob_snapshots.jsonl")
SPOOF_LOG = os.path.join(DATA_DIR, "spoof_events.jsonl")

# Keep max 2 hours of snapshots (120 entries at 1/min)
MAX_SNAPSHOTS = 150


def fetch_ob_snapshot():
    """Fetch current order book from Bybit (free, no key)."""
    import requests
    try:
        # Get orderbook depth (top 50 levels each side)
        r = requests.get("https://api.bybit.com/v5/market/orderbook",
                        params={"category": "linear", "symbol": "ETHUSDT", "limit": 50},
                        timeout=10)
        r.raise_for_status()
        data = r.json().get("result", {})

        bids = [(float(p), float(q)) for p, q in data.get("b", [])]
        asks = [(float(p), float(q)) for p, q in data.get("a", [])]

        if not bids or not asks:
            return None

        bid_total = sum(q for _, q in bids)
        ask_total = sum(q for _, q in asks)
        total = bid_total + ask_total

        # OB ratio: positive = bid-heavy (buyers), negative = ask-heavy (sellers)
        ob_ratio = (bid_total - ask_total) / total if total > 0 else 0

        # Top 5 levels each side (where the real walls are)
        top5_bid_vol = sum(q for _, q in bids[:5])
        top5_ask_vol = sum(q for _, q in asks[:5])
        top5_ratio = (top5_bid_vol - top5_ask_vol) / (top5_bid_vol + top5_ask_vol) if (top5_bid_vol + top5_ask_vol) > 0 else 0

        # Largest single wall
        max_bid = max(bids, key=lambda x: x[1]) if bids else (0, 0)
        max_ask = max(asks, key=lambda x: x[1]) if asks else (0, 0)

        # Spread
        spread = asks[0][0] - bids[0][0] if bids and asks else 0
        spread_pct = spread / bids[0][0] if bids and bids[0][0] > 0 else 0

        return {
            "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
            "bid_total": round(bid_total, 2),
            "ask_total": round(ask_total, 2),
            "ob_ratio": round(ob_ratio, 6),
            "top5_bid_vol": round(top5_bid_vol, 2),
            "top5_ask_vol": round(top5_ask_vol, 2),
            "top5_ratio": round(top5_ratio, 6),
            "max_bid_price": max_bid[0],
            "max_bid_vol": round(max_bid[1], 2),
            "max_ask_price": max_ask[0],
            "max_ask_vol": round(max_ask[1], 2),
            "spread": round(spread, 2),
            "spread_pct": round(spread_pct, 6),
            "best_bid": bids[0][0],
            "best_ask": asks[0][0],
        }
    except Exception as e:
        print(f"  ⚠️ OB fetch failed: {e}")
        return None


def detect_spoof(current, history):
    """
    Detect spoofing: large wall appears then disappears within 2-5 minutes.
    Returns list of spoof events.
    """
    spoofs = []
    if len(history) < 3:
        return spoofs

    # Check if a large wall (>50 ETH) appeared in last 3 snapshots and disappeared
    for side in ['bid', 'ask']:
        vol_key = f"max_{side}_vol"
        price_key = f"max_{side}_price"

        # Get wall sizes from last 5 snapshots
        recent_walls = []
        for snap in history[-5:]:
            recent_walls.append({
                "vol": snap.get(vol_key, 0),
                "price": snap.get(price_key, 0),
                "ts": snap.get("ts", 0)
            })

        if len(recent_walls) < 3:
            continue

        # Check pattern: small → large → small (wall appeared then vanished)
        for i in range(1, len(recent_walls) - 1):
            prev_vol = recent_walls[i-1]["vol"]
            curr_vol = recent_walls[i]["vol"]
            next_vol = recent_walls[i+1]["vol"]

            # Wall appeared (3x increase) then vanished (dropped back to prev level)
            if curr_vol > 50 and curr_vol > prev_vol * 3 and next_vol < prev_vol * 1.5:
                spoofs.append({
                    "ts": recent_walls[i]["ts"],
                    "side": side,
                    "wall_vol": curr_vol,
                    "wall_price": recent_walls[i]["price"],
                    "appeared_at": i,
                    "vanished_at": i + 1,
                    "pattern": "appear_vanish"
                })

    return spoofs


def compute_metrics(history):
    """
    Compute persistence and delta metrics from OB history.
    Returns dict with analysis results.
    """
    if len(history) < 2:
        return {"persistence_bars": 0, "ob_delta": 0, "top5_delta": 0, "trend": "NEUTRAL"}

    current = history[-1]
    ob_ratio = current.get("ob_ratio", 0)
    top5_ratio = current.get("top5_ratio", 0)

    # Persistence: how many consecutive snapshots has the imbalance been in same direction?
    persistence = 0
    direction = "BUY" if ob_ratio > 0.05 else ("SELL" if ob_ratio < -0.05 else "NEUTRAL")

    for snap in reversed(history):
        snap_dir = "BUY" if snap.get("ob_ratio", 0) > 0.05 else ("SELL" if snap.get("ob_ratio", 0) < -0.05 else "NEUTRAL")
        if snap_dir == direction:
            persistence += 1
        else:
            break

    # Delta: change in OB ratio over last 5 snapshots
    if len(history) >= 5:
        ob_5ago = history[-5].get("ob_ratio", 0)
        top5_5ago = history[-5].get("top5_ratio", 0)
        ob_delta = ob_ratio - ob_5ago
        top5_delta = top5_ratio - top5_5ago
    else:
        ob_delta = 0
        top5_delta = 0

    # Trend: is imbalance increasing or decreasing?
    if ob_delta > 0.05:
        trend = "BUY_STRENGTHENING"
    elif ob_delta < -0.05:
        trend = "SELL_STRENGTHENING"
    elif abs(ob_delta) < 0.02:
        trend = "STABLE"
    else:
        trend = "NEUTRAL"

    return {
        "persistence_bars": persistence,
        "persistence_minutes": persistence,  # 1 snapshot per minute
        "ob_delta_5m": round(ob_delta, 6),
        "top5_delta_5m": round(top5_delta, 6),
        "trend": trend,
        "direction": direction,
    }


def collect():
    """Collect one OB snapshot, compute metrics, detect spoofs."""
    snap = fetch_ob_snapshot()
    if not snap:
        return None

    # Load history
    history = []
    if os.path.exists(SNAPSHOTS_FILE):
        try:
            with open(SNAPSHOTS_FILE) as f:
                for line in f:
                    try:
                        history.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    # Append current snapshot
    history.append(snap)

    # Trim to max size
    if len(history) > MAX_SNAPSHOTS:
        history = history[-MAX_SNAPSHOTS:]

    # Write trimmed history back
    with open(SNAPSHOTS_FILE, "w") as f:
        for h in history:
            f.write(json.dumps(h) + "\n")

    # Compute metrics
    metrics = compute_metrics(history)

    # Detect spoofs
    spoofs = detect_spoof(snap, history)
    if spoofs:
        for s in spoofs:
            with open(SPOOF_LOG, "a") as f:
                f.write(json.dumps(s) + "\n")

    # Save state for strategy to read
    state = {
        "last_update": datetime.now(timezone.utc).isoformat(),
        "snapshot": snap,
        "metrics": metrics,
        "recent_spoofs": len(spoofs),
        "history_size": len(history),
    }
    state_file = os.path.join(DATA_DIR, "ob_state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    return state


if __name__ == "__main__":
    result = collect()
    if result:
        s = result["snapshot"]
        m = result["metrics"]
        print(f"[{result['last_update']}] OB Ratio: {s['ob_ratio']:.4f} | "
              f"Top5: {s['top5_ratio']:.4f} | "
              f"Persistence: {m['persistence_minutes']}m | "
              f"Delta: {m['ob_delta_5m']:.4f} | "
              f"Trend: {m['trend']} | "
              f"Spoofs: {result['recent_spoofs']}")
    else:
        print("Failed to collect OB snapshot")
