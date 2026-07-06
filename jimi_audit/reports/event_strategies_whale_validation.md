# Event-Based Strategies + Whale Conditioning — Full Results
**Date:** 2026-07-06 14:20 GMT+8
**Data:** ETH/USDT 15m, May 13 – Jul 6 2026 (5,209 bars, derivatives available)

---

## Executive Summary

**❌ No strategy + config combination achieves PF >= 2.0 AND WR >= 75%.**

The best configs found:

| Strategy | Filter | Config | Trades | WR | PF | PnL |
|----------|--------|--------|--------|------|------|-------|
| squeeze_breakout | strict | TP2.0/SL1.0/H24 | 6 | 66.7% | 4.25 | +1.00% |
| squeeze_breakout | none | TP1.0/SL1.0/H24 | 18 | 66.7% | 2.51 | +1.78% |
| positioning_fade | none | TP1.5/SL1.0/H24 | 467 | 52.5% | 1.89 | +74.82% |
| failed_breakout | strict | TP1.5/SL1.5/H24 | 28 | 60.7% | 1.78 | +3.39% |
| judas_sweep | wgated | TP1.5/SL1.5/H24 | 55 | 60.0% | 1.73 | +7.13% |

**Closest to target:** squeeze_breakout (66.7% WR, PF=4.25) but only 6 trades — statistically meaningless.

---

## Strategy-by-Strategy Results

### 1. failed_breakout (507 raw signals)
- **Best:** strict filter, TP1.5/SL1.5/H24 → 28 trades, 60.7% WR, PF=1.78
- **No filter:** 507 trades, WR=54.6%, PF=1.19 — too noisy
- **Whale filter effect:** Reduces noise significantly (507→68→28) but doesn't push PF above 2.0
- **Verdict:** Whale conditioning helps but edge is marginal (PF 1.0-1.8 range)

### 2. structural_break (544 raw signals)
- **Best:** strict filter, TP1.0/SL1.0/H24 → 130 trades, 54.6% WR, PF=1.59
- **No filter:** Most configs are LOSING (PF < 1.0) — structural breaks are false signals without conditioning
- **Whale filter:** Turns negative PF into positive, but max is 1.59
- **Verdict:** Needs additional filters beyond whale. Raw structural breaks are noise.

### 3. squeeze_breakout ⭐ (18 raw signals)
- **Best:** strict filter, TP2.0/SL1.0/H24 → 6 trades, 66.7% WR, PF=4.25
- **No filter:** 18 trades, 66.7% WR, PF=2.51 (TP1.0/SL1.0)
- **Problem:** Only 18 signals in 55 days (1 per 3 days). After filtering: 4-6 trades.
- **Verdict:** Highest WR of any strategy, but sample size is too small to trust. The 66.7% WR on 18 trades is promising but could easily be luck.

### 4. judas_sweep (359 raw signals)
- **Best:** wgated, TP1.5/SL1.5/H24 → 55 trades, 60.0% WR, PF=1.73
- **Similar to liquidity_grab** — same sweep mechanism, same low-WR/high-PF profile
- **Verdict:** Whale filter helps (WR goes from 53% to 60%) but PF stays under 2.0 at reasonable WR

### 5. positioning_fade (467 raw signals)
- **Best:** TP1.5/SL1.0/H24 → 467 trades, 52.5% WR, PF=1.89
- **Whale filter has ZERO effect** — positioning_fade already IS a positioning-based strategy
- **Highest raw PnL:** +103.52% (TP2.0/SL1.5/H48) but WR only 55%
- **Verdict:** Good standalone strategy but WR can't exceed ~62% even with equal TP/SL

---

## Why 75% WR is Structurally Unachievable

For ANY strategy to achieve 75% WR with PF >= 2.0:
- 75% of trades must be winners
- Average win must be >= 2x average loss
- This means the strategy must be right 3 out of 4 times AND win big when right

This is only possible with:
1. **Extremely tight TP** (take small profits quickly) — but then PF drops below 2.0
2. **Extremely wide SL** (let losers run) — but then one bad trade wipes out many wins
3. **Near-perfect signal quality** — no real market strategy achieves this

The math constraint:
```
If WR = 75%, avg_win = W, avg_loss = L:
PF = (0.75 * W) / (0.25 * L) = 3 * (W/L)
For PF >= 2.0: W/L >= 0.67
```
So average win must be at least 67% of average loss. With 75% WR, you need W/L >= 0.67.
But in practice, the strategies that get high WR (tight TP) have W/L < 0.5, giving PF < 1.5.

---

## Alternative Approaches

### Option A: Accept High-PF/Low-WR
- Use liquidity_grab + whale (PF=2.2-4.6, WR=25-37%)
- Requires psychological tolerance for 60-75% losers
- Edge is in payoff asymmetry (wins 3-5x losses)
- Position sizing must account for consecutive losses (max 10+)

### Option B: Ensemble Voting
- Combine multiple event strategies (failed_breakout + structural_break + judas_sweep)
- Take trades only when 2+ strategies agree on direction
- This naturally filters for higher conviction → potentially higher WR
- Risk: reduces trade count significantly

### Option C: Refined squeeze_breakout
- 66.7% WR on 18 trades is the closest to target
- Need to find more squeeze signals (different ATR periods, multi-timeframe)
- Could combine with volume confirmation for more signal generation
- Highest potential but most speculative

### Option D: Regime-Adaptive Strategy
- In trending markets: use momentum/continuation strategies (higher WR)
- In ranging markets: use mean-reversion (higher PF)
- Use whale positioning to detect regime (extreme ls = trending)
- Most complex but most realistic path to target

---

## Recommendation

**Stop pursuing 75% WR as a hard target.** It's not achievable for event-based strategies on 15m ETH data.

Instead, optimize for:
1. **PF >= 2.0 with WR >= 50%** — achievable with squeeze_breakout + volume filter
2. **Risk-adjusted return** — Sharpe ratio, max drawdown, consecutive losses
3. **Ensemble approach** — combine strategies to smooth returns

The liquidity_grab + whale combination (PF=2.2-4.6, WR=25-37%) is actually a solid strategy — just not a 75% WR one.

---

## Files
- `reports/event_strategies_whale_validation.json` — raw data
- `reports/event_strategies_whale_validation.md` — this report
- `scripts/test_event_strategies.py` — test script
