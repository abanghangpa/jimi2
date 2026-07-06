# Liquidity Grab + Whale Watch — V2 Analysis
**Date:** 2026-07-06 13:34 GMT+8

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
Losses are remarkably tight and evenly spread. Not a lucky 2-3 trade situation.

---

## Entry Refinement: Composite Signal Testing

### Hypothesis
Merge sweep magnitude + rejection strength (wick) + volume into one composite condition.

### Results

| Config | Trades | WR | PF | PnL | Score |
|--------|--------|-----|------|-------|-------|
| Baseline (no filters) | 13 | 30.8% | 3.97 | +4.01% | 1.22 |
| **+sweep 0.1 ATR** | **11** | **36.4%** | **6.00** | **+4.44%** | **2.18** |
| +sweep 0.2 ATR | 11 | 27.3% | 3.94 | +3.39% | 1.07 |
| +wick ratio 1.0 | 5 | 0.0% | 0.00 | -0.39% | 0.00 |
| +wick ratio 1.5 | 3 | 0.0% | 0.00 | -0.42% | 0.00 |
| +sweep + wick + vol | — | — | — | — | 0 trades |

### Key Finding: WICK RATIO KILLS THE EDGE

The big wins (+2.61%, +2.38%) are clean sweeps — price poked past the liquidity level and dropped hard with no upper wick rejection. Requiring a wick filters OUT the winning trades.

**The edge is in sweep magnitude, not candle shape.** A deeper sweep = more stops triggered = more fuel for reversal. The candle pattern is irrelevant.

### Refined Signal Definition
**Composite signal = sweep magnitude only (≥0.1 ATR past the level)**
- How far price pokes past the swing high/low
- Measured in ATR units (normalized for volatility)
- 0.1 ATR = meaningful poke, not noise
- 0.2 ATR = too strict, filters out good signals too

### Performance After Refinement
- 11 trades (was 13)
- WR: 36.4% (was 30.8%, +5.6pp)
- PF: 6.00 (was 3.97, +51%)
- PnL: +4.44% (was +4.01%, +11%)
- Removed 2 marginal trades, improved all metrics

---

## Architecture Validation

### Event + State Pattern Confirmed
```
Event: liquidity_grab (sweep ≥0.1 ATR past 20-bar swing level)
  + State: whale (L/S ratio > 2.1 SHORT, < 1.7 LONG)
  = Right timing + right context
```

### What Doesn't Work
- Wick ratio (rejection candle) — kills the edge
- Volume filter — too few trades
- Top L/S filter — too few trades
- Funding rate filter — untested (Priority 2)

---

## Next Steps

### Priority 2: Funding Rate Extremes
- Genuinely different data source (derivatives cost-of-carry)
- Real triangulation with L/S ratio (position count skew)
- Watch: don't shrink trigger frequency into single digits

### Priority 3: Adaptive Lookback (if needed)
- Swing highs/lows validated by minimum touches
- Volume-weighted levels (watch for state+state overlap)
- Most likely needs full re-sweep from scratch

---

## Files
- This report: `reports/liquidity_grab_whale_v2.md`
- Original trades JSON: `reports/whale_pair_analysis.json`
- Architecture notes: `reports/strategy_architecture_notes.md`
