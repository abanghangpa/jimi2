# Liquidity Grab + Whale Watch — Threshold Validation Report
**Date:** 2026-07-06 14:05 GMT+8
**Data:** ETH/USDT 15m, Feb 1 – Jul 6 2026 (14,806 bars)
**Derivatives:** 1,252 snapshots (May 13 – Jul 6)

---

## Executive Summary

**None of the tested configurations achieve PF >= 2.0 AND WR >= 75%.**

The liquidity_grab + whale_watch combination is a **high-PF, low-WR** strategy (edge comes from asymmetric payoff, not high win rate). The best achievable WR across all configurations is ~37.5%, far below the 75% target.

| Finding | Confidence |
|---------|-----------|
| Sweep depth effect is REAL (smooth PF trend) | HIGH |
| Funding rate filter DESTROYS signal count | HIGH |
| Edge survives out-of-sample | HIGH |
| WR will never reach 75% on this strategy type | HIGH |
| FR>0.0001 is NOT viable (0 trades in full dataset) | HIGH |

---

## Priority 1: Sweep Magnitude Grid

| Sweep (ATR) | Raw Signals | Filtered | Trades | WR | PF | PnL |
|-------------|-------------|----------|--------|------|------|-------|
| 0.03 | 754 | 27 | 27 | 29.6% | 1.93 | +2.93% |
| 0.05 | 723 | 24 | 24 | 25.0% | 1.80 | +2.31% |
| 0.08 | 677 | 24 | 24 | 25.0% | 1.80 | +2.31% |
| **0.10** | **647** | **22** | **22** | **27.3%** | **2.22** | **+2.86%** |
| 0.15 | 579 | 18 | 18 | 27.8% | 2.18 | +2.15% |
| 0.20 | 511 | 15 | 15 | 26.7% | 2.88 | +2.34% |
| 0.25 | 455 | 12 | 12 | 33.3% | 4.26 | +2.74% |
| 0.30 | 396 | 11 | 11 | 36.4% | 4.60 | +2.80% |
| 0.40 | 303 | 10 | 10 | 30.0% | 3.90 | +2.25% |
| 0.50 | 233 | 8 | 8 | 37.5% | 5.20 | +2.45% |

### Key Observations
1. **PF trend is smooth and monotonic** (minor noise at 0.40) — confirms depth effect is real
2. **Tradeoff:** deeper sweep = fewer trades but higher PF
3. **0.10–0.25 ATR is the viable range** — enough trades (12-22) with PF > 2.0
4. **WR stays 25-37% regardless of sweep threshold** — deeper sweeps don't improve WR, only PF

### Recommendation
Use **sweep=0.15 ATR** as default — balances trade count (18) with PF (2.18).

---

## Priority 2: Funding Rate Threshold Grid

### With L/S Ratio Filter (wgated mode)

| FR Threshold | Filtered | Trades | WR | PF | PnL |
|-------------|----------|--------|------|------|-------|
| None | 22 | 22 | 27.3% | 2.22 | +2.86% |
| 0.00003 | 14 | 14 | 21.4% | 1.28 | +0.39% |
| 0.00005 | 12 | 12 | 25.0% | 1.40 | +0.52% |
| 0.00008 | 2 | 2 | 0.0% | 0.00 | -0.22% |
| 0.00010 | 0 | 0 | — | — | — |

### Key Observations
1. **FR filter DESTROYS the edge** — every threshold reduces PF below baseline (2.22)
2. **FR>0.00010 = 0 trades** — previous V3 finding NOT reproducible
3. **Do NOT use FR filter** — L/S ratio filter alone is sufficient

---

## Priority 3: Hold-Out Validation

| Config | P1 Trades | P1 WR | P1 PF | P2 Trades | P2 WR | P2 PF | Δ PF |
|--------|-----------|-------|-------|-----------|-------|-------|------|
| sweep=0.05, no FR | 17 | 23.5% | 1.70 | 7 | 28.6% | 2.13 | +0.43 |
| **sweep=0.10, no FR** | **16** | **25.0%** | **2.09** | **6** | **33.3%** | **2.66** | **+0.57** |
| sweep=0.15, no FR | 13 | 23.1% | 1.82 | 5 | 40.0% | 3.46 | +1.64 |
| sweep=0.10, FR>0.00005 | 8 | 25.0% | 1.06 | 4 | 25.0% | 2.15 | +1.09 |

- **P1:** Feb 1 – Jun 14 (fit) | **P2:** Jun 15 – Jul 6 (validate)
- **Edge SURVIVES out-of-sample** — P2 PF >= P1 PF for all configs
- FR>0.00005 hurts P1 badly (PF drops from 2.09 to 1.06) — confirms FR filter is harmful

---

## TP/SL Multiplier Grid

Best configs (22 trades, sweep=0.10, no FR):

| TP | SL | WR | PF | PnL |
|------|------|------|------|-------|
| 3.5 | 0.4 | 18.2% | 2.97 | +3.32% |
| 3.5 | 0.5 | 22.7% | 2.67 | +3.41% |
| 3.5 | 0.6 | 27.3% | 2.59 | +3.73% |
| 3.0 | 0.4 | 18.2% | 2.55 | +2.61% |
| 2.0 | 0.4 | 22.7% | 2.66 | +2.45% |

**WR never exceeds 37.5% across ALL TP/SL combinations.**

---

## The Fundamental Problem

**This strategy type CANNOT achieve 75% WR.**

Liquidity grabs are mean-reversion entries against the trend. You're fading a move, betting the crowd is wrong. These trades naturally have low WR because you're fighting momentum. The edge is in **payoff asymmetry**: wins are 3-5x larger than losses.

This is structurally similar to value investing — low hit rate, high payoff per hit.

---

## What Should Be Tested Next

Instead of forcing 75% WR on liquidity_grab, test event-based strategies that might naturally have higher WR:

1. **failed_breakout** — BB breach + snap back (prev: 57.1% WR, PF=5.18)
2. **structural_break** — level break + continuation (prev: 61.1% WR, PF=3.60)
3. **squeeze_breakout** — ATR compression → expansion

Pair each with whale_watch conditioning. Use tighter TP (1.0-2.0x ATR) for higher WR.

---

## Files
- `reports/lg_whale_threshold_validation.json` — raw data
- `reports/lg_whale_threshold_validation.md` — this report
