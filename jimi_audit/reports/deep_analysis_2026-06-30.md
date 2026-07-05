# JIMI Deep Analysis Report - 2026-06-30

## 📊 Summary Metrics
- **Scans Analyzed:** 1,531
- **Signals Evaluated:** 524 (Signal Rate: 34.2%)
- **Period:** 2026-06-07 to 2026-06-30
- **Dominant Regime:** Trending Down (89.9%)
- **Price Range:** $1,525.16 - $1,819.59

---

## 🛡️ Quality Gate Performance (Critical)
**⚠️ SYSTEM ALERT:** The new multi-layered quality gate architecture is **NOT ACTIVE**.
- **Ensemble Block Rate:** 0% (Consensus Distribution: 100% NONE)
- **Sweep-Against Block Rate:** 0%
- **M20 Block Rate:** 0%
- **Confirmation Rate:** 0% (No signals marked as confirmed)

**Verdict:** The analysis was performed on raw signal data without the filters applied. The "Deep Analysis" agent failed because it expected to analyze filter performance, but the filters are currently bypassing all signals or not being recorded.

---

## 📈 Strategy Performance (Raw)
Top performers by Win Rate (minimum samples):
- **Failed Breakout (8h):** 77.6% WR (Avg Pct: +0.20%) 🚀
- **Trade Flow (2h):** 59.2% WR (Avg Pct: +0.02%)
- **Orderbook Imbalance (2h):** 56.7% WR (Avg Pct: +0.03%)
- **Structural Break (8h):** 29.2% WR (Avg Pct: +0.05%) ❌

**Regime Accuracy:**
- **Trending Down + SHORT:** 58.4% WR (Strongest alignment)
- **Trending Down + LONG:** 52.0% WR (Surprisingly resilient)
- **Ranging + LONG:** 39.1% WR (Weak performance)

---

## 🧠 Regime & Signal Analysis
- **Regime Selector:** The system is heavily biased toward `trending_down` (90%). 
- **ICS Impact:** 
    - High ICS (0.55-0.60) for LONGs is a disaster (25% WR).
    - Low ICS (<0.40) for LONGs is significantly more profitable (58.6% WR).
    - This confirms that "over-conviction" in longs during a downtrend is a primary loss driver.

---

## 🛠️ PROPOSAL: Urgent Architecture Fixes

### 1. Fix Filter Integration
**Issue:** Filter stats are all 0. The ensemble, M20, and Sweep-against gates are not effectively filtering or logging.
**Action:** Audit `scripts/scanner.py` and the ensemble logic to ensure `ensemble_blocked`, `sweep_blocked`, and `m20_blocked` are being correctly incremented and saved to the scan metadata.

### 2. Optimize Hold Windows
**Observation:** 8h windows (Failed Breakout/Structural Break) show the highest win rates and average percentages.
**Action:** Shift the `main_pipeline` default hold window from 2h to 4h-8h for high-conviction strategy matches.

### 3. ICS-Based Veto for Longs
**Observation:** Longs with ICS > 0.55 are failing aggressively.
**Action:** Implement a hard veto for LONG signals when ICS > 0.55 in a `trending_down` regime.

### 4. Structural Break De-weighting
**Observation:** Structural Break (8h) has a dismal 29.2% WR.
**Action:** Reduce the weight of `strategy:structural_break` in the ensemble voting process.
