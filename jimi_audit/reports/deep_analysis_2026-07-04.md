## JIMI Deep Analysis Report - 2026-07-04

**Date Range:** 2026-06-07 to 2026-07-04

### 📊 Data Quality & Coverage

- **Filter Data Quality:** 
  - `ensemble_passes`: Not tracked (7.0% coverage)
  - `sweep_blocked`: Not tracked (7.0% coverage)
  - `m20_blocked`: Not tracked (7.0% coverage)
  - `confirmation_status`: Not tracked (35.3% coverage)
- **General Notes:** Minimum samples for metrics is 30. 95% CI shown for n >= 50.

### 📈 Trade Outcomes (Primary) - Total Trades: 4049

**Overall:**
- Win Rate: 46.4% (based on 577 signals)
- Avg. RR: -0.018 (Note: This is directional accuracy, not actual trade P&L)

**By Strategy:**
- **`orderbook_imbalance`**: 🌟 **Strong Performer**
  - Win Rate: 54.7% (95% CI: 49.6-59.7)
  - Avg. RR: 0.185
  - Sample Size (n): 396
- **`trade_flow`**: 
  - Win Rate: 50.4% (95% CI: 46.7-54.1)
  - Avg. RR: 0.115
  - Sample Size (n): 753
- **`cross_asset`**:
  - Win Rate: 45.4% (95% CI: 40.2-50.6)
  - Avg. RR: 0.134
  - Sample Size (n): 346
- **`funding_arb`**:
  - Win Rate: 48.0% (95% CI: 43.2-52.9)
  - Avg. RR: -0.031 (Losing money per trade)
  - Sample Size (n): 411
- **`structural_break`**:
  - Win Rate: 39.3% (95% CI: 31.6-47.6)
  - Avg. RR: -0.018
  - Sample Size (n): 140
- **`mtf_confluence`**:
  - Win Rate: 39.4% (95% CI: 33.6-45.5)
  - Avg. RR: -0.039
  - Sample Size (n): 256
- **`scalp_v2`**:
  - Win Rate: 32.7% (95% CI: 28.6-37.2)
  - Avg. RR: -0.272 (Significant losses)
  - Sample Size (n): 484
- **`regime_switch`**:
  - Win Rate: 31.9% (95% CI: 27.8-36.2)
  - Avg. RR: -0.203 (Significant losses)
  - Sample Size (n): 481
- **`failed_breakout`**:
  - Win Rate: 34.1% (95% CI: 30.7-37.7)
  - Avg. RR: -0.238 (Significant losses)
  - Sample Size (n): 757
- **Insufficient Data**: `squeeze_breakout` (n=10), `taker_flow` (n=7), `vol_rotation` (n=8).

**By Direction:**
- **LONG signals:**
  - `orderbook_imbalance_LONG`: Win Rate: 58.9% (n=197)
  - `trade_flow_LONG`: Win Rate: 53.8% (n=342)
  - `structural_break_LONG`: Win Rate: 21.7% (n=83) - **Poor performance**
  - `failed_breakout_LONG`: Win Rate: 38.7% (n=478)
- **SHORT signals:**
  - `orderbook_imbalance_SHORT`: Win Rate: 50.3% (n=199)
  - `trade_flow_SHORT`: Win Rate: 47.5% (n=411)
  - `structural_break_SHORT`: Win Rate: 64.9% (n=57) - **Strong performance**
  - `failed_breakout_SHORT`: Win Rate: 24.5% (n=279) - **Poor performance**

**By Conviction Bucket:**
- Very High (0.7+): Win Rate: 48.4% (n=1552)
- High (0.5-0.7): Win Rate: 37.0% (n=2220)
- Medium (0.3-0.5): Win Rate: 40.7% (n=277)

### 🎯 Direction Accuracy (Secondary) - 577 Signals

- **Overall:** Win Rate: 46.4% (Avg. %: -0.018)
- **`strategy:failed_breakout_8h`**: **Excellent Directional Accuracy**
  - Win Rate: 77.6% (n=49)
- **`strategy:orderbook_imbalance_2h`**:
  - Win Rate: 57.1% (95% CI: 49.2-64.7) (n=154)
- **`strategy:trade_flow_2h`**:
  - Win Rate: 57.3% (95% CI: 46.5-67.5) (n=82)
- **`strategy:funding_arb_4h`**:
  - Win Rate: 54.8% (n=42)
- **`strategy:scalp_v2_1h`**: Insufficient data (n=20, need 10 more).
- **`strategy:main_pipeline_2h`**:
  - Win Rate: 46.4% (95% CI: 39.4-53.7) (n=183)

### ⚙️ Regime Analysis (Period: 2026-06-07 to 2026-07-04)

- **Distribution:** 81.8% Trending Down, 11.8% Ranging, 6.3% Trending Up.
- **Performance by Regime:**
  - **`trending_down`**:
    - LONG signals: Win Rate: 52.1% (n=313)
    - SHORT signals: Win Rate: 58.0% (n=193) - **Stronger performance**
  - **`ranging`**:
    - LONG signals: Win Rate: 46.7% (n=30) - Insufficient data
    - SHORT signals: Insufficient data (n=3)
  - **`trending_up`**:
    - LONG signals: Insufficient data (n=16)
    - SHORT signals: Insufficient data (n=9)

### 🤔 Reconciliation & Proposals

**Observations:**

1.  **`failed_breakout`**: Shows **excellent directional accuracy (77.6%)** but **poor trade outcomes (34.1% WR, -0.238 Avg. RR)**. This strongly suggests the Take Profit (TP) and Stop Loss (SL) parameters for this strategy need adjustment. The signal is predicting direction well, but the trades themselves are losing money.
2.  **`structural_break`**: Similar to `failed_breakout`, direction accuracy is decent (though not as high as `failed_breakout`), but trade outcomes are poor. Directional accuracy for LONG signals is particularly weak (21.7% WR).
3.  **`scalp_v2`**: Very poor trade outcomes (32.7% WR, -0.272 Avg. RR), indicating significant losses. This strategy should be considered for disabling or a major overhaul.
4.  **`regime_switch`**: Also shows very poor trade outcomes (31.9% WR, -0.203 Avg. RR).
5.  **`orderbook_imbalance`**: Stands out with strong trade outcomes (54.7% WR, 0.185 Avg. RR) and good directional accuracy (57.1% for 2h). This strategy is performing well.
6.  **`trade_flow`**: Solid performance with a 50.4% WR and positive Avg. RR.
7.  **Data Tracking Gaps**: Crucial filters (`ensemble_passes`, `sweep_blocked`, `m20_blocked`, `confirmation_status`) have very low coverage (7.0% or less). This severely limits our ability to analyze filter effectiveness and potential biases.

**Proposals:**

1.  **Re-tune TP/SL for `failed_breakout` and `structural_break`**:
    *   **File:** `/root/.openclaw/workspace/jimi_audit/scripts/strategy_configs/failed_breakout.py` (and similar for `structural_break`)
    *   **Action:** Analyze historical trade data for these strategies to identify optimal TP/SL ratios or absolute values that align better with realized price movements and reduce losses. Focus on shortening TP or widening SL for `failed_breakout` to improve profitability, and investigate why `structural_break_LONG` is consistently losing.

2.  **Consider Disabling or Overhauling `scalp_v2`, `regime_switch`, and `failed_breakout` (for longs)**:
    *   **Action:** Given their poor trade outcome win rates and negative Avg. RR, these strategies are detrimental. Either disable them temporarily or initiate a deep dive into their logic. For `failed_breakout`, specifically look into the SHORT direction, which is performing better than LONG.

3.  **Enhance Data Tracking for Filters**:
    *   **Action:** Investigate why `ensemble_passes`, `sweep_blocked`, `m20_blocked`, and `confirmation_status` are not being tracked or have low coverage. Modify relevant scripts (e.g., `deep_analysis_prep.py` or scan data collection scripts) to ensure these critical filter metrics are logged. This is essential for understanding the full pipeline and diagnosing issues.

4.  **Investigate `orderbook_imbalance` and `trade_flow`**:
    *   **Action:** These are the strongest performers. Analyze their high-conviction signals and performance within specific regimes to see if there are opportunities to increase their weight or identify conditions where they perform exceptionally well.

5.  **Monitor Regime Performance**:
    *   **Action:** The current market is heavily `trending_down` (81.8%). Strategy performance within this regime (e.g., `trending_down_SHORT` performing better) should be noted. Be cautious when proposing changes that might be optimized for a `trending_up` or `ranging` market, as those conditions are not currently dominant.
