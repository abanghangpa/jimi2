# M66–M73 Group Triage Report — CORRECTED
*Date: 2026-06-24 | Evaluator: JIMI Evaluator | Protocol: EVAL.md Priority 2*

---

## ⚠️ CORRECTION NOTICE

**Original triage (2026-06-23) incorrectly stated M72 and M73 were "dead code — not imported, not scored, not passed to calc_ics."** This is wrong. Verification of engine.py confirms:
- M72 IS scored (lines 1786–1800) and passed to calc_ics (line 265)
- M73 IS scored (lines 1802–1820) and passed to calc_ics (line 268)
- Both have been wired in since the original code was written

The original triage also failed to verify the actual code before making claims. This correction is important: **always verify against source, not assumptions.**

---

## Changes Made (2026-06-24)

### 1. Created `data/tradfi/aligned.csv` — BLOCKING DEPENDENCY RESOLVED ✅

Built `data/build_tradfi_aligned.py` pipeline script that:
- Fetches USD/JPY, DXY, 10Y yield, VIX, WTI, Gold via yfinance
- Aligns to ETH 15m bar timestamps (277,006 bars)
- Forward-fills daily data onto 15m grid
- Coverage: 2018-01-01 → 2025-12-31 (100% fill rate)

**Limitation**: Uses daily data forward-filled to 15m bars. M66/M67/M68/M70/M71 use ROC calculations that require intraday movement — these will return NEUTRAL on most bars. M69 (VIX) works well because it uses level-based thresholds. For full signal fidelity, intraday tradfi data (15m/1h bars) would be needed.

### 2. Fixed operator precedence bug (engine.py line 492) ✅

**Before**: `if os.path.exists(...) and cfg.get('M66_ENABLED') or cfg.get('M67_ENABLED') or ...`
**After**: `if os.path.exists(...) and (cfg.get('M66_ENABLED') or cfg.get('M67_ENABLED') or ...)`

Python `and` binds tighter than `or`. Without parentheses, M67-M71 could trigger tradfi data loading even if the file didn't exist (caught by try/except, but still a logic bug).

### 3. Set explicit weights in CONFIG ✅

| Module | Old Weight | New Weight | Rationale |
|--------|-----------|-----------|-----------|
| M66 | 0.08 (fallback) | 0.02 | USD/JPY carry — daily data limitation |
| M67 | 0.06 (fallback) | 0.02 | DXY divergence — daily data limitation |
| M68 | 0.10 (fallback) | 0.03 | 10Y yield — TIPS still spoofed |
| M69 | 0.08 (fallback) | 0.03 | VIX — works well with daily data |
| M70 | 0.05 (fallback) | 0.02 | WTI — weakest rationale |
| M71 | 0.06 (fallback) | 0.02 | Gold — daily data limitation |
| M72 | 0.10 | 0.04 | BTC.D — reduced from disproportionate 0.10 |
| M73 | 0.05 (fallback) | 0.02 | Stablecoin — fragile cache mechanism |
| **Total** | **0.58** | **0.20** | Within recommended budget |

### 4. Enabled M66-M71 in CONFIG ✅

All modules set to `M66_ENABLED: True` through `M71_ENABLED: True`.

---

## Updated Module Status

| Module | Verdict | Status After Fix |
|--------|---------|-----------------|
| **M66** | ⚠️ CAUTION | Enabled. Data exists. Daily granularity limits signal. Weight: 0.02 |
| **M67** | ⚠️ CAUTION | Enabled. Data exists. Daily granularity limits signal. Weight: 0.02 |
| **M68** | ⚠️ CAUTION | Enabled. Data exists. TIPS still spoofed. Weight: 0.03 |
| **M69** | ✅ PASS | Enabled. Works well with daily data (level-based). Weight: 0.03 |
| **M70** | ⚠️ CAUTION | Enabled. Weakest rationale. Weight: 0.02 |
| **M71** | ⚠️ CAUTION | Enabled. Data exists. Daily granularity limits signal. Weight: 0.02 |
| **M72** | ✅ PASS | Was always wired in. Weight reduced: 0.10 → 0.04 |
| **M73** | ✅ PASS | Was always wired in. Weight reduced: 0.05 → 0.02 |

---

## Remaining Issues (not blocking, but noted)

1. **TIPS still spoofed in M68** — Inflation/growth decomposition disabled. Only nominal yield used.
2. **M73 cache-based delta fragile** — Irregular polling → misleading supply change signals.
3. **M66/M67 USD overlap** — Combined weight reduced to 0.04 (was 0.14). Acceptable.
4. **Daily data limitation** — M66/M67/M68/M70/M71 ROC calculations will show zero intraday movement. For full signal fidelity, need intraday tradfi data (15m/1h bars).

---

## Validation Results

```
M66 (USD/JPY): ✅ Scores correctly (NEUTRAL on normal days — expected with daily data)
M67 (DXY):     ✅ Scores correctly (NEUTRAL on normal days)
M68 (Yield):   ✅ Scores correctly (NEUTRAL on normal days)
M69 (VIX):     ✅ Scores correctly (PASS with COMPLACENT/ELEVATED classifications)
M70 (WTI):     ✅ Scores correctly (NEUTRAL on normal days)
M71 (Gold):    ✅ Scores correctly (NEUTRAL on normal days)
M72 (BTC.D):   ✅ Scores correctly (BTC.D=56.3% → PASS, score=0.380)
M73 (Stable):  ✅ Scores correctly (NORMAL classification)
```

---

## Session Log

```
=== EVAL SESSION ===
Date: 2026-06-24
Module / Phase: M66–M73 / Phase 4 (fix session)
Phase number: 4
Session type: FIX + CORRECTION
Upstream phases stable? YES
M66–M73 triage complete? YES (corrected)

--- POST-EVAL ---
What improved:
  - Created tradfi data pipeline (277K bars, 100% fill)
  - Fixed operator precedence bug
  - Set explicit weights (total: 0.58 → 0.20)
  - Enabled M66-M71 in CONFIG
  - Corrected false claim that M72/M73 were dead code

What degraded: N/A
Statistically ambiguous: Daily data limitation for ROC-based modules
Direction drift detected: N/A (no backtest run yet)
Cascade risk detected: N/A (weights reduced, not increased)
Weight registry verified: YES — all 8 have explicit CONFIG entries
Verdict: M66=CAUTION, M67=CAUTION, M68=CAUTION, M69=PASS, M70=CAUTION, M71=CAUTION, M72=PASS, M73=PASS
Group verdict: CONDITIONAL — safe for next backtest with noted limitations
ICS distortion risk: LOW (weights reduced to 0.20 total)
Next action: Run full backtest to measure ICS contribution; consider intraday tradfi data for M66/M67/M68/M70/M71
Cooling period ends: 2026-06-26
====================
```
