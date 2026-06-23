# EVAL.md — Hypothesis Testing & Evaluation Protocol

*Last updated: 2026-06-23*

This file defines how Jimi evaluates changes to the trading system. Every modification to entry logic, module weights, thresholds, or strategy gates must go through this process before going live.

---

## 1. Hypothesis Statement

Before any test, write a clear hypothesis:

```
HYPOTHESIS: [What you believe will happen]
WHY:        [Evidence or reasoning behind the belief]
RISK:       [What could go wrong if this is adopted]
REVERSIBLE: [Can we easily revert? Y/N]
```

---

## 2. Test Design

### Data Requirements
- **Minimum data**: 3 months of 15m candles (Jan–Mar 2018 recommended as baseline)
- **Comparison**: Always test against the current system (baseline) on the same data
- **Walk-forward**: If time permits, test on out-of-sample data (e.g., train on Jan–Feb, validate on Mar)

### Metrics to Track

| Metric | Definition | Why It Matters |
|--------|-----------|----------------|
| **Win Rate** | Wins / Total Trades | Core profitability signal |
| **PnL %** | Net profit/loss per trade | Absolute performance |
| **Max Drawdown** | Worst peak-to-trough | Risk management |
| **Trade Count** | Total signals generated | More trades = more opportunities, but also more noise |
| **Avg Win / Avg Loss** | Reward-to-risk ratio | Must be > 1.0 for positive expectancy |
| **Expectancy** | (WR × AvgWin) - ((1-WR) × AvgLoss) | Must be > 0 |
| **Signal Quality** | % of signals that hit TP1 | Measures entry precision |
| **False Positive Rate** | % of signals that hit SL before TP1 | Measures noise filtering |

### What to Log Per Trade

```json
{
  "timestamp": "2026-01-15T10:30:00+08:00",
  "strategy": "scalp",
  "direction": "LONG",
  "entry": 1985.50,
  "sl": 1975.00,
  "tp1": 1993.33,
  "outcome": "WIN",
  "pnl_pct": 0.40,
  "ics_score": 0.62,
  "vol_regime": "CHOP_BULL",
  "modules_agreeing": ["M1", "M2", "M3"],
  "modules_disagreeing": ["M5"],
  "notes": ""
}
```

---

## 3. Success Criteria

Define go/no-go thresholds BEFORE running the test:

| Metric | Minimum (Go) | Target | Maximum (No-Go) |
|--------|-------------|--------|-----------------|
| Win Rate | ≥ baseline | ≥ baseline + 5% | < baseline |
| PnL % | ≥ baseline | ≥ baseline + 10% | < baseline |
| Max Drawdown | ≤ baseline + 2% | ≤ baseline | > baseline + 5% |
| Trade Count | ≥ baseline × 0.7 | ≥ baseline | < baseline × 0.5 |
| Expectancy | > 0 | ≥ baseline | < 0 |

**Decision rules:**
- **GO**: All minimums met, at least 2 targets met
- **CONDITIONAL GO**: Minimums met but targets not met → test on more data
- **NO-GO**: Any minimum violated → reject hypothesis

---

## 4. Test Execution

### Step-by-step
1. Write hypothesis to this file (Section 6 below)
2. Create a test config YAML (e.g., `test_confluence_gate.yaml`)
3. Run backtest: `python3 scripts/scanner.py --config test_confluence_gate.yaml --backtest`
4. Compare results against baseline config
5. Document results in Section 6
6. Make go/no-go decision

### Config naming convention
- `baseline.yaml` — current production config
- `test_[name].yaml` — experimental config
- `test_[name]_v2.yaml` — iterations

---

## 5. Results Template

```
## Test: [Name]
Date: YYYY-MM-DD
Hypothesis: [from Section 1]

### Baseline Results
- Win Rate: X%
- PnL: X%
- Max DD: X%
- Trades: N
- Expectancy: X

### Test Results
- Win Rate: X% (Δ = +X%)
- PnL: X% (Δ = +X%)
- Max DD: X% (Δ = +X%)
- Trades: N (Δ = +N)
- Expectancy: X (Δ = +X)

### Verdict: [GO / CONDITIONAL GO / NO-GO]
Reason: [One sentence]

### Notes
[Observations, anomalies, edge cases]
```

---

## 6. Active Tests

### TEST: Confluence Gate (replacing ICS for Scalp)
Date: 2026-06-23
Status: PENDING

**Hypothesis:**
Replacing the ICS gate in Strategy A (Scalp) with a multi-factor confluence check will generate more valid signals without reducing win rate.

**Why:**
ICS 0.495 blocked a scalp entry despite the market being tradeable. ICS is a weighted average — one weak module can drag the whole score below threshold even when most signals agree.

**Proposed change:**
Replace ICS gate with:
- Module agreement: ≥ 3 of M1–M5 agree with direction (required)
- Module strength: Avg score of agreeing modules ≥ 0.60 (required)
- Volume: vol_ratio ≥ 1.2x OR taker flow confirms direction (optional boost)

**Risk:**
More permissive gate → more signals → some lower quality → potential increase in false positives.

**Reversible:** Yes (config toggle `SCALP_GATE_MODE: confluence | ics`)

**Test config:**
- Data: 2018-01 to 2018-03 (Jan–Mar 2018 ETH 15m)
- Baseline: `baseline.yaml` (ICS threshold 0.65)
- Test: `test_confluence_gate.yaml` (confluence mode)

**Results:** [To be filled after backtest]

---

*Add new tests below this line. Use the template from Section 5.*
