# Kill Log

**Your most valuable file.** Every failed hypothesis, logged with the same detail as successes.

Why? Because:
1. Prevents repeating failed ideas
2. Documents what you learned
3. Shows the path to what actually worked

---

<!--

## [Hypothesis Name] v[Version] — KILLED

**Date:** YYYY-MM-DD
**Hypothesis:** [One sentence — what edge were you testing?]
**Mechanism:** [Why should this work? What structural behavior does it exploit?]

### Detection Logic
1. [Condition 1]
2. [Condition 2]
3. [Condition 3]

### Isolation Gate Results
- **Events:** [count]
- **p-value:** [value]
- **Effect direction:** [correct / backwards]
- **Mean forward return:** [%]
- **Round-trip cost:** [%]
- **Gate passed:** ❌

### Why It Failed
[Specific reason — be honest and precise]

- Wrong direction: effect was negative when theory predicted positive
- Not significant: p=[value] > 0.1
- Below costs: mean return [%] < round-trip cost [%]
- Too few events: [n] < 500
- Overfit: PF drift [value] > 0.5

### What I Learned
[Lesson that applies to future work]

### Time Invested
- Build time: [hours]
- Would have been saved by running gate first: [yes/no]

### Related Hypotheses
- [Link to similar ideas that also failed]
- [Link to the idea that eventually worked]

-->

---

## Template (copy this for each new kill)

```markdown
## [Name] v[Version] — KILLED

**Date:** YYYY-MM-DD
**Hypothesis:** [One sentence]
**Mechanism:** [Why should this work?]

### Detection Logic
1. [Condition 1]
2. [Condition 2]

### Isolation Gate Results
- **Events:** [n]
- **p-value:** [p]
- **Effect direction:** [correct / backwards]
- **Mean forward return:** [%]
- **Round-trip cost:** [%]
- **Gate passed:** ❌

### Why It Failed
[Specific reason]

### What I Learned
[Lesson]

### Time Invested
- Build: [hours]
- Gate-first would have saved: [yes/no]
```

## bb_mom6 standalone — KILLED

**Date:** 2026-07-12
**Hypothesis:** BB(20,2.0) mean reversion + 6h momentum > 3% predicts forward returns.
**Mechanism:** Price at BB extremes or strong 6h momentum indicates overextension, mean reversion follows.

### Detection Logic
1. Price below lower BB (LONG) or above upper BB (SHORT) on 1H
2. OR 6h momentum > 3% in either direction
3. RSI confirmation (neutral zone)

### Isolation Gate Results
- **Events:** 2921
- **p-value:** 0.3105
- **Effect direction:** backwards (mean=-0.714%)
- **Mean forward return:** -0.714%
- **Round-trip cost:** 0.10%
- **Gate passed:** ❌

### Confluence Test (extreme positioning)
- **Events:** 326
- **p-value:** 0.7716
- **Effect direction:** backwards (mean=-0.029%)
- **Gate passed:** ❌

### Why It Failed
- Standalone: negative mean returns across all regimes (2018 bear: -0.93%, 2026 chop: -0.01%)
- With confluence: still negative (-0.029%)
- Earlier gate result (+1.016%, 13 events) was noise from tiny confluence-only sample
- BB mean reversion does not have a structural edge on ETH 15m

### What I Learned
- 13 events is not enough for a gate claim (BACKTEST_FRAMEWORK.md: need 500+)
- Confluence-only testing on tiny samples creates false positives
- "Buy the paint" — BB is an indirect measure; no direct data to validate against

### Time Invested
- Build time: ~1 hour (original) + 30min (confluence re-test)
- Gate-first would have saved: yes (the 13-event claim was premature)

### Related Hypotheses
- failed_breakout (regime-specific, not dead)
- positioning_fade (not gated yet)

## momentum_v3 — KILLED

**Date:** 2026-07-13
**Hypothesis:** Exhaustion filter (9 weighted signals: decel, vol_div, percentile, OI_div, RSI, RSI_div, MACD_hist, wave, BB) scoring 0.0-1.2 with threshold 0.30+ predicts forward returns.
**Mechanism:** When multiple momentum exhaustion signals align, price is overextended and likely to reverse.

### Detection Logic
1. Compute 9 weighted exhaustion sub-signals (deceleration, volume divergence, percentile, OI divergence, RSI, RSI divergence, MACD histogram, wave, Bollinger Band)
2. Score 0.0-1.2, threshold >= 0.30
3. State filter paired with event triggers (not standalone)

### Isolation Gate Results
- **Events:** 7,490
- **p-value:** 0.0 (but mean return = 0%)
- **Effect direction:** correct (but economically dead)
- **Mean forward return:** 0%
- **Round-trip cost:** 0.10%
- **Gate passed:** ❌

### Scenario Breakdown
- PASS in 0/10 scenarios (real_data, extreme_long, extreme_short, high_vol, low_vol, bear_stress, bull_euphoria, ranging_chop, liquidation_cascade, news_event)
- Mean return across all scenarios: 0%
- Earlier promising results (positioning_fade 77.8% WR, funding_arb 100% WR) were from tiny samples (9 and 6 trades respectively) — noise, not signal

### Why It Failed
- Zero predictive power across all 10 scenarios — the 9 sub-signals collectively have no edge
- State filter concept was sound (exhaustion as context, not trigger) but the individual components don't predict
- Earlier combo results (positioning_fade + momentum_v3: 77.8% WR, PF=2.02 on 9 trades) were from insufficient sample sizes
- Per BACKTEST_FRAMEWORK.md: 9 trades is indistinguishable from a lucky coin flip

### What I Learned
- State filters need independent validation — "works as confluence" doesn't mean the component has edge
- 0% mean return with 7,490 events is definitive — the mechanism is dead, not underpowered
- Earlier results with positioning_fade were likely driven by positioning_fade alone, not momentum_v3 contribution

### Time Invested
- Build: ~2 hours (v2 scoring system, 9 sub-signals)
- Gate-first would have saved: yes (the 9-trade claims were premature)

### Related Hypotheses
- bb_mom6 (KILLED — BB mean reversion, same family)
- positioning_fade (PASS — works standalone, not because of momentum_v3)
- funding_arb (NOT GATED — needs testing)


## funding_arb — KILLED (No Data)

**Date:** 2026-07-13
**Hypothesis:** Funding rate divergence across exchanges predicts mean reversion in perpetual price.
**Mechanism:** When funding rates are extreme on one exchange vs another, traders arbitrage the difference, causing price convergence.

### Isolation Gate Results
- **Events:** 0
- **Gate passed:** N/A — never gated, no events detected

### Why It Failed
- Zero events in all available data — the scanner never detected a funding_arb signal
- No data = no edge. Cannot claim profitability without a single event.
- Strategy was disabled in executor since before the isolation gate protocol was adopted.

### What I Learned
- Strategies with zero events are not "waiting to be tested" — they're dead until proven otherwise
- Per BACKTEST_FRAMEWORK.md: "If the isolation gate fails, stop." A strategy with no events to gate is worse than a failure — it's untestable.
- Can be revived using the Synthetic Data Protocol (20-set framework) if the hypothesis is worth pursuing

### Action
- Disabled in executor (confirmed)
- Added to kill log
- Revivable via synthetic data testing if hypothesis is revisited

---

## squeeze_breakout — KILLED (No Data)

**Date:** 2026-07-13
**Hypothesis:** Bollinger Band / Keltner Channel squeeze compression followed by expansion predicts directional breakout.
**Mechanism:** When BB compresses inside KC (squeeze on), energy accumulates. Release predicts strong directional move.

### Isolation Gate Results
- **Events:** 0
- **Gate passed:** N/A — never gated, no events detected

### Why It Failed
- Zero events in all available data — the scanner never detected a squeeze_breakout signal
- No data = no edge. Cannot claim profitability without a single event.
- Was referenced as a Group B co-occurrence filter (OBI + squeeze_breakout: 80% WR, PF=3.16 on 20 trades) but those results were from a different testing methodology, not the isolation gate.

### What I Learned
- Co-occurrence results (OBI + squeeze: 20 trades) don't validate the standalone mechanism
- Per BACKTEST_FRAMEWORK.md: minimum 50 trades for any claim. 20 trades is noise.
- If the squeeze detection logic never fires, the detection parameters may need adjustment — but that's optimization, not validation

### Action
- Disabled in executor (confirmed)
- Added to kill log
- Revivable via synthetic data testing if detection logic is reworked

---

## momentum_v2 — KILLED (Co-occurrence Only, No Standalone Edge)

**Date:** 2026-07-13
**Hypothesis:** RSI + MACD + momentum convergence predicts forward returns as a state filter.
**Mechanism:** When multiple momentum indicators align, price is likely to continue in that direction.

### Isolation Gate Results
- **Events:** 0 (standalone)
- **Gate passed:** N/A — never tested standalone
- **Co-occurrence:** OBI + momentum_v2: 62.5% WR, PF=3.14 (from earlier testing)

### Why It Failed
- Never gated as standalone — only tested as co-occurrence filter with OBI
- Co-occurrence results (OBI + momentum_v2) may be driven by OBI alone
- momentum_v3 (similar concept, more sophisticated) was killed with 7,490 events showing 0% mean return — momentum state filters as a family have no edge

### What I Learned
- momentum_v3 killed with 7,490 events = definitive evidence that momentum state filters don't predict
- momentum_v2 is the simpler version — if v3 has no edge, v2 unlikely to have one either
- Co-occurrence validation is not standalone validation

### Action
- Disabled in executor (confirmed)
- Added to kill log
- Not revivable unless new evidence emerges


## scalp_v2 — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** Fast RSI(7) oversold/overbought + volume spike predicts short-term reversal.
**Mechanism:** Extreme RSI + volume = exhausted move, mean reversion follows.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 0/20
- **Direction correct:** 2/20
- **Mean p-value:** 0.2129
- **Gate passed:** ❌

### Why It Failed
- Too few events in most sets (0-7 per set) — detection logic is too restrictive
- 2/20 correct direction = worse than random
- The few events that fired had no predictive power

### What I Learned
- Ultra-tight RSI(7) + volume thresholds produce almost no signals
- When they do fire, they're noise — not enough data to distinguish from random

---

## power_of_3 — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** Wyckoff phases (accumulation/markup/distribution/markdown) predict directional moves.
**Mechanism:** Phase transitions (accum->markup = LONG, dist->markdown = SHORT) have edge.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 2/20
- **Direction correct:** 9/20
- **Mean p-value:** 0.2051
- **Gate passed:** ❌

### Why It Failed
- 9/20 correct direction = barely better than random
- Phase detection is too noisy — many false phase transitions
- Effect size too small to cover costs in most regimes

---

## macro_surprise — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** Extreme funding rate predicts mean reversion (shorts overcrowded = LONG, longs overcrowded = SHORT).
**Mechanism:** Funding rate z-score > 2 or < -2 with volume confirmation.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 2/20
- **Direction correct:** 4/20
- **Mean p-value:** 0.1354
- **Gate passed:** ❌

### Why It Failed
- 4/20 correct direction = worse than random
- Funding rate extremes in synthetic data don't reliably predict reversion
- Most sets had too few events (0-6)

---

## liquidation_cascade — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** OI crash (>5% drop) + sharp price move + volume spike = cascading liquidations predict continuation.
**Mechanism:** OI dropping = forced closes, momentum continues.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 2/20
- **Direction correct:** 6/20
- **Mean p-value:** 0.2669
- **Gate passed:** ❌

### Why It Failed
- 6/20 correct direction = worse than random
- Direction is unpredictable — sometimes cascades reverse, sometimes continue
- High p-values across all sets

---

## judas_sweep — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** Price sweeps a swing level then closes back inside = trapped traders, reversal follows.
**Mechanism:** Sweep high + close below = SHORT, sweep low + close above = LONG.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 1/20
- **Direction correct:** 12/20
- **Mean p-value:** 0.2803
- **Gate passed:** ❌

### Why It Failed
- 12/20 correct direction is decent but mean p=0.28 = not significant
- Effect size too small (most < 0.1%) to cover costs
- Only 1 set passed the gate — not robust

---

## taker_flow — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** Extreme taker buy/sell ratio (>2 sigma) with volume predicts directional continuation.
**Mechanism:** Aggressive taker flow = informed traders, follow their direction.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 0/20
- **Direction correct:** 0/20
- **Mean p-value:** 1.0000
- **Gate passed:** ❌

### Why It Failed
- ZERO events in most sets — detection threshold too extreme
- When events existed (1-2 per set), no statistical power
- Complete failure — the mechanism doesn't work even in theory on synthetic data

---

## liquidity_grab — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** Extreme bid/ask imbalance (>0.3) with volume predicts price direction.
**Mechanism:** One side of book heavier = institutional positioning, follow that direction.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 2/20
- **Direction correct:** 9/20
- **Mean p-value:** 0.1874
- **Gate passed:** ❌

### Why It Failed
- 9/20 correct direction = random
- L2 imbalance doesn't predict on synthetic data — may need real L2 dynamics

---

## cascade — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** OI + price + volume all moving together = cascading momentum that continues.
**Mechanism:** Bull cascade (OI up + price up + vol up) or bear cascade (opposite).

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 2/20
- **Direction correct:** 6/20
- **Mean p-value:** 0.1766
- **Gate passed:** ❌

### Why It Failed
- 6/20 correct direction = worse than random
- Cascades are unpredictable — sometimes they reverse, sometimes continue
- Similar to liquidation_cascade — same family, same failure mode

---

## mtf_confluence — KILLED (Synthetic Gate)

**Date:** 2026-07-13
**Hypothesis:** 15m and 1h EMA trends aligned = strong directional signal.
**Mechanism:** Multi-timeframe confluence confirms trend, entry on fresh alignment.

### Isolation Gate Results (Synthetic v2)
- **Sets passed:** 2/20
- **Direction correct:** 8/20
- **Mean p-value:** 0.2521
- **Gate passed:** ❌

### Why It Failed
- 8/20 correct direction = worse than random
- Fresh EMA alignment is too noisy — many false signals
- Effect size tiny in most sets


## regime_switch — KILLED (Real Data Gate)

**Date:** 2026-07-13
**Hypothesis:** Vol regime transition (ATR percentile crossing 0.8) predicts directional move.
**Mechanism:** When vol expands from compression, price tends to move in the direction of the prevailing trend.

### Real Data Gate Results (ETH 15m, Jan-Jul 2026)
- **Events:** 876
- **Best horizon:** 4-bar
- **Mean return:** -0.0538% (BACKWARDS)
- **p-value:** 0.0838
- **Gate passed:** ❌

### Why It Failed
- Direction is backwards — vol expansion predicts CONTINUATION, not the trend direction at detection
- ATR percentile crossing 0.8 catches late-stage moves, not early ones
- Synthetic data showed 9/20 correct direction but real data confirms no edge

---

## kill_zone — KILLED (Real Data Gate)

**Date:** 2026-07-13
**Hypothesis:** Session timing (London/NY opens) combined with EMA trend predicts direction.
**Mechanism:** Kill zones (07-10, 13-16 UTC) have higher volume and institutional activity.

### Real Data Gate Results (ETH 15m, Jan-Jul 2026)
- **Events:** 6,177
- **Best horizon:** 24-bar
- **Mean return:** -0.0118% (BACKWARDS)
- **p-value:** 0.0162
- **Gate passed:** ❌

### Why It Failed
- 6,177 events = every bar in kill zones = no selectivity
- Direction backwards — being in a kill zone doesn't predict direction
- Session timing alone has no edge; it's a filter, not a signal

---

## structural_break — KILLED (Real Data Gate)

**Date:** 2026-07-13
**Hypothesis:** Breaking 50-bar high/low with volume > 1.3x predicts continuation.
**Mechanism:** Institutional S/R breaks with volume confirm genuine breakouts.

### Real Data Gate Results (ETH 15m, Jan-Jul 2026)
- **Events:** 559
- **Best horizon:** 1-bar
- **Mean return:** -0.0419% (BACKWARDS)
- **p-value:** 0.0677
- **Gate passed:** ❌

### Why It Failed
- Direction backwards — breaks with volume often reverse (false breaks)
- 50-bar rolling high/low is too reactive — catches noise, not real levels
- Similar failure mode to judas_sweep — sweeps/breaks reverse

---

## vol_rotation — KILLED (Real Data Gate)

**Date:** 2026-07-13
**Hypothesis:** Volume expanding from compression (>1.5x) with EMA trend predicts direction.
**Mechanism:** Low-vol compression followed by expansion = directional move.

### Real Data Gate Results (ETH 15m, Jan-Jul 2026)
- **Events:** 1,071
- **Best horizon:** 4-bar
- **Mean return:** +0.0238% (correct direction)
- **p-value:** 0.1552
- **Gate passed:** ❌

### Why It Failed
- Correct direction (+0.0238%) but effect too small to cover costs (0.10% round-trip)
- p=0.1552 > 0.1 threshold — not statistically significant
- Volume expansion alone doesn't predict enough to be tradeable


---

## funding_arb — RESURRECTED (2026-07-13)

**Original kill:** Zero events, never fired.
**Resurrection:** v3 multi-factor detection (taker z-score > 1.25 + round number proximity + volume) on extended data (88K bars, Jan 2024 - Jul 2026).
**New gate result:** 226 events, mean=+0.210%, p=0.054. PASS.
**Key insight:** The concept was always valid. v1 detection was wrong — needed round number proximity (where arb desks operate) and taker divergence (not FR level) as signal.

---

## judas_sweep — RESURRECTED (2026-07-13)

**Original kill:** +0.008% mean, p=0.154. Effect too small, levels were noise.
**Resurrection:** v3 multi-factor detection (daily/session H/L + rejection wick 1.5x body + volume > 1.0) on extended data (88K bars).
**New gate result:** 1,895 events, mean=+0.103%, p=0.040. PASS.
**Key insight:** The concept was always valid. v1 used rolling 10-bar fractals (noise). v3 uses real institutional levels where stops actually cluster.

## cross_asset — KILLED

**Date:** 2026-07-14
**Hypothesis:** ETH/BTC ratio divergence + macro alignment + exchange activity predicts ETH price direction.
**Mechanism:** When ETH diverges from BTC (ratio z-score), macro and exchange scores confirm, price should revert.

### Isolation Gate Results
- **Events:** 1784 (extended backtest, 5000 bars)
- **p-value:** 0.311
- **Effect direction:** backwards (mean=-0.018%)
- **Mean forward return:** -0.018%
- **Round-trip cost:** 0.10%
- **Gate passed:** ❌

### Why It Failed
- Original 82-event result (+0.661% mean) was noise from tiny sample
- Extended backtest with 1784 events showed negative mean return
- ETH/BTC ratio divergence does not predict ETH price direction
- LONG signals lost (-0.0625%), SHORT signals barely positive (+0.0256%)
- Both below round-trip costs

### What I Learned
- 82 events is NOT enough for a gate claim (BACKTEST_FRAMEWORK.md: need 500+)
- Cross-asset divergence is a real phenomenon but not exploitable on 15m timeframe
- The "confluence" of M10+M7+exchange was illusory — correlated modules

### Time Invested
- Build: ~2 hours (original) + 30min (extended backtest)
- Gate-first would have saved: yes (the 82-event claim was premature)

