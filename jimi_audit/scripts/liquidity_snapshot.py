#!/usr/bin/env python3
"""
JIMI — Enhanced Liquidity Snapshot

Captures ALL liquidity levels from latest_scan.json and stores hourly snapshots.
Compares with previous snapshot to detect:
  - Equal highs/lows (swing H/L at same price)
  - Liquidity level changes (gained/lost strength)
  - Buy-side vs sell-side accumulation rate
  - Most attractive target with probability estimate

Output: data/liquidity_snapshots_enhanced.json (append-only log)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SCAN_FILE = os.path.join(BASE_DIR, "..", "latest_scan.json")
SNAP_FILE = os.path.join(BASE_DIR, "data", "liquidity_snapshots_enhanced.json")
EQUAL_HL_THRESHOLD = 0.001  # 0.1% price tolerance for equal highs/lows


def load_scan():
    with open(SCAN_FILE) as f:
        return json.load(f)


def load_snapshots():
    if not os.path.exists(SNAP_FILE):
        return []
    with open(SNAP_FILE) as f:
        return json.load(f)


def save_snapshots(snaps):
    os.makedirs(os.path.dirname(SNAP_FILE), exist_ok=True)
    with open(SNAP_FILE, "w") as f:
        json.dump(snaps, f, indent=2)


def detect_equal_levels(levels, threshold=EQUAL_HL_THRESHOLD):
    """Find clusters of levels at similar prices (equal highs/lows)."""
    equal_groups = []
    used = set()
    
    for i, a in enumerate(levels):
        if i in used:
            continue
        group = [a]
        for j, b in enumerate(levels):
            if j <= i or j in used:
                continue
            if abs(a["price"] - b["price"]) / max(a["price"], 0.01) < threshold:
                group.append(b)
                used.add(j)
        if len(group) >= 2:
            used.add(i)
            avg_price = sum(g["price"] for g in group) / len(group)
            total_strength = sum(g.get("strength", 0) for g in group)
            types = list(set(g.get("type", "?") for g in group))
            equal_groups.append({
                "price": round(avg_price, 2),
                "count": len(group),
                "types": types,
                "total_strength": round(total_strength, 2),
                "label": f"Equal {'Highs' if any('HIGH' in t or 'SHORT' in t for t in types) else 'Lows'} x{len(group)}"
            })
    
    return equal_groups


def build_snapshot(scan):
    """Build a liquidity snapshot from scanner output."""
    price = scan.get("price", 0)
    liq = scan.get("liquidity_levels", {})
    magnets = scan.get("magnets", [])
    sr = scan.get("sr_levels", [])
    gaps = scan.get("gaps", [])
    
    # All levels from liquidity_levels
    all_levels = liq.get("all", [])
    below = liq.get("below", [])
    above = liq.get("above", [])
    
    # Classify levels
    classified = []
    for lvl in all_levels:
        classified.append({
            "price": lvl.get("price", 0),
            "type": lvl.get("type", "?"),
            "strength": lvl.get("strength", 0),
            "cascade_risk": lvl.get("cascade_risk", "LOW"),
            "swept": lvl.get("swept", False),
            "side": "buy" if lvl.get("price", 0) < price else "sell",
            "dist_pct": round((lvl.get("price", 0) - price) / max(price, 0.01) * 100, 2)
        })
    
    # Add magnets as levels
    for mag in magnets:
        if len(mag) >= 3:
            classified.append({
                "price": mag[0],
                "type": "MAGNET",
                "strength": mag[1],
                "cascade_risk": "LOW",
                "swept": mag[2] if len(mag) > 2 else False,
                "side": "buy" if mag[0] < price else "sell",
                "dist_pct": round((mag[0] - price) / max(price, 0.01) * 100, 2)
            })
    
    # Add S/R levels
    for s in sr:
        if len(s) >= 3:
            classified.append({
                "price": s[0],
                "type": s[2] if len(s) > 2 else "SR",
                "strength": s[1],
                "cascade_risk": "LOW",
                "swept": False,
                "side": "buy" if s[2] == "SUPPORT" else "sell" if len(s) > 2 else "neutral",
                "dist_pct": round((s[0] - price) / max(price, 0.01) * 100, 2)
            })
    
    # Add FVGs
    for g in gaps:
        classified.append({
            "price": g,
            "type": "FVG",
            "strength": 0,
            "cascade_risk": "LOW",
            "swept": False,
            "side": "buy" if g < price else "sell",
            "dist_pct": round((g - price) / max(price, 0.01) * 100, 2)
        })
    
    # Deduplicate by price (within 0.01%)
    deduped = []
    classified.sort(key=lambda x: x["price"])
    for lvl in classified:
        if not deduped or abs(lvl["price"] - deduped[-1]["price"]) / max(lvl["price"], 0.01) > 0.0001:
            deduped.append(lvl)
    
    # Detect equal highs/lows
    swing_highs = [l for l in deduped if "HIGH" in l["type"].upper() or "SHORT" in l["type"].upper() or l["type"] == "RESISTANCE"]
    swing_lows = [l for l in deduped if "LOW" in l["type"].upper() or "LONG" in l["type"].upper() or l["type"] == "SUPPORT"]
    equal_highs = detect_equal_levels(swing_highs)
    equal_lows = detect_equal_levels(swing_lows)
    
    # Buy/sell side totals
    buy_strength = sum(l["strength"] for l in deduped if l["side"] == "buy")
    sell_strength = sum(l["strength"] for l in deduped if l["side"] == "sell")
    
    # Sort by distance from price
    deduped.sort(key=lambda x: abs(x["dist_pct"]))
    
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "price": price,
        "levels": deduped,
        "equal_highs": equal_highs,
        "equal_lows": equal_lows,
        "buy_side_strength": round(buy_strength, 2),
        "sell_side_strength": round(sell_strength, 2),
        "total_levels": len(deduped),
        "unswept_above": sum(1 for l in deduped if l["side"] == "sell" and not l["swept"]),
        "unswept_below": sum(1 for l in deduped if l["side"] == "buy" and not l["swept"]),
    }


def compute_deltas(curr, prev):
    """Compare current snapshot with previous to find changes."""
    if not prev:
        return {"changes": [], "new_levels": [], "removed_levels": []}
    
    prev_levels = {round(l["price"], 2): l for l in prev.get("levels", [])}
    curr_levels = {round(l["price"], 2): l for l in curr.get("levels", [])}
    
    changes = []
    new_levels = []
    
    for price_key, curr_lvl in curr_levels.items():
        if price_key in prev_levels:
            prev_lvl = prev_levels[price_key]
            strength_delta = curr_lvl["strength"] - prev_lvl["strength"]
            if abs(strength_delta) > 0.5:  # Significant change threshold
                changes.append({
                    "price": curr_lvl["price"],
                    "type": curr_lvl["type"],
                    "prev_strength": round(prev_lvl["strength"], 2),
                    "curr_strength": round(curr_lvl["strength"], 2),
                    "delta": round(strength_delta, 2),
                    "pct_change": round(strength_delta / max(prev_lvl["strength"], 0.01) * 100, 1),
                    "side": curr_lvl["side"]
                })
        else:
            new_levels.append(curr_lvl)
    
    removed_levels = [l for p, l in prev_levels.items() if p not in curr_levels]
    
    # Sort changes by magnitude
    changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
    
    return {
        "changes": changes[:10],  # Top 10 changes
        "new_levels": new_levels[:5],
        "removed_levels": removed_levels[:5]
    }


def format_report(snapshot, deltas):
    """Format WhatsApp-friendly report."""
    lines = []
    lines.append("═══════════════════════════════════")
    lines.append("🔍 ENHANCED LIQUIDITY SNAPSHOT")
    lines.append("═══════════════════════════════════")
    lines.append(f"⏰ {snapshot['timestamp']}")
    lines.append(f"💰 ETH ${snapshot['price']:,.2f}")
    lines.append("")
    
    # Summary
    lines.append(f"📊 Levels: {snapshot['total_levels']} total")
    lines.append(f" Buy-side strength: {snapshot['buy_side_strength']:,.0f}")
    lines.append(f" Sell-side strength: {snapshot['sell_side_strength']:,.0f}")
    bias = "BUY" if snapshot['buy_side_strength'] > snapshot['sell_side_strength'] * 1.2 else "SELL" if snapshot['sell_side_strength'] > snapshot['buy_side_strength'] * 1.2 else "NEUTRAL"
    lines.append(f" Bias: {bias}")
    lines.append("")
    
    # Equal highs/lows
    if snapshot.get("equal_highs"):
        lines.append("🔺 Equal Highs:")
        for eh in snapshot["equal_highs"]:
            lines.append(f" ${eh['price']:,.2f} — {eh['label']} (str={eh['total_strength']:,.0f})")
    
    if snapshot.get("equal_lows"):
        lines.append("🔻 Equal Lows:")
        for el in snapshot["equal_lows"]:
            lines.append(f" ${el['price']:,.2f} — {el['label']} (str={el['total_strength']:,.0f})")
    
    if snapshot.get("equal_highs") or snapshot.get("equal_lows"):
        lines.append("")
    
    # Top levels above price
    above = [l for l in snapshot["levels"] if l["side"] == "sell"][:8]
    if above:
        lines.append("📈 Levels ABOVE price:")
        for l in above:
            swept = "✅" if l["swept"] else "⬜"
            lines.append(f" {swept} ${l['price']:,.2f} {l['type']} str={l['strength']:,.1f} ({l['dist_pct']:+.1f}%) {l['cascade_risk']}")
        lines.append("")
    
    # Top levels below price
    below = [l for l in snapshot["levels"] if l["side"] == "buy"][:8]
    if below:
        lines.append("📉 Levels BELOW price:")
        for l in below:
            swept = "✅" if l["swept"] else "⬜"
            lines.append(f" {swept} ${l['price']:,.2f} {l['type']} str={l['strength']:,.1f} ({l['dist_pct']:+.1f}%) {l['cascade_risk']}")
        lines.append("")
    
    # Deltas
    if deltas.get("changes"):
        lines.append("🔄 Hourly Changes:")
        for c in deltas["changes"][:5]:
            arrow = "↑" if c["delta"] > 0 else "↓"
            lines.append(f" {arrow} ${c['price']:,.2f} {c['type']}: {c['prev_strength']:,.0f}→{c['curr_strength']:,.0f} ({c['pct_change']:+.1f}%)")
        lines.append("")
    
    if deltas.get("new_levels"):
        lines.append("🆕 New Levels:")
        for l in deltas["new_levels"][:3]:
            lines.append(f" + ${l['price']:,.2f} {l['type']} str={l['strength']:,.1f}")
        lines.append("")
    
    # Most attractive target
    unswept = [l for l in snapshot["levels"] if not l["swept"]]
    if unswept:
        target = min(unswept, key=lambda x: abs(x["dist_pct"]))
        lines.append(f"🎯 Nearest unswept target: ${target['price']:,.2f} ({target['dist_pct']:+.1f}%)")
    
    return "\n".join(lines)


if __name__ == "__main__":
    scan = load_scan()
    snapshots = load_snapshots()
    
    # Build current snapshot
    snapshot = build_snapshot(scan)
    
    # Get previous for delta
    prev = snapshots[-1] if snapshots else None
    
    # Compute deltas
    deltas = compute_deltas(snapshot, prev)
    
    # Append to log
    snapshots.append(snapshot)
    
    # Keep last 168 snapshots (7 days hourly)
    if len(snapshots) > 168:
        snapshots = snapshots[-168:]
    
    save_snapshots(snapshots)
    
    # Print report
    report = format_report(snapshot, deltas)
    print(report)
