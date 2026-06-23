# REPORTING.md — 15-Min Scan Report Protocol

*Last updated: 2026-06-14*

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

## Delta Reporting Protocol

Every report must begin with a comparison to the previous scan before generating
the current verdict. This is not optional — a verdict without a delta is a
point-in-time snapshot, not a report.

### What to read before writing the report
1. Load `latest_scan.json` — current snapshot
2. Load `scan_history.json` — last completed entry
3. Compute the delta across these fields:
   - ICS score (current vs previous)
   - Verdict (current vs previous)
   - vol_regime (current vs previous)
   - direction (current vs previous)
   - Top 3 contributing modules (did any flip sign?)
   - Active vetoes (any added or cleared?)

### Reportable flip definition
A verdict change is only surfaced and explained if at least ONE of these is true:

| Trigger | Threshold |
|---------|-----------|
| ICS delta | ≥ 0.05 absolute change |
| Regime change | vol_regime label changed |
| Direction flip | direction changed (LONG ↔ SHORT ↔ NEUTRAL) |
| Veto state change | veto added or cleared |
| Module sign flip | any top-3 module changed from positive to negative or vice versa |

If none of these triggers are met, the verdict change is noise.
Report it briefly as: *"Verdict unchanged in substance — minor ICS drift (Δ < 0.05)."*
Do not write a full flip explanation for noise.

### Flip explanation format (only when triggered)
When a reportable flip occurs, include this block in the report:

```
⚡ SIGNAL SHIFT DETECTED
Previous verdict : [VERDICT] (ICS: X.XX, Regime: Y, Dir: Z)
Current verdict  : [VERDICT] (ICS: X.XX, Regime: Y, Dir: Z)
Primary driver   : [what changed — one module, regime, or veto]
Secondary driver : [if applicable]
Assessment       : GENUINE SHIFT / NOISE SPIKE / REGIME TRANSITION
```

Assessment definitions:
- `GENUINE SHIFT` — direction or regime changed, ICS moved > 0.10
- `NOISE SPIKE` — ICS moved 0.05–0.10 with no regime or direction change
- `REGIME TRANSITION` — vol_regime label changed regardless of ICS delta

---

## Liquidity Analysis Requirement

Every report must include a liquidity analysis section. Identify all key liquidity levels above and below the current price, including equal highs, equal lows, swing highs, swing lows, session highs/lows, and other significant liquidity pools.

Compare the current liquidity distribution with the previous hourly snapshot and determine:

1. Which liquidity levels have gained additional liquidity.
2. Which liquidity levels have lost liquidity.
3. Which side (buy-side or sell-side liquidity) is accumulating faster.
4. Which liquidity level is currently the most attractive target for price.

For each hourly review, provide:

- Liquidity level
- Type of liquidity
- Estimated liquidity change since the previous check
- Relative strength ranking
- Probability of being targeted next

Highlight any significant shifts in liquidity concentration that could alter the expected market path.

---

## scan_history.json Schema

Each completed scan appended to `scan_history.json` must store exactly these fields.
No more, no less — keep the file lean for fast delta reads.

```json
{
  "timestamp": "2026-06-14T10:15:00+08:00",
  "verdict": "WATCH",
  "ics_score": 0.61,
  "vol_regime": "CHOP_BULL",
  "direction": "LONG",
  "ics_threshold": 0.65,
  "ics_delta_from_prev": 0.03,
  "active_vetoes": [],
  "top_modules": [
    {"id": "M7",  "score": 0.82, "sign": "+"},
    {"id": "M9",  "score": 0.74, "sign": "+"},
    {"id": "M75", "score": -0.31, "sign": "-"}
  ],
  "flip_detected": false,
  "flip_assessment": null
}
```

Retention: keep last 96 entries (24 hours of 15-min scans).
Anything older is stale and should be pruned automatically.

---

## 15-Min Report Structure

Every report must follow this exact order:

```
1. DELTA HEADER
   [Previous verdict → Current verdict]
   [Flip detected: YES (trigger) / NO (noise)]

2. CURRENT SNAPSHOT
   Time      : HH:MM MYT
   Price     : $X,XXX.XX
   ICS Score : X.XX / threshold X.XX
   Regime    : [vol_regime]
   Direction : [LONG / SHORT / NEUTRAL]
   Vetoes    : [list or NONE]

3. MODULE SUMMARY
   Top contributors (max 5):
   [Module ID] [score] [brief reason]
   Conflicts (modules disagreeing with direction):
   [Module ID] [score] [brief reason]

4. FLIP EXPLANATION (only if flip triggered — else omit)
   [⚡ SIGNAL SHIFT block from above]

5. LIQUIDITY LEVELS
   [Per liquidity analysis requirement — key levels, changes, target probability]

6. VERDICT
   [Single taxonomy label]
   [One sentence rationale — ICS relative to threshold + regime context]
```

---

## Consistency Rules

- Never generate a verdict before reading both `latest_scan.json` AND `scan_history.json`
- Never explain a flip that didn't meet the reportable flip threshold
- Never use a verdict label outside the taxonomy
- Never carry forward a previous verdict without re-reading the current scan
- If `scan_history.json` is missing or empty (first run), note it:
  *"No prior scan available — delta comparison skipped."*
- If `latest_scan.json` is stale (timestamp > 20 minutes old), flag it before
  generating the report: *"⚠️ Scan data is stale — [X] minutes since last update."*

---

## What This File Does NOT Cover

- Module evaluation, backtesting, or hypothesis testing → see EVAL.md
- Live trade execution decisions → operator judgment, not this report
- Any data not in latest_scan.json or scan_history.json → do not fabricate
