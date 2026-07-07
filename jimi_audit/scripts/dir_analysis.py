#!/usr/bin/env python3
"""Analyze direction logic for each strategy."""
import os
import re

STRATS = [
    ("momentum_v2", "s18_momentum_v2.py"),
    ("failed_breakout", "s01_failed_breakout.py"),
    ("squeeze_breakout", "s02_squeeze_breakout.py"),
    ("kill_zone", "s05_kill_zone.py"),
    ("cross_asset", "s11_cross_asset.py"),
    ("whale_watch", "s14_whale_watch.py"),
    ("vol_rotation", "s15_vol_rotation.py"),
    ("positioning_fade", "s04_positioning_fade.py"),
    ("taker_flow", "s07_taker_flow.py"),
]

BASE = "/root/.openclaw/workspace/jimi_audit/src/strategies"

for name, fname in STRATS:
    path = os.path.join(BASE, fname)
    if not os.path.exists(path):
        print(f"\n{'='*60}")
        print(f"{name}: FILE NOT FOUND")
        continue
    
    with open(path) as f:
        content = f.read()
    
    print(f"\n{'='*60}")
    print(f"DIRECTION LOGIC: {name}")
    print(f"{'='*60}")
    
    # Find all lines that set direction
    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Look for direction assignment
        if 'direction' in stripped and ('=' in stripped or 'LONG' in stripped or 'SHORT' in stripped):
            # Print context: 3 lines before, the line, 3 lines after
            start = max(0, i-2)
            end = min(len(lines), i+3)
            for j in range(start, end):
                marker = ">>>" if j == i else "   "
                print(f"  {marker} L{j+1}: {lines[j]}")
            print()
