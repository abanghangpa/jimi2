# REPORTING.md — 15-Min Scan Report Protocol

*Last updated: 2026-06-27*

This file defines how Jimi writes 15-minute market scan reports. Read this before generating any report.

---

## Verdict Taxonomy (MANDATORY — use exact labels only)

Every 15-min report must end with one of these five verdicts. No other wording.

| Verdict | Condition |
|---------|-----------|
| `STRONG SIGNAL` | ICS ≥ threshold, regime confirms direction, no active veto |
| `WATCH` | ICS approaching threshold (within 0.08), conditions building, no veto |
| `HOLD` | Active position open — no new entry logic applies |
| `AVOID` | ICS below threshold, OR active veto, OR regime conflict |
| `NO SIGNAL` | Scanner returned NO_SIGNAL cleanly — no ambiguity |

Never use: "looks good", "promising", "uncertain", "mixed" — these are not verdicts.
If the situation genuinely doesn't fit any category, use `AVOID` and explain why
the taxonomy doesn't fit at the bottom of the report.

---

## Report Structure

Every report must follow this exact order:

### 1. STATUS HEADER
```
### 🚨 Status: [SIGNAL_STATUS]
*Directional Bias:* `[BIAS]` ([SOURCE: Reason])
*Primary Blocker:* [Blocker in plain English, no module IDs]
*ICS Score:* `[ICS_SCORE]`
```


### ⏳ Confirmation Status
* *Signal Status:* [PENDING / CONFIRMED_3BAR / CONFIRMED_1BAR / EXPIRED]
* *Bars Waited:* [X]/3
* *Hold Window:* [X]h (strategy-specific)
* *Confirmed Price:* $[price] ([direction] confirmed)

If PENDING:
> Signal queued for market confirmation. Will enter if price moves [direction] within 3 bars (45 min).

If CONFIRMED:
> ✅ Market confirmed [direction] — price moved [X]% from signal entry. Hold window: [X]h.

If EXPIRED:
> ❌ Market did not confirm — signal expired. No trade taken.

### 2. TECHNICAL ANALYSIS
```
### 📈 Technical Analysis
* *Price:* `$[PRICE]`
* *Exchange Activity:*
  * *Bullish:* [Funding/OI bullish factors]
  * *Bearish:* [Spot/Basis bearish factors]
* *OI & L/S:* [Total OI, dominant exchange, L/S ratio highlights]
```

### 3. MACRO & REGIME
```
### 🌍 Macro & Regime
* *Regime:* `[REGIME]`
* *US Labor Cascade:* [Status/Decay]
* *Macro indicators:* [Relevant PMI/CPI/NFP misses/hits]
```

### 4. CONFLICT & RESOLUTION
```
### ⚖️ Conflict & Resolution
* *Conflict:* `[CONFLICT_TYPE]` ([Severity])
* **Key Level to Watch:** `$[LEVELS]`
* *Scenario:* [Describe the sweep/hold setup with sweep low, hold level, targets]
```

### 5. CONVERGENCE CHECK: LIQUIDITY × FLOW
Compare WHERE the liquidity is vs WHERE the flow is pushing.

*Liquidity Map* (WHERE price wants to go):
* Direction Resolver: direction, reason
* Nearest Magnet, Key S/R Levels, Stop Clusters

*Flow Map* (WHAT is pushing price):
* Whale Signal, Taker 4h, OB Imbalance, Net Flow, OI Change, L/S Ratio

*Convergence Score:* ALIGNED / PARTIAL / DIVERGENT
- ALIGNED: liquidity and flow point same direction = high conviction
- DIVERGENT: liquidity says X, flow says Y = Judas sweep risk or conflict

Renumber sections after:

### 6. STRATEGY SIGNALS (22 strategies)
Read `multi_strategy` from JSON. Show:
- `signals_fired`/`total_strategies`
- Best signal from `strategy_signal`: strategy name, type, direction, conviction, entry/SL/TP1/TP2/TP3, R:R, reason, bypass_gates
- Top 3 from `all_signals` if available

```
### 🎯 Strategy Signals
* *Strategies Fired:* `[X]/22`
* *Best Strategy:* `[name]` ([type])
* *Direction:* `[LONG/SHORT]` | *Conviction:* `[X]%`
* *Entry:* `$[entry]` | *SL:* `$[sl]` ([sl_pct]%)
* *TP1:* `$[tp1]` ([tp1_pct]%) | *TP2:* `$[tp2]` | *TP3:* `$[tp3]`
* *R:R:* `[rr1]` | *Size Mult:* `[size_mult]x`
* *Reason:* [reason]
```

### 7. ORDER FLOW
Read `order_flow` from JSON:
```
### 📊 Order Flow
* *OB Imbalance:* `[ob_imbalance]` ([ob_consensus])
* *Trade Taker:* `[trade_taker]`
* *Net Flow:* `[trade_net_flow]`
* *Funding Avg:* `[funding_avg]`
```

### 8. DUAL-GEAR STATUS
Read `dual_strategy` from JSON. Show Strategy A (Scalp) and Strategy B (Momentum) status:
```
### ⚙️ Dual-Gear Status
* *Strategy A (Scalp):* `[status]` — [reason]
* *Strategy B (Momentum):* `[status]` — [reason]
* *Base Direction:* `[direction]` | *Regime:* `[regime]`
```

### 9. NARRATIVE & VERDICT
```
### 📝 Narrative
[Plain-English market story. Reference strategy signals and order flow.
DO NOT mention module names or IDs.]

*Verdict:* [WATCH/TRADE/AVOID]. [Short final instruction].
```

---

## Data Sources (JSON fields)

| Report Section | JSON Field |
|---------------|------------|
| Status | `status`, `reason`, `direction`, `ics` |
| Price | `price` |
| Exchange Activity | `exchange_activity`, `derivatives` |
| Macro | `macro_indicators`, `m22`, `cascade` |
| Conflict | `conflict`, `direction_resolver` |
| Convergence | `direction_resolver`, `derivatives`, `taker_summary`, `order_flow`, `magnets`, `sr_levels`, `liquidity_levels` |
| Strategy Signals | `multi_strategy`, `strategy_signal` |
| Order Flow | `order_flow` |
| Dual-Gear | `dual_strategy` |
| Levels | `sr_levels`, `magnets`, `gaps`, `direction_resolver` |

---

## Delta Reporting Protocol

Every report must compare to the previous scan before generating the verdict.

### Reportable flip threshold
| Trigger | Threshold |
|---------|-----------|
| ICS delta | ≥ 0.05 absolute change |
| Regime change | vol_regime label changed |
| Direction flip | LONG ↔ SHORT ↔ NEUTRAL |
| Veto state change | veto added or cleared |
| Strategy signal change | best strategy changed or conviction delta ≥ 0.15 |

### Flip explanation format (only when triggered)
```
⚡ SIGNAL SHIFT DETECTED
Previous verdict : [VERDICT] (ICS: X.XX, Strategy: [name])
Current verdict  : [VERDICT] (ICS: X.XX, Strategy: [name])
Primary driver   : [what changed]
Assessment       : GENUINE SHIFT / NOISE SPIKE / REGIME TRANSITION
```

---

## Consistency Rules

- Never generate a verdict before reading both `latest_scan.json` AND `scan_history.json`
- Never explain a flip that didn't meet the reportable flip threshold
- Never use a verdict label outside the taxonomy
- If `latest_scan.json` is stale (>20 min), flag it: *"⚠️ Scan data is stale — [X] minutes since last update."*
- If `multi_strategy.signals_fired` is 0, note: *"No strategy signals triggered."*
- Always show the best strategy signal even if ICS is low — strategies can bypass ICS gates

---

## What This File Does NOT Cover

- Module evaluation, backtesting, or hypothesis testing → see EVAL.md
- Live trade execution decisions → operator judgment, not this report
- Any data not in latest_scan.json → do not fabricate
