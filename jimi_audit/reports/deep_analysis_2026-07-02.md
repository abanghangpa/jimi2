## JIMI Deep Analysis Report - 2026-07-02

This report analyzes the performance of the JIMI Framework's multi-layered quality gate architecture based on data from 2026-06-07 to 2026-07-02, covering 1817 scan files.

### 📊 Filter Performance

*   **M20 Filter Block Rate:** 0% (244 FAIL + 141 NEUTRAL out of 1817 total module counts for m20, indicating it's not actively blocking contrarian signals as expected, or its definition of 'blocking' needs review).
*   **Sweep-Against Filter Block Rate:** 0% (No signals explicitly blocked by this filter based on `filter_stats`). This suggests the filter may not be engaged or is not triggering.
*   **Ensemble Pass Rate:** 100% (545 total signals, 0 ensemble blocked). This implies all signals are passing the ensemble gate, or the gate is not yet implemented/fully active in the data.
*   **Confirmation Rate:** 0% of total signals were confirmed. The `filter_stats` show 0 confirmed signals. This is a critical weakness.
*   **Strategy-Specific Hold Window Effectiveness:**
    *   'strategy:scalp_v2' (1h): 50% WR, -0.0823 median % loss.
    *   'strategy:orderbook_imbalance' (2h): 56.4% WR, -0.0035 median %.
    *   'strategy:trade_flow' (2h): 58.4% WR, -0.0438 median %.
    *   'strategy:funding_arb' (4h): 54.5% WR, 0.0801 median %.
    *   'strategy:failed_breakout' (8h): 77.6% WR, 0.326 median %.
    *   'strategy:structural_break' (8h): 28.0% WR, -0.117 median %.
    *   The 8h hold windows for 'failed_breakout' show high WR, while 'structural_break' is underperforming significantly.

### 📈 Regime Selector Accuracy

*   **Regime Distribution:** 91.5% trending\_down, 8.5% ranging.
*   **Accuracy:** The regime selector's accuracy is difficult to assess directly from this data. However, the overwhelming 'trending\_down' regime suggests the selector might be biased or the market has been predominantly bearish.
    *   In the 'trending\_down' regime: LONG signals have a 52.1% WR, while SHORT signals have a 58.0% WR. This indicates a slight edge for shorts in this regime.
    *   In the 'ranging' regime: LONG signals have a lower WR (39.1%) compared to SHORT signals (insufficient data).

### 🤝 Ensemble Consensus Quality

*   **Ensemble Consensus Distribution:** 100% 'NONE'. This indicates no ensemble consensus is being recorded or utilized in the provided data. The system appears to be passing all signals without an active consensus mechanism.

### ✅ Confirmation Layer Effectiveness

*   **Confirmation Rate:** 0% of signals were confirmed according to `filter_stats`. This is a major issue, suggesting signals are not meeting confirmation criteria or the tracking is faulty.

### 🪟 Strategy-Specific Hold Window Optimization

*   **Underperformers:**
    *   'strategy:structural\_break' (8h): 28.0% WR.
    *   'strategy:failed\_breakout' (8h): 77.6% WR.
*   **Optimization Potential:** The large discrepancy between 'failed\_breakout' and 'structural\_break' within the same 8h window warrants investigation. It's possible the parameters for 'structural\_break' need adjustment, or its signals are fundamentally weaker.

### ⚠️ Remaining Weak Points

*   Signals in the \"0.55-0.60\" ICS bucket with a LONG direction have a very low WR of 25.0%.
*   The \"trending\_down\" regime shows weaker performance for LONG signals (52.1% WR) compared to SHORT signals (58.0% WR).
*   The confirmation layer is not reporting any confirmed signals, which is a critical failure point.

### 🚀 PROPOSAL

1.  **Investigate Confirmation Layer:**
    *   **File:** `scripts/deep_analysis_prep.py` (or related confirmation logic)
    *   **Change:** Audit the confirmation logic to ensure signals are correctly flagged as 'confirmed'. Verify that the 'confirmed' count in `filter_stats` is accurately reflecting passed signals. If the logic is correct, investigate why signals are not meeting the 3-bar confirmation window.

2.  **Re-evaluate 'structural\_break' Strategy:**
    *   **File:** `src/strategies/structural_break.py` (or relevant config/parameters)
    *   **Change:** Analyze the parameters and logic for `strategy:structural_break`. Specifically, investigate why its 8h hold window has a 28.0% WR, significantly underperforming `strategy:failed_breakout` (77.6% WR) over the same period. Consider recalibrating its thresholds or decision logic.

3.  **Address Low-Confidence ICS Buckets:**
    *   **File:** `jimi_audit/data/deep_analysis_summary.json` (analysis) and potentially strategy parameter files.
    *   **Change:** The \"0.55-0.60\" ICS bucket for LONG signals shows a critical weakness (25.0% WR). Investigate if this bucket should be filtered out or if specific strategies performing poorly in this bucket need adjustment.

4.  **Review M20 and Sweep-Against Filters:**
    *   **File:** `scripts/deep_analysis_prep.py` (or related filter logic)
    *   **Change:** The M20 and sweep-against filters show 0% block rates in the summary. This suggests they may not be active or are not triggering as expected. Review their implementation and ensure they are correctly filtering contrarian and sweep-against signals. If they are intended to be passive, document this clearly.

5.  **Analyze Regime Selector Bias:**
    *   **File:** `scripts/deep_analysis_prep.py` (analysis)
    *   **Change:** Given the strong 'trending\_down' bias (91.5%), analyze if the regime selector is correctly classifying market conditions or if it's overly sensitive to one type of trend. Evaluate if the strategy performance within regimes aligns with expectations. Consider if more 'ranging' regime detection is needed.

*Self-Correction:* The `filter_stats` showing 0 confirmed signals is highly concerning and points to a potential implementation error in the confirmation layer or the data collection for it. This should be prioritized. The M20 and sweep-against filters also warrant immediate investigation to ensure they are functioning as intended.
