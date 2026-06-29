# Strategy Upgrade Roadmap
*Created: 2026-06-27*
*Updated: 2026-06-29*

## Completed

- [x] s22_judas_sweep: created, validated (80.2% win, 10.3x R:R), upgraded to v2
- [x] Signal logging added to StrategyRunner (all 22 strategies auto-logged)
- [x] Convergence Check section in report template (liquidity x flow)
- [x] REPORTING.md updated with multi-strategy + order flow + convergence
- [x] s05_kill_zone: ATR-dynamic taker thresholds (0.5 +/- atr_pct * 5)
- [x] s06_liquidity_grab: Dynamic proximity via squeeze_quality (0.3-0.7 ATR range)
- [x] s07_taker_flow: ATR-relative taker thresholds (0.5 +/- atr_pct * 2)
- [x] s11_cross_asset: Bidirectional - evaluates both LONG and SHORT alignment

## Pending: Medium Priority (after 2 weeks of data)

### Outcome Tracker Script
- Script to read data/strategy_signals.jsonl and match against actual price moves
- Metrics: Win rate per strategy, avg R:R, conviction calibration
- When: After 2 weeks of live signal logging

### Per-Strategy Tuning
- Adjust thresholds based on actual outcome data
- When: After outcome tracker shows which strategies are underperforming

### Dynamic Thresholds (remaining strategies)
- Convert fixed thresholds to ATR-based in s08, s17
- When: After outcome data validates the approach

## Data Collection Status

| Metric | Source | Status |
|--------|--------|--------|
| Strategy signals | data/strategy_signals.jsonl | Auto-logged |
| Scan history | data/scans/*.json | 930+ files |
| Judas sweep signals | data/judas_sweep_signals.jsonl | Auto-logged |
| Outcome tracking | Not yet | Need script |
