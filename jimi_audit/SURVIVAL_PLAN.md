# JIMI Survival Plan — $200 Capital

## The Problem
Without risk controls, $200 → $0 in 2 months (60 trades/day, 3% SL with 10x leverage).

## The Solution: Risk Framework

### Position Sizing
- **Max risk per trade:** 1% of capital ($2 at $200)
- **Max leverage:** 3x (not 10x)
- **Max concurrent positions:** 1
- **Max position size:** 30% of capital

### Daily Limits
- **Max trades per day:** 3
- **Max daily loss:** 3% → stop trading for the day
- **Cooldown after loss:** 2 hours (8 bars)
- **3 consecutive losses:** 4-hour pause

### Drawdown Circuit Breakers
| DD Level | Action |
|---|---|
| 10% | Reduce risk to 0.5%, leverage to 2x |
| 20% | Reduce risk to 0.25%, leverage to 1x |
| 30% | Stop trading for 24 hours |
| 40% | **KILL SWITCH** — stop completely, manual restart required |

### Signal Quality Gates
- Min conviction: 0.60
- Must align with EMA20/EMA50 trend
- Min ATR: 0.5% (skip boring markets)
- Max ATR: 3.0% (skip crisis)
- Block hours: 19-21 UTC (low liquidity)
- Block Saturday

### TP/SL Rules
- ATR-based: 1x ATR TP, 1x ATR SL
- Hard cap: max 2% SL
- Min TP: 0.3%, Max TP: 3%

### Active Strategies
- squeeze_breakout (best quality)
- taker_flow (most signals)
- power_of_3 (good in ranges)

### Disabled Strategies
- vol_rotation (too many signals, low quality)
- cascade (no data)
- positioning_fade/whale_watch (need derivatives)

## Simulation Results (Feb-Jul 2026)

| Metric | Without Controls | With Controls |
|---|---|---|
| Final Capital | $0.00 | $193.51 |
| Return | -100% | -3.2% |
| Max DD | 100% | 3.4% |
| Trades/day | 60 | 0.6 |
| Total trades | 9,190 | 87 |

## Implementation Priority
1. **Immediate:** Add DD circuit breakers to scanner_executor.py
2. **This week:** Implement daily loss limits
3. **Next week:** Add signal quality gates (trend + conviction)
4. **Ongoing:** Monitor and adjust based on live performance
