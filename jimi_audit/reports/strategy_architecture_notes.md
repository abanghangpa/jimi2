# Strategy Architecture Notes — Sentiment vs Event-Based Signals
**Date:** 2026-07-06
**Author:** Analysis during whale_watch pairing optimization

---

## Core Insight

**Two filters agreeing on direction ≠ a signal. You need at least one hard trigger.**

Sentiment/positioning indicators (L/S ratio, funding rate, OI skew) are **conditioning variables** — they tell you the state of the crowd. They should be paired with **event-based modules** that answer "why now" (breakouts, structure shifts, liquidity sweeps) — not with other trend/continuation modules that also lack a hard timing trigger.

Pairing two non-timing signals (sentiment + trend_follow, which is itself more of a state/regime filter than a discrete trigger) gives you two filters agreeing on direction with **no actual entry event** — which is exactly the failure mode diagnosed in the whale_watch analysis.

---

## Strategy Classification

### State/Conditioning Indicators (NO timing trigger)
These tell you "what is the environment" but not "when to enter":

| Strategy | What it measures | Why it's state, not event |
|----------|-----------------|--------------------------|
| whale_watch | L/S ratio positioning | Crowd position = continuous state |
| trend_follow | Price vs EMA200 | Regime filter, not discrete trigger |
| mtf_confluence | Multi-EMA alignment | Regime filter |
| cross_asset | Volume direction | Flow state indicator |
| momentum_v2 | 5-bar price change | Velocity state |

### Event-Based Strategies (HAS discrete trigger)
These answer "why now" — something specific just happened:

| Strategy | The event | Why it's a trigger |
|----------|-----------|-------------------|
| **failed_breakout** | Price broke BB then snapped back | Discrete: breach + reversal = event |
| **structural_break** | Price broke 20-bar high/low | Discrete: level break = event |
| **liquidity_grab** | Swept high/low + closed reversal | Discrete: sweep + rejection = event |
| **squeeze_breakout** | ATR compression → expansion | Discrete: regime change = event |
| **judas_sweep** | Sweep high/low + bearish close | Discrete: trap + reversal = event |
| **positioning_fade** | Extreme L/S + price direction | Borderline: extreme IS the trigger |
| **orderbook_imbalance** | Volume spike + direction | Discrete: volume surge = event |
| **taker_flow** | High volume + body > ATR threshold | Discrete: flow surge = event |

---

## Correct Architecture

```
Event module (WHY NOW?)    +    State filter (IS THE CROWD WRONG?)
         ↓                                    ↓
  liquidity_grab fires              whale confirms direction
  "price swept a high"              "crowd is heavily long"
  = concrete entry trigger          = conditioning context
```

The event module provides the **timing** (when to enter).
The state filter provides the **context** (is the environment favorable).

### Why This Works

- **Event alone** = may fire against the crowd → stopped out
- **State alone** = no entry timing → over-trading or stale entries
- **Event + State** = right timing + right context → high WR

---

## Pairing Results Validation

### Worked (Event + State)
| Pair | WR | PF | Architecture |
|------|-----|------|-------------|
| liquidity_grab + whale | 47.1% | **7.57** | Event (sweep) + State (crowd) ✅ |
| structural_break + whale | 61.1% | 3.60 | Event (break) + State (crowd) ✅ |
| failed_breakout + whale | 57.1% | 5.18 | Event (BB breach) + State (crowd) ✅ |

### Failed (State + State)
| Pair | WR | PF | Architecture |
|------|-----|------|-------------|
| trend_follow + whale | 40.5% | 3.17 | State + State ❌ no trigger |
| mtf_confluence + whale | 50.0% | 3.75 | State + State ❌ no trigger |
| cross_asset + whale | 47.5% | 2.33 | State + State ❌ no trigger |
| momentum_v2 + whale | 62.5% | 7.11 | State + State ❌ (8 trades only) |

---

## Application to Live Executor

### Current Enabled Strategies — Classification
| Strategy | Type | Verdict |
|----------|------|---------|
| failed_breakout | Event ✅ | Keep enabled |
| structural_break | Event ✅ | Keep enabled |
| positioning_fade | Event (borderline) ✅ | Keep enabled |
| orderbook_imbalance | Event ✅ | Keep enabled |
| trade_flow | Event ✅ | Keep enabled |
| funding_arb | State (funding rate) | Need to pair with event |
| regime_switch | State (EMA cross) | Need to pair with event |
| whale_watch | State (L/S ratio) | DISABLED — needs event pairing |

### Recommended Pairing Strategy

Instead of running whale_watch as a standalone signal, use it as a **gate/condition** for event-based strategies:

```
For each event-based strategy (failed_breakout, structural_break, etc.):
  1. Strategy fires its event signal
  2. Check whale_watch: is the crowd positioned against this trade?
  3. If crowd agrees OR is neutral → take the trade
  4. If crowd is heavily against → skip or reduce size
```

This turns whale_watch from a signal generator into a **risk filter** — which is what sentiment indicators are best at.

---

## Key Takeaway

> **Sentiment tells you WHO is wrong.**
> **Events tell you WHEN to act.**
> **You need both to trade.**

A crowd being wrong is not enough — you need a trigger that says "the crowd is wrong AND the market is starting to correct." That trigger comes from event-based modules: breakouts, sweeps, structure shifts, volume surges.

Without the event, you're just fading a crowd that can stay wrong for a long time.

---

## Files
- This document: `reports/strategy_architecture_notes.md`
- Whale pair analysis: `reports/whale_pair_findings.md`
- Detailed trades JSON: `reports/whale_pair_analysis.json`
