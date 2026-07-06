#!/usr/bin/env python3
"""
Synthetic Derivatives Data Generator
=====================================
Fills the gap: Feb 1 - May 12, 2026 (100 days, ~9600 15m bars)
Real derivatives data: May 13 - Jul 6, 2026

Creates MULTIPLE scenario datasets, each covering a different market regime.
Every scenario has its own ls_ratio, funding_rate, oi patterns.
Strategy must work across ALL scenarios to be considered robust.

Scenarios:
1. EXTREME_BULL — crowd heavily long, high FR, euphoria
2. EXTREME_BEAR — crowd heavily short, negative FR, panic
3. NEUTRAL_LOW_VOL — ls near 1.0, FR near 0, low OI
4. HIGH_OI_CRASH — extreme OI buildup then liquidation cascade
5. REGIME_TRANSITIONS — alternating bull/bear phases
6. MEDIAN — median of real data, steady state
7. WORST_CASE — maximum noise, worst possible fills
"""

import csv, os, sys, json, random
from datetime import datetime, timedelta
import numpy as np

BASE = "/root/.openclaw/workspace/jimi_audit"
DERIV_FILE = os.path.join(BASE, "data", "derivatives_history", "derivatives_collected.csv")
OUT_DIR = os.path.join(BASE, "data", "derivatives_synthetic")
os.makedirs(OUT_DIR, exist_ok=True)

# ============================================================
# LOAD REAL DATA TO EXTRACT STATISTICS
# ============================================================

def load_real_deriv():
    rows = []
    with open(DERIV_FILE) as f:
        for row in csv.DictReader(f):
            rows.append({
                'ls_ratio': float(row['ls_ratio']),
                'funding_rate': float(row['funding_rate']),
                'oi': float(row['oi']),
                'oi_usd': float(row['oi_usd']),
            })
    return rows

def compute_stats(rows):
    ls = [r['ls_ratio'] for r in rows]
    fr = [r['funding_rate'] for r in rows]
    oi = [r['oi'] for r in rows]
    oi_usd = [r['oi_usd'] for r in rows]
    
    def percentiles(arr):
        a = np.array(arr)
        return {
            'min': float(np.min(a)),
            'p5': float(np.percentile(a, 5)),
            'p10': float(np.percentile(a, 10)),
            'p25': float(np.percentile(a, 25)),
            'median': float(np.median(a)),
            'mean': float(np.mean(a)),
            'p75': float(np.percentile(a, 75)),
            'p95': float(np.percentile(a, 95)),
            'max': float(np.max(a)),
            'std': float(np.std(a)),
        }
    
    return {
        'ls_ratio': percentiles(ls),
        'funding_rate': percentiles(fr),
        'oi': percentiles(oi),
        'oi_usd': percentiles(oi_usd),
    }

# ============================================================
# GENERATE SYNTHETIC SNAPSHOTS
# ============================================================

def generate_snapshots(scenario_name, n_snapshots, ls_gen, fr_gen, oi_gen, oi_usd_gen):
    """Generate n_snapshots for a scenario. Each generator returns value at time t."""
    snapshots = []
    # Time range: Feb 1 - May 12, 2026
    start = datetime(2026, 2, 1)
    end = datetime(2026, 5, 13)
    total_minutes = int((end - start).total_seconds() / 60)
    
    for i in range(n_snapshots):
        t_frac = i / n_snapshots  # 0 to 1
        dt = start + timedelta(minutes=int(t_frac * total_minutes))
        
        snapshots.append({
            'timestamp': dt.isoformat(),
            'timestamp_ms': int(dt.timestamp() * 1000),
            'ls_ratio': round(ls_gen(t_frac, i), 4),
            'long_pct': 0,  # derived below
            'short_pct': 0,
            'top_ls_ratio': 0,  # derived below
            'top_long_pct': 0,
            'top_short_pct': 0,
            'futures_taker_ratio': 1.0,
            'futures_buy_vol': 0,
            'futures_sell_vol': 0,
            'oi': round(oi_gen(t_frac, i), 2),
            'oi_usd': round(oi_usd_gen(t_frac, i), 2),
            'funding_rate': round(fr_gen(t_frac, i), 8),
        })
    
    # Derive long_pct/short_pct from ls_ratio
    for s in snapshots:
        ls = s['ls_ratio']
        s['long_pct'] = round(ls / (1 + ls), 4)
        s['short_pct'] = round(1 / (1 + ls), 4)
        # top_ls_ratio ~ ls_ratio with slight offset
        s['top_ls_ratio'] = round(ls * (0.85 + random.random() * 0.15), 4)
        s['top_long_pct'] = round(s['top_ls_ratio'] / (1 + s['top_ls_ratio']), 4)
        s['top_short_pct'] = round(1 / (1 + s['top_ls_ratio']), 4)
    
    return snapshots

def save_scenario(name, snapshots):
    """Save scenario as CSV in the same format as real data."""
    path = os.path.join(OUT_DIR, f"derivatives_{name}.csv")
    fieldnames = ['timestamp', 'timestamp_ms', 'oi', 'oi_usd', 'ls_ratio',
                  'long_pct', 'short_pct', 'top_ls_ratio', 'top_long_pct',
                  'top_short_pct', 'futures_taker_ratio', 'futures_buy_vol',
                  'futures_sell_vol', 'funding_rate']
    
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(snapshots)
    
    print(f"  Saved {len(snapshots)} snapshots → {path}")
    return path

# ============================================================
# SCENARIO DEFINITIONS
# ============================================================

def make_scenario(name, stats, n=960):
    """
    Create a scenario. n=960 = ~10 days of 15-min snapshots.
    We generate 960 snapshots per scenario (~10 days spacing over 100 days).
    """
    
    ls = stats['ls_ratio']
    fr = stats['funding_rate']
    oi = stats['oi']
    oi_usd = stats['oi_usd']
    
    scenarios = {
        # ─── EXTREME_BULL ───────────────────────────────────────
        # Crowd heavily long, high positive FR, high OI
        # ls_ratio: 2.5-4.0 (extreme long crowding)
        # funding_rate: 0.0001-0.0005 (longs paying shorts)
        # OI: high (p75-max)
        'extreme_bull': {
            'ls_gen': lambda t, i: 2.5 + 1.5 * np.sin(t * np.pi * 2) + np.random.normal(0, 0.15),
            'fr_gen': lambda t, i: 0.0001 + 0.0004 * abs(np.sin(t * np.pi * 3)) + np.random.normal(0, 0.00002),
            'oi_gen': lambda t, i: oi['p75'] + (oi['max'] - oi['p75']) * 0.5 * (1 + np.sin(t * np.pi * 2)),
            'oi_usd_gen': lambda t, i: oi_usd['p75'] + (oi_usd['max'] - oi_usd['p75']) * 0.5 * (1 + np.sin(t * np.pi * 2)),
        },
        
        # ─── EXTREME_BEAR ───────────────────────────────────────
        # Crowd heavily short, negative FR, declining OI
        # ls_ratio: 0.3-0.7 (extreme short crowding)
        # funding_rate: -0.0005 to -0.0001 (shorts paying longs)
        # OI: declining from p50 to p10
        'extreme_bear': {
            'ls_gen': lambda t, i: 0.5 - 0.2 * np.sin(t * np.pi * 2) + np.random.normal(0, 0.05),
            'fr_gen': lambda t, i: -0.0001 - 0.0004 * abs(np.sin(t * np.pi * 3)) + np.random.normal(0, 0.00002),
            'oi_gen': lambda t, i: oi['median'] * (1 - 0.3 * t) + np.random.normal(0, oi['std'] * 0.1),
            'oi_usd_gen': lambda t, i: oi_usd['median'] * (1 - 0.3 * t) + np.random.normal(0, oi_usd['std'] * 0.1),
        },
        
        # ─── NEUTRAL_LOW_VOL ────────────────────────────────────
        # ls near 1.0, FR near 0, low OI, no conviction
        # ls_ratio: 0.9-1.1 (balanced)
        # funding_rate: -0.00003 to 0.00003 (flat)
        # OI: low (p10-p25)
        'neutral_low_vol': {
            'ls_gen': lambda t, i: 1.0 + np.random.normal(0, 0.05),
            'fr_gen': lambda t, i: np.random.normal(0, 0.00001),
            'oi_gen': lambda t, i: oi['p10'] + (oi['p25'] - oi['p10']) * random.random(),
            'oi_usd_gen': lambda t, i: oi_usd['p10'] + (oi_usd['p25'] - oi_usd['p10']) * random.random(),
        },
        
        # ─── HIGH_OI_CRASH ──────────────────────────────────────
        # OI builds to extreme, then liquidation cascade
        # Phase 1 (0-0.6): OI rises, ls shifts to extreme long, FR rises
        # Phase 2 (0.6-0.8): CRASH — ls reverses, FR spikes negative, OI drops
        # Phase 3 (0.8-1.0): Recovery — ls normalizes
        'high_oi_crash': {
            'ls_gen': lambda t, i: (2.0 + np.random.normal(0, 0.1)) if t < 0.6 else (0.5 + np.random.normal(0, 0.1)) if t < 0.8 else (1.2 + np.random.normal(0, 0.1)),
            'fr_gen': lambda t, i: (0.0002 + np.random.normal(0, 0.00002)) if t < 0.6 else (-0.0003 + np.random.normal(0, 0.00005)) if t < 0.8 else (0.00005 + np.random.normal(0, 0.00001)),
            'oi_gen': lambda t, i: (oi['p95'] * (0.8 + 0.4 * t / 0.6) + np.random.normal(0, oi['std'] * 0.1)) if t < 0.6 else (oi['p95'] * 1.2 * (1 - (t - 0.6) / 0.2 * 0.5) + np.random.normal(0, oi['std'] * 0.2)) if t < 0.8 else (oi['median'] + np.random.normal(0, oi['std'] * 0.1)),
            'oi_usd_gen': lambda t, i: (oi_usd['p95'] * (0.8 + 0.4 * t / 0.6)) if t < 0.6 else (oi_usd['p95'] * 1.2 * (1 - (t - 0.6) / 0.2 * 0.5)) if t < 0.8 else oi_usd['median'],
        },
        
        # ─── REGIME_TRANSITIONS ─────────────────────────────────
        # 5 phases: bull → bear → neutral → bull → bear
        # Each phase ~20% of the time
        'regime_transitions': {
            'ls_gen': lambda t, i: (
                2.0 + np.random.normal(0, 0.1) if t < 0.2 else
                0.6 + np.random.normal(0, 0.1) if t < 0.4 else
                1.0 + np.random.normal(0, 0.05) if t < 0.6 else
                1.8 + np.random.normal(0, 0.1) if t < 0.8 else
                0.5 + np.random.normal(0, 0.1)
            ),
            'fr_gen': lambda t, i: (
                0.00015 + np.random.normal(0, 0.00002) if t < 0.2 else
                -0.0001 + np.random.normal(0, 0.00002) if t < 0.4 else
                np.random.normal(0, 0.00001) if t < 0.6 else
                0.00012 + np.random.normal(0, 0.00002) if t < 0.8 else
                -0.00015 + np.random.normal(0, 0.00002)
            ),
            'oi_gen': lambda t, i: oi['median'] * (0.8 + 0.4 * abs(np.sin(t * np.pi * 5))),
            'oi_usd_gen': lambda t, i: oi_usd['median'] * (0.8 + 0.4 * abs(np.sin(t * np.pi * 5))),
        },
        
        # ─── MEDIAN ─────────────────────────────────────────────
        # Steady state at median values with realistic noise
        'median': {
            'ls_gen': lambda t, i: ls['median'] + np.random.normal(0, ls['std'] * 0.3),
            'fr_gen': lambda t, i: fr['median'] + np.random.normal(0, fr['std'] * 0.3),
            'oi_gen': lambda t, i: oi['median'] + np.random.normal(0, oi['std'] * 0.2),
            'oi_usd_gen': lambda t, i: oi_usd['median'] + np.random.normal(0, oi_usd['std'] * 0.2),
        },
        
        # ─── MEAN ───────────────────────────────────────────────
        # Steady state at mean values
        'mean': {
            'ls_gen': lambda t, i: ls['mean'] + np.random.normal(0, ls['std'] * 0.3),
            'fr_gen': lambda t, i: fr['mean'] + np.random.normal(0, fr['std'] * 0.3),
            'oi_gen': lambda t, i: oi['mean'] + np.random.normal(0, oi['std'] * 0.2),
            'oi_usd_gen': lambda t, i: oi_usd['mean'] + np.random.normal(0, oi_usd['std'] * 0.2),
        },
        
        # ─── WORST_CASE_ADVERSE ─────────────────────────────────
        # Every signal fires at the worst possible ls/fr combination
        # Whale signals fire when ls is at its MOST unfavorable
        # Deliberately adversarial — if strategy survives this, it's robust
        'worst_case_adverse': {
            'ls_gen': lambda t, i: (
                # Flip between extreme values to maximize false signals
                3.0 + np.random.normal(0, 0.2) if (i % 100) < 50 else
                0.4 + np.random.normal(0, 0.1)
            ),
            'fr_gen': lambda t, i: (
                0.0003 + np.random.normal(0, 0.00005) if (i % 100) < 50 else
                -0.0002 + np.random.normal(0, 0.00005)
            ),
            'oi_gen': lambda t, i: oi['p95'] * (1 + 0.1 * np.sin(i * 0.1)),
            'oi_usd_gen': lambda t, i: oi_usd['p95'] * (1 + 0.1 * np.sin(i * 0.1)),
        },
        
        # ─── LOW_LS_RANGE ───────────────────────────────────────
        # ls_ratio always between 1.5-2.0 (near threshold)
        # Tests sensitivity at the decision boundary
        'low_ls_range': {
            'ls_gen': lambda t, i: 1.5 + 0.5 * abs(np.sin(t * np.pi * 4)) + np.random.normal(0, 0.05),
            'fr_gen': lambda t, i: fr['median'] + np.random.normal(0, fr['std'] * 0.5),
            'oi_gen': lambda t, i: oi['median'] + np.random.normal(0, oi['std'] * 0.3),
            'oi_usd_gen': lambda t, i: oi_usd['median'] + np.random.normal(0, oi_usd['std'] * 0.3),
        },
        
        # ─── HIGH_LS_RANGE ──────────────────────────────────────
        # ls_ratio always between 2.0-3.0 (always in whale SHORT zone)
        # Should always trigger SHORT signals
        'high_ls_range': {
            'ls_gen': lambda t, i: 2.0 + 1.0 * abs(np.sin(t * np.pi * 3)) + np.random.normal(0, 0.1),
            'fr_gen': lambda t, i: 0.00005 + 0.0001 * abs(np.sin(t * np.pi * 2)) + np.random.normal(0, 0.00001),
            'oi_gen': lambda t, i: oi['p75'] + np.random.normal(0, oi['std'] * 0.2),
            'oi_usd_gen': lambda t, i: oi_usd['p75'] + np.random.normal(0, oi_usd['std'] * 0.2),
        },
    }
    
    if name not in scenarios:
        print(f"  Unknown scenario: {name}")
        return None
    
    s = scenarios[name]
    return generate_snapshots(name, n, s['ls_gen'], s['fr_gen'], s['oi_gen'], s['oi_usd_gen'])

# ============================================================
# MERGE WITH REAL DATA
# ============================================================

def merge_with_real(synthetic_csv, real_csv, output_csv):
    """Merge synthetic (Feb-May) with real (May-Jul) derivatives data."""
    rows = []
    
    # Read synthetic
    with open(synthetic_csv) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    
    # Read real
    with open(real_csv) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    
    # Sort by timestamp
    rows.sort(key=lambda r: r['timestamp'])
    
    # Write merged
    fieldnames = list(rows[0].keys())
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"  Merged {len(rows)} total snapshots → {output_csv}")

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("SYNTHETIC DERIVATIVES DATA GENERATOR")
    print("=" * 70)
    
    print("\n[1] Loading real derivatives statistics...")
    real = load_real_deriv()
    stats = compute_stats(real)
    
    print("\n  Real data statistics:")
    for field, s in stats.items():
        print(f"    {field}:")
        print(f"      min={s['min']:.6f} p5={s['p5']:.6f} median={s['median']:.6f} mean={s['mean']:.6f} p95={s['p95']:.6f} max={s['max']:.6f}")
    
    scenario_names = [
        'extreme_bull',
        'extreme_bear',
        'neutral_low_vol',
        'high_oi_crash',
        'regime_transitions',
        'median',
        'mean',
        'worst_case_adverse',
        'low_ls_range',
        'high_ls_range',
    ]
    
    print(f"\n[2] Generating {len(scenario_names)} scenarios...")
    
    for name in scenario_names:
        print(f"\n  --- {name} ---")
        snapshots = make_scenario(name, stats, n=960)
        if snapshots:
            # Clamp values to realistic ranges
            for s in snapshots:
                s['ls_ratio'] = max(0.1, min(10.0, s['ls_ratio']))
                s['funding_rate'] = max(-0.001, min(0.001, s['funding_rate']))
                s['oi'] = max(0, s['oi'])
                s['oi_usd'] = max(0, s['oi_usd'])
            
            # Save standalone
            save_scenario(name, snapshots)
            
            # Merge with real data and save
            synth_path = os.path.join(OUT_DIR, f"derivatives_{name}.csv")
            merged_path = os.path.join(OUT_DIR, f"derivatives_{name}_merged.csv")
            merge_with_real(synth_path, DERIV_FILE, merged_path)
    
    print(f"\n[3] Done. {len(scenario_names)} scenario files saved to {OUT_DIR}/")
    print("\nEach file has format: derivatives_{scenario}_merged.csv")
    print("These cover Feb 1 - Jul 6, 2026 (synthetic Feb-May + real May-Jul)")
    print("\nTo test a scenario, replace the derivatives_collected.csv with")
    print("the scenario file and re-run the backtest.")
    
    # Save scenario descriptions
    desc = {}
    for name in scenario_names:
        s = snapshots  # last one
        desc[name] = {
            'description': f"Synthetic scenario: {name}",
            'period': 'Feb 1 - May 12, 2026 (synthetic) + May 13 - Jul 6 (real)',
            'snapshots': 960,
        }
    
    # Write summary
    summary_path = os.path.join(OUT_DIR, "README.md")
    with open(summary_path, 'w') as f:
        f.write("# Synthetic Derivatives Scenarios\n\n")
        f.write("Fill the gap: Feb 1 - May 12, 2026 (no real derivatives data).\n")
        f.write("Each scenario covers a different market regime.\n\n")
        f.write("## Scenarios\n\n")
        f.write("| Scenario | ls_ratio range | FR range | Description |\n")
        f.write("|---|---|---|---|\n")
        f.write("| extreme_bull | 2.5-4.0 | +0.0001 to +0.0005 | Crowd heavily long, euphoria |\n")
        f.write("| extreme_bear | 0.3-0.7 | -0.0005 to -0.0001 | Crowd heavily short, panic |\n")
        f.write("| neutral_low_vol | 0.9-1.1 | ~0 | Balanced, no conviction |\n")
        f.write("| high_oi_crash | 2.0→0.5→1.2 | +0.0002→-0.0003→+0.00005 | OI buildup then cascade |\n")
        f.write("| regime_transitions | 0.5-2.0 | -0.00015 to +0.00015 | 5 alternating phases |\n")
        f.write("| median | ~1.8 | ~0.000046 | Steady at real median |\n")
        f.write("| mean | ~1.7 | ~0.000035 | Steady at real mean |\n")
        f.write("| worst_case_adverse | 0.4-3.0 | -0.0002 to +0.0003 | Adversarial flipping |\n")
        f.write("| low_ls_range | 1.5-2.0 | median | Near threshold boundary |\n")
        f.write("| high_ls_range | 2.0-3.0 | +0.00005 to +0.00015 | Always in SHORT zone |\n")
        f.write("\n## Usage\n\n")
        f.write("```bash\n")
        f.write("# Test a scenario:\n")
        f.write("cp data/derivatives_synthetic/derivatives_{scenario}_merged.csv data/derivatives_history/derivatives_collected.csv\n")
        f.write("python3 scripts/validate_v5.py\n")
        f.write("# Then restore original:\n")
        f.write("cp data/derivatives_history/derivatives_collected.csv.backup data/derivatives_history/derivatives_collected.csv\n")
        f.write("```\n")
    
    print(f"\n  Summary: {summary_path}")
