# Whale Watch Pairing Analysis Report
**Date:** 2026-07-06
**Period:** Feb 1, 2026 → Jul 6, 2026
**Data:** ETH/USDT 15m (14,800 bars), Derivatives L/S ratio (May 13 → Jul 6)

---

## Executive Summary

Whale_watch strategy was tested standalone and paired with all 21 other strategies (6 enabled + 15 disabled). **No configuration achieved PF≥2.0 AND WR≥75%.** The L/S ratio is a sentiment indicator, not a timing indicator.

**Action taken:** whale_watch DISABLED in live executor (scanner_executor.py)

---

## Standalone Whale Watch Analysis

| Metric | Value |
|--------|-------|
| Total signals | 1,503 |
| Win Rate | 52.0% |
| Profit Factor | 1.71 |
| Total PnL | +210.23% |
| Data coverage | 11.4% (derivatives only from May 13) |
| Signals/day | ~27 (massive over-trading) |

### Key Issues
1. **Data gap:** No derivatives for Feb-May (88.6% of period)
2. **Over-trading:** Fires on every 15m bar when whales positioned
3. **LONG weakness:** 49.3% WR on LONG vs 52.9% on SHORT
4. **No cooldown:** Consecutive signals within minutes

---

## Pairing Results — Enabled Strategies

| Pair | Trades | WR | PF | PnL | Score |
|------|--------|-----|------|-------|-------|
| whale + failed_breakout | 7 | 57.1% | 5.18 | +3.07% | 2.96 |
| whale + structural_break | 36 | 61.1% | 3.60 | +8.51% | 2.20 |
| whale + trend_follow | 84 | 40.5% | 3.17 | +30.18% | 1.28 |
| whale + positioning_fade | 70 | 35.7% | 2.38 | +19.03% | 0.85 |
| whale + orderbook_imbalance | 57 | 31.6% | 2.30 | +9.34% | 0.73 |
| whale + regime_switch | 3 | 33.3% | 1.75 | +0.23% | 0.58 |

---

## Pairing Results — Disabled Strategies

| Pair | Trades | WR | PF | PnL | Score |
|------|--------|-----|------|-------|-------|
| whale + liquidity_grab | 17 | 47.1% | 7.57 | +8.41% | 3.57 |
| whale + momentum_v2 | 8 | 62.5% | 7.11 | — | 4.44 |
| whale + squeeze_breakout | 13 | 23.1% | 1.12 | +0.26% | 0.26 |
| whale + macro_surprise | 23 | 39.1% | 1.72 | +3.16% | 0.67 |
| whale + judas_sweep | 9 | 55.6% | 5.06 | — | 2.81 |
| whale + liquidity_grab | 14 | 64.3% | 8.32 | — | 5.35 |
| whale + squeeze_breakout | 14 | 64.3% | 4.53 | — | 2.91 |
| whale + macro_surprise | 19 | 63.2% | 3.08 | — | 1.95 |

*Note: Bottom 3 rows are from simplified signal generators (grid search), not full strategy implementations.*

---

## Top 3 Pairings — Detailed Analysis

### 1. LIQUIDITY_GRAB + WHALE WATCH ⭐ Best

**Config:**
- Whale SHORT when L/S ratio > 2.1
- Whale LONG when L/S ratio < 1.7
- Cooldown: 24 bars (6 hours)
- Take Profit: 3.0x ATR
- Stop Loss: 0.6x ATR (TP:SL = 5:1)
- Max Hold: 48 bars (12 hours)
- EMA200 Trend Filter: ON

**Performance: 17 trades | 8W/8L | WR=47.1% | PF=7.57 | PnL=+8.41%**

All Trades:
| Result | Date | Dir | Entry | Exit | PnL | L/S Ratio | Bars |
|--------|------|-----|-------|------|-----|-----------|------|
| WIN | 2026-06-02 11:00 | SHORT | $1982.49 | $1966.79 | +0.79% | 2.9139 | 13 |
| WIN | 2026-06-05 09:15 | SHORT | $1680.64 | $1640.68 | +2.38% | 2.5868 | 18 |
| WIN | 2026-06-25 16:15 | SHORT | $1576.97 | $1535.84 | +2.61% | 2.5625 | 40 |
| WIN | 2026-06-25 23:30 | SHORT | $1577.38 | $1564.48 | +0.82% | 2.6456 | 8 |
| LOSS | 2026-06-26 06:45 | SHORT | $1570.24 | $1573.65 | -0.22% | 2.4223 | 2 |
| TIME | 2026-06-26 15:45 | SHORT | $1584.76 | $1580.69 | +0.26% | 2.2331 | 48 |
| LOSS | 2026-06-27 21:15 | SHORT | $1583.99 | $1585.47 | -0.09% | 2.1486 | 1 |
| LOSS | 2026-06-28 07:45 | SHORT | $1574.75 | $1576.48 | -0.11% | 2.2992 | 4 |
| WIN | 2026-06-28 20:30 | SHORT | $1573.85 | $1565.98 | +0.50% | 2.3367 | 6 |
| LOSS | 2026-06-30 14:00 | SHORT | $1566.78 | $1569.98 | -0.20% | 2.6643 | 1 |
| WIN | 2026-06-30 20:15 | SHORT | $1581.31 | $1575.53 | +0.37% | 2.5651 | 2 |
| LOSS | 2026-07-01 09:00 | SHORT | $1579.41 | $1581.48 | -0.13% | 2.3887 | 1 |
| WIN | 2026-07-02 16:30 | LONG | $1690.35 | $1715.39 | +1.48% | 1.5407 | 37 |
| LOSS | 2026-07-03 14:15 | LONG | $1734.99 | $1732.39 | -0.15% | 1.6008 | 7 |
| WIN | 2026-07-04 06:30 | LONG | $1754.72 | $1762.71 | +0.46% | 1.5954 | 10 |
| LOSS | 2026-07-04 22:15 | LONG | $1786.93 | $1784.73 | -0.12% | 1.6490 | 3 |
| LOSS | 2026-07-06 00:00 | LONG | $1786.61 | $1782.82 | -0.21% | 1.6824 | 2 |

**Why it works:** Extreme TP:SL ratio (5:1). Wins average +1.05%, losses average -0.15%. Only needs 1 win per 7 losses to break even.

---

### 2. SQUEEZE_BREAKOUT + WHALE WATCH

**Config:**
- Whale SHORT when L/S ratio > 2.3, LONG when < 1.9
- Cooldown: 16 bars (4 hours)
- TP: 3.0x ATR | SL: 0.8x ATR | Hold: 32 bars | Trend: ON

**Performance: 13 trades | 3W/10L | WR=23.1% | PF=1.12 | PnL=+0.26%**

❌ NOT VIABLE — too many losses, barely profitable.

---

### 3. MACRO_SURPRISE + WHALE WATCH

**Config:**
- Whale SHORT when L/S ratio > 2.2, LONG when < 1.8
- Cooldown: 24 bars (6 hours)
- TP: 2.5x ATR | SL: 0.8x ATR | Hold: 48 bars | Trend: ON

**Performance: 23 trades | 9W/14L | WR=39.1% | PF=1.72 | PnL=+3.16%**

Notable wins: +1.94% (Jun 4), +1.72% (Jun 5), +0.79% (Jul 2)

⚠️ MARGINAL — PF below 2.0 target.

---

## Recommendations

1. **whale_watch should remain DISABLED** — cannot meet PF≥2.0 + WR≥75% alone or paired
2. **liquidity_grab + whale** is the only viable combo (PF=7.57) but WR is only 47%
3. Consider using whale as a **confirmation filter** rather than a signal generator
4. **Backfill derivatives data** for Feb-May to enable proper full-period testing
5. Move analysis to next standalone strategy: **failed_breakout**, **structural_break**, or **positioning_fade**

---

## Files
- Detailed JSON: `reports/whale_pair_analysis.json`
- This report: `reports/whale_pair_findings.md`
- whale_watch disabled in: `scripts/scanner_executor.py`
