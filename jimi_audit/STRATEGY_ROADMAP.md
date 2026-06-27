# Strategy Upgrade Roadmap
*Created: 2026-06-27*

## Completed This Session
- [x] s22_judas_sweep: created, validated (80.2% win, 10.3x R:R), upgraded to v2
- [x] Signal logging added to StrategyRunner (all 22 strategies auto-logged)
- [x] Convergence Check section in report template (liquidity × flow)
- [x] REPORTING.md updated with multi-strategy + order flow + convergence

## Pending: High Priority (3 strategies)

### s05_kill_zone — Fixed taker thresholds
- **Issue:** Hardcoded taker thresholds (0.53 LONG, 0.47 SHORT)
- **Fix:** Make ATR-dynamic: `taker_long = 0.5 + atr_pct * 5`, `taker_short = 0.5 - atr_pct * 5`
- **Impact:** Better adaptation to volatile vs calm regimes

### s06_liquidity_grab — Fixed ATR proximity
- **Issue:** Hardcoded `0.5 * atr` proximity check
- **Fix:** Dynamic: `proximity = atr * (0.3 + compression_ratio * 0.4)`
- **Impact:** Tighter in compression, wider in expansion

### s07_taker_flow — Fixed thresholds
- **Issue:** Fixed taker/flow thresholds
- **Fix:** ATR-relative thresholds
- **Impact:** Better regime adaptation

### s11_cross_asset — LONG only
- **Issue:** Only checks LONG direction from cross-asset signals
- **Fix:** Add SHORT logic when cross-asset signals are bearish
- **Impact:** Doubles the opportunity set

## Pending: Medium Priority (after 2 weeks of data)

### Outcome Tracker Script
- **What:** Script to read `data/strategy_signals.jsonl` and match against actual price moves
- **Metrics:** Win rate per strategy, avg R:R, conviction calibration, best/worst strategies
- **When:** After 2 weeks of live signal logging

### Per-Strategy Tuning
- **What:** Adjust thresholds based on actual outcome data
- **When:** After outcome tracker shows which strategies are underperforming

### Dynamic Thresholds (remaining strategies)
- **What:** Convert fixed thresholds to ATR-based in s05, s06, s07, s08, s17
- **When:** After outcome data validates the approach

## Data Collection Status

| Metric | Source | Status |
|--------|--------|--------|
| Strategy signals | `data/strategy_signals.jsonl` | ✅ Auto-logged |
| Scan history | `data/scans/*.json` | ✅ 930+ files |
| Judas sweep signals | `data/judas_sweep_signals.jsonl` | ✅ Auto-logged |
| Outcome tracking | Not yet | ❌ Need script |

## Key Numbers (from s22 validation)
- Judas sweep: 80.2% win rate, 10.3x R:R on 20k bars
- 587 events in ~208 days = ~2.8 events/day
- Closed below resistance: 78.6% win
- Still above resistance: 81.3% win
