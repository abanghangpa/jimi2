# Liquidity Grab + Whale Watch — V3 Analysis
**Date:** 2026-07-06 13:37 GMT+8

---

## P&L Distribution Analysis (17 trades)

```
WINS (ranked):    +2.61%  +2.38%  +1.48%  +0.82%  +0.79%  +0.50%  +0.46%  +0.37%
LOSSES (ranked):  -0.22%  -0.21%  -0.20%  -0.15%  -0.13%  -0.12%  -0.11%  -0.09%
```

| Metric | Value |
|--------|-------|
| Avg Win / Avg Loss | 7.57:1 |
| Median Win / Median Loss | 5.73:1 |
| Max consecutive losses | 2 |
| Loss clustering | 1 per day, no stacking |
| **PF without top 2 wins** | **3.55** |
| PF without top 1 win | 5.47 |
| Top 2 share of PnL | 59% |

### Verdict: MODERATE DEPENDENCE — Edge is real
Even removing the two outlier wins (+2.61%, +2.38%), PF stays at 3.55.

---

## Entry Refinement: Composite Signal Testing

### Finding 1: WICK RATIO KILLS THE EDGE (HIGH CONFIDENCE)
- Wick ratio ≥1.0 → 0% WR, all trades lose
- Wick ratio ≥1.5 → 0% WR, all trades lose
- The big wins (+2.61%, +2.38%) are clean sweeps with no upper wick rejection
- **Mechanistic insight (not curve-fit):** sweep-and-continue vs sweep-and-reject are two different market behaviors. This edge lives in sweep-and-continue. This finding should survive out-of-sample.

### Finding 2: SWEEP MAGNITUDE THRESHOLD (LOW CONFIDENCE — OVERFITTING RISK)

| Config | Trades | WR | PF | PnL | Score |
|--------|--------|-----|------|-------|-------|
| Baseline (no filters) | 13 | 30.8% | 3.97 | +4.01% | 1.22 |
| +sweep 0.1 ATR | 11 | 36.4% | 6.00 | +4.44% | 2.18 |
| +sweep 0.2 ATR | 11 | 27.3% | 3.94 | +3.39% | 1.07 |

**⚠️ WARNING: Only 2 threshold values tested on 13 trades.**
- Both 0.1 and 0.2 removed the same number of trades (13→11) but different trades
- At N=11, one trade swapping in/out swings PF by 50%+
- "0.1 ATR is better than 0.2 ATR" is not supportable at this sample size
- This is the same trap as the 17-trade PF=7.57 concern — one level deeper

**What's actually supportable:**
- "Deeper sweeps outperform shallow ones" — qualitative finding, solid
- "Wick shape doesn't matter" — mechanistic finding, solid
- "0.1 ATR is the optimal cutoff" — NOT supportable, needs larger sample

**What's needed before locking in 0.1 ATR:**
1. Widen grid: test 0.05, 0.10, 0.15, 0.20, 0.25 ATR
2. Report trade count at every step
3. If PF trends smoothly → effect is real
4. If PF spikes at one value and craters → overfitting
5. Hold out validation slice if data extends further back

---

## Priority 2: Funding Rate Extremes

### Funding Rate Distribution
```
Total snapshots: 1710
Positive (longs pay): 1349 (78.9%)
Negative (shorts pay): 361 (21.1%)
Range: -0.000102 to 0.000100
Mean: 0.000035 | Median: 0.000046
P5: -0.000054 | P95: 0.000100
```

### Results

| Config | Trades | WR | PF | PnL | Score |
|--------|--------|-----|------|-------|-------|
| Baseline (no FR) | 11 | 36.4% | 6.00 | +4.44% | 2.18 |
| FR > 0.00005 (both) | 4 | 50.0% | 11.39 | +3.05% | 5.69 |
| FR > 0.0001 (wgated, TP=4x) | 14 | 28.6% | 7.76 | +6.09% | 2.22 |
| FR > 0.0001 (wgated, TP=3x) | 14 | 28.6% | 3.88 | +3.99% | 1.11 |
| FR only (no ls filter) | 14 | 28.6% | 3.88 | +3.99% | 1.11 |

### Key Findings
1. **FR > 0.00005 + both mode** — Score=5.69, PF=11.39, WR=50%. But only 4 trades (statistically meaningless).
2. **FR > 0.0001 + wgated + TP=4x/SL=0.4x** — 14 trades, PF=7.76, PnL=+6.09%. Most interesting config.
3. **FR as primary filter (no ls)** — Same results as with ls. FR alone doesn't generate signals; it filters existing ones.
4. **Funding is real triangulation** — different data source (cost-of-carry vs position count). When both agree (extreme ls + extreme funding), signal is strongest.
5. **Tradeoff:** FR > 0.00005 = best score but 4 trades. FR > 0.0001 = more trades (14) while still filtering.

---

## Architecture Summary

```
Event: liquidity_grab
  - Sweep ≥ [TBD] ATR past 20-bar swing high/low
  - Bearish/bullish close (no wick requirement)
  - Mechanism: stops triggered → fuel for reversal

State: whale conditioning
  - L/S ratio: > 2.1 SHORT, < 1.7 LONG
  - Funding rate: > 0.0001 confirms SHORT, < -0.0001 confirms LONG
  - Gated mode: event triggers, whale filters (can't disagree)
```

---

## Confidence Levels

| Finding | Confidence | Reason |
|---------|-----------|--------|
| Wick ratio kills edge | HIGH | Mechanistic, 5 trades all lose |
| Sweep magnitude matters | MEDIUM | Qualitative trend, but threshold unconfirmed |
| 0.1 ATR optimal cutoff | LOW | Grid of 2 on 13 trades, overfitting risk |
| Funding rate adds value | MEDIUM | 4-14 trades, directionally correct |
| FR > 0.0001 as threshold | LOW | Same overfitting concern as sweep magnitude |
| Event + State architecture | HIGH | Consistent across all tests |

---

## Next Steps
1. **Larger sample needed** — pull more liquidity_grab triggers (not just 13-17) to validate thresholds
2. **Wider sweep magnitude grid** — 0.05, 0.10, 0.15, 0.20, 0.25 ATR with trade counts
3. **Hold-out validation** — fit on one period, confirm on unseen bars
4. **Don't lock in 0.1 ATR yet** — treat as working hypothesis

---

## Files
- This report: `reports/liquidity_grab_whale_v3.md`
- V2 report: `reports/liquidity_grab_whale_v2.md`
- Architecture notes: `reports/strategy_architecture_notes.md`
- Original trades: `reports/whale_pair_analysis.json`
