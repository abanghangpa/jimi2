#!/usr/bin/env python3
"""
JIMI — Hourly Liquidity Reporter

Reads the latest row from liquidity_snapshots.csv and prints a
WhatsApp-friendly liquidity report to stdout.

Usage:
    python scripts/liquidity_reporter.py              # print report
    python scripts/liquidity_reporter.py --prev        # include previous row for deltas
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "liquidity_snapshots.csv")
MULTI_TF_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "magnets_multi_tf.json")


def read_last_n_rows(n=2):
    """Read the last N rows from the CSV."""
    rows = []
    with open(DATA_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows[-n:] if len(rows) >= n else rows


def load_multi_tf_magnets(timestamp=None):
    if not os.path.exists(MULTI_TF_FILE):
        return None
    try:
        with open(MULTI_TF_FILE) as f:
            data = json.load(f)
        if timestamp and str(timestamp) in data:
            return data[str(timestamp)]
        if data:
            latest_key = sorted(data.keys())[-1]
            return data[latest_key]
    except Exception:
        pass
    return None


def fmt_num(val, decimals=2):
    """Format a number, return '?' if missing."""
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return "?"


def fmt_pct(val, decimals=2):
    """Format a percentage."""
    try:
        return f"{float(val):+.{decimals}f}%"
    except (ValueError, TypeError):
        return "?"


def fmt_delta(curr, prev, decimals=2):
    """Format delta between two values."""
    try:
        c, p = float(curr), float(prev)
        d = c - p
        arrow = "↑" if d > 0 else "↓" if d < 0 else "→"
        return f"{arrow}{abs(d):.{decimals}f}"
    except (ValueError, TypeError):
        return "→"


def arrow(curr, prev):
    """Simple arrow based on comparison."""
    try:
        c, p = float(curr), float(prev)
        if c > p:
            return "↑"
        elif c < p:
            return "↓"
        return "→"
    except (ValueError, TypeError):
        return "→"


def swept_icon(swept):
    return "✅" if str(swept).upper() == "YES" else "⬜"


def direction_icon(d):
    d = str(d).upper()
    if d == "LONG":
        return "🟢 LONG"
    elif d == "SHORT":
        return "🔴 SHORT"
    return f"⚪ {d}"


def swing_icon(s):
    s = str(s).upper()
    if s == "BULLISH":
        return "🟢 BULLISH"
    elif s == "BEARISH":
        return "🔴 BEARISH"
    return f"⚪ {s}"


def price_change(curr_price, prev_price):
    try:
        c, p = float(curr_price), float(prev_price)
        d = c - p
        pct = (d / p) * 100 if p != 0 else 0
        icon = "🟢" if d >= 0 else "🔴"
        return f"{icon} {fmt_num(d, 2)} ({fmt_pct(pct, 2)})"
    except (ValueError, TypeError):
        return ""


def generate_report(curr, prev=None):
    """Generate the WhatsApp-friendly report."""
    ts = curr.get("timestamp", "?")
    price = curr.get("price", "?")

    lines = []
    lines.append("═══════════════════════════════════")
    lines.append("📊 JIMI HOURLY LIQUIDITY REPORT")
    lines.append("═══════════════════════════════════")
    lines.append(f"⏰ {ts}")
    lines.append("")

    # Price
    if prev:
        pc = price_change(price, prev.get("price", price))
        lines.append(f"💰 ETH ${fmt_num(price)} {pc}")
    else:
        lines.append(f"💰 ETH ${fmt_num(price)}")

    atr = curr.get("atr_1h", "?")
    atr_pct = curr.get("atr_pct", "?")
    vol = curr.get("vol_ratio", "?")
    lines.append(f" ATR(1H): ${fmt_num(atr)} ({fmt_pct(atr_pct)}) Vol: {fmt_num(vol, 3)}x")
    lines.append("")

    # Direction & ICS
    direction = curr.get("direction", "?")
    swing = curr.get("swing_bias", "?")
    ics = curr.get("ics", "?")

    if prev:
        pd = prev.get("direction", "?")
        ps = prev.get("swing_bias", "?")
        pi = prev.get("ics", "?")
        lines.append(f"📐 Direction: {direction_icon(direction)} (prev: {pd})")
        lines.append(f" Swing: {swing_icon(swing)} (prev: {ps})")
        ics_delta = fmt_delta(ics, pi, 4)
        lines.append(f" ICS: {fmt_num(ics, 4)} {ics_delta} (prev: {fmt_num(pi, 4)})")
    else:
        lines.append(f"📐 Direction: {direction_icon(direction)}")
        lines.append(f" Swing: {swing_icon(swing)}")
        lines.append(f" ICS: {fmt_num(ics, 4)}")
    lines.append("")

    # Module scores
    m1 = curr.get("m1_score", "?")
    m2 = curr.get("m2_score", "?")
    m3 = curr.get("m3_score", "?")
    m4 = curr.get("m4_score", "?")
    m5 = curr.get("m5_score", "?")
    if prev:
        lines.append(f"📈 Scores: M1={fmt_num(m1,3)}{arrow(m1,prev.get('m1_score',m1))} M2={fmt_num(m2,3)}{arrow(m2,prev.get('m2_score',m2))} M3={fmt_num(m3,3)}{arrow(m3,prev.get('m3_score',m3))} M4={fmt_num(m4,3)}{arrow(m4,prev.get('m4_score',m4))} M5={fmt_num(m5,3)}{arrow(m5,prev.get('m5_score',m5))}")
    else:
        lines.append(f"📈 Scores: M1={fmt_num(m1,3)} M2={fmt_num(m2,3)} M3={fmt_num(m3,3)} M4={fmt_num(m4,3)} M5={fmt_num(m5,3)}")
    lines.append("")

    # Derivatives
    lines.append("📊 Derivatives:")
    oi_eth = curr.get("oi_eth", "?")
    oi_usd = curr.get("oi_usd", "?")
    oi_roc = curr.get("oi_roc_1h", "?")
    ls_ratio = curr.get("ls_ratio", "?")
    long_pct = curr.get("long_pct", "?")
    short_pct = curr.get("short_pct", "?")
    ls_zscore = curr.get("ls_zscore", "?")
    taker = curr.get("taker_ratio", "?")
    funding = curr.get("funding_rate", "?")
    whale = curr.get("whale_signal", "?")
    positioning = curr.get("positioning", "?")
    oi_div = curr.get("oi_price_div", "?")

    if prev:
        lines.append(f" OI: {fmt_num(oi_eth,0)} ETH (${fmt_num(float(oi_usd)/1e9 if oi_usd != '?' else '?', 2)}B) {arrow(oi_roc, 0)} {fmt_pct(oi_roc)}")
        lines.append(f" L/S: {fmt_num(ls_ratio,4)} {arrow(ls_ratio, prev.get('ls_ratio', ls_ratio))} (L{fmt_num(long_pct,0)}% / S{fmt_num(short_pct,0)}%) z={fmt_num(ls_zscore,2)}")
        lines.append(f" Taker: {fmt_num(taker,4)} {arrow(taker, prev.get('taker_ratio', taker))}")
        lines.append(f" Funding: {fmt_pct(funding)} (prev: {fmt_pct(prev.get('funding_rate', funding))})")
        lines.append(f" Whale: {whale} (prev: {prev.get('whale_signal', whale)})")
        lines.append(f" Position: {positioning} OI/Price Div: {oi_div}")
    else:
        lines.append(f" OI: {fmt_num(oi_eth,0)} ETH (${fmt_num(float(oi_usd)/1e9 if oi_usd != '?' else '?', 2)}B) {fmt_pct(oi_roc)}")
        lines.append(f" L/S: {fmt_num(ls_ratio,4)} (L{fmt_num(long_pct,0)}% / S{fmt_num(short_pct,0)}%) z={fmt_num(ls_zscore,2)}")
        lines.append(f" Taker: {fmt_num(taker,4)}")
        lines.append(f" Funding: {fmt_pct(funding)}")
        lines.append(f" Whale: {whale}")
        lines.append(f" Position: {positioning} OI/Price Div: {oi_div}")
    lines.append("")

    # Magnets - Multi-Timeframe
    ts = curr.get("timestamp", "")
    mtf = load_multi_tf_magnets(ts)

    if mtf:
        tf_order = ['1d', '1w', '1m', '1q', '1y']
        for tf_key in tf_order:
            tf_data = mtf.get(tf_key)
            if not tf_data:
                continue
            label = tf_data.get('label', tf_key)
            mags = tf_data.get('magnets', [])
            if not mags:
                continue
            lines.append(f"🧲 Magnets [{label}]:")
            active = [m for m in mags if not m.get('swept')]
            swept = [m for m in mags if m.get('swept')]
            for m in active:
                p = m.get('price', 0)
                s = m.get('strength', 0)
                d = m.get('dist_pct', 0)
                arw = "+" if d >= 0 else ""
                lines.append(f" 🎯 ${fmt_num(p)} str={fmt_num(s,1)}x ({arw}{d:.2f}%)")
            if not active and swept:
                lines.append("  (all swept — no active pull targets)")
            for m in swept:
                p = m.get('price', 0)
                s = m.get('strength', 0)
                d = m.get('dist_pct', 0)
                tag = "RES (swept)" if d >= 0 else "SUP (swept)"
                lines.append(f" ⤷ ${fmt_num(p)} {tag} str={fmt_num(s,1)}x ({d:+.2f}%)")
            lines.append("")
    else:
        lines.append("🧲 Magnets:")
        for i in range(1, 6):
            mp = curr.get(f"mag{i}_price", "")
            ms = curr.get(f"mag{i}_strength", "")
            md = curr.get(f"mag{i}_dist_pct", "")
            mw = curr.get(f"mag{i}_swept", "")
            if mp:
                icon = swept_icon(mw)
                lines.append(f" {icon} #{i} ${fmt_num(mp)} str={fmt_num(ms,1)}x ({fmt_pct(md)})")
        lines.append("")

    # Key Levels
    lines.append("📏 Key Levels:")
    for i in range(1, 4):
        sp = curr.get(f"sr{i}_price", "")
        st = curr.get(f"sr{i}_type", "")
        ss = curr.get(f"sr{i}_strength", "")
        if sp:
            icon = "🟢" if st.upper() == "SUPPORT" else "🔴"
            lines.append(f" {icon} {st.upper()} ${fmt_num(sp)} str={fmt_num(ss,0)}")
    lines.append("")

    # Liquidity Analysis
    lines.append("🔍 Liquidity Analysis:")
    unswept_above = 0
    unswept_below = 0
    nearest_target = None
    nearest_dist = 999
    price_f = float(price) if price != "?" else 0

    for i in range(1, 6):
        mp = curr.get(f"mag{i}_price", "")
        mw = curr.get(f"mag{i}_swept", "")
        md = curr.get(f"mag{i}_dist_pct", "")
        if mp and str(mw).upper() != "YES":
            mp_f = float(mp)
            if mp_f > price_f:
                unswept_above += 1
            else:
                unswept_below += 1
            if abs(float(md)) < abs(nearest_dist):
                nearest_dist = float(md)
                nearest_target = mp

    lines.append(f" Unswept above: {unswept_above} Unswept below: {unswept_below}")
    if nearest_target:
        lines.append(f" 🎯 Nearest target: ${fmt_num(nearest_target)} ({fmt_pct(nearest_dist)})")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    rows = read_last_n_rows(2)
    if not rows:
        print("ERROR: No data in liquidity_snapshots.csv")
        sys.exit(1)

    curr = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None

    report = generate_report(curr, prev)
    print(report)
