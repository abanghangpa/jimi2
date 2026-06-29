# JIMI Deep Analysis Session Log — 2026-06-29

## Session Summary

Deep-dive evaluation of JIMI Framework performance. Discovered the original daily 8 UTC cron job was lost during migration. Rebuilt it with a two-step architecture (Python pre-processor → agent analysis). Found and fixed a critical metadata bug. Defended the framework against a misleading initial report. Identified the real weaknesses.

---

## 1. Cron Job Recovery

**Problem:** The "JIMI Deep Analysis" cron job (ID: 180b4db7) was lost during OpenClaw migration. It existed in session history but not in the current cron store. Two prior runs failed ("assistant turn failed before producing content") — likely due to token limits from reading 1,340+ raw JSON scan files.

**Fix:** Created a new cron job with a two-step architecture:
- **Step 1:** Python pre-processor (`deep_analysis_prep.py`) crunches all scan files into a compact ~23KB summary JSON
- **Step 2:** Agent reads the summary and generates the proposal report

**New Job ID:** `863f3058-a8af-44d0-8170-47282a325819`
- Schedule: Daily 08:00 UTC (exact)
- Delivery: WhatsApp → +601112827947
- Also saves to: `jimi_audit/reports/deep_analysis_YYYY-MM-DD.md`
- Tools allowed: exec, read, write

---

## 2. Original Report Critique

The first deep analysis report made several claims that were misleading:

### Claim: "24h LONG win rate = 15.3% (Critical Failure)"
**Reality:** JIMI is a 15-minute scanner. Judging it on 24h win rate is evaluating a scalpel as a sword. The 1h LONG win rate was 53.9% — respectable for a 15m system.

### Claim: "Higher ICS (0.55-0.60) = 0.0% win rate on 24h"
**Reality:** This bucket had only 2-3 samples. Drawing conclusions from single-digit trades is noise, not signal. The report didn't check sample sizes.

### Claim: "m10 has 39.3% pass rate — needs investigation"
**Reality:** A 60% rejection rate could mean m10 is doing its job as a macro filter. Low pass rate ≠ broken.

### Claim: "Weekend signal rate >90% — suspicious"
**Reality:** Weekend crypto has different liquidity dynamics. Needs investigation but shouldn't be assumed wrong.

### Claim: "Implement Regime Hard-Stop for LONG in BEARISH"
**Reality:** Would kill mean-reversion setups. The squeeze system already handles oversold bounces. Adding another gate risks over-filtering.

---

## 3. Framework Defense — What's Actually Working

After building a hold-window-aware evaluation (v2 prep script), the real picture emerged:

### Strong Performers
- **failed_breakout** @ 8h: **79.4% WR** (n=34) — best strategy
- **orderbook_imbalance** @ 2h: **60.2% WR** (n=108) — solid, high volume
- **trade_flow** @ 2h: **62.3% WR** (n=70) — solid
- **LONG @ 2h: 62.2% WR** (n=82) — the "broken" LONG signals work at correct timeframe
- **SHORT @ 2h: 61.5% WR** (n=96) — both directions work at 2h

### Key Insight
The original report's "24h LONG at 15.3% WR" was measuring the wrong thing. At the correct 2h hold window, LONG signals are 62.2% accurate.

---

## 4. Metadata Bug Found & Fixed

**Bug:** Line 3743 of `scanner.py` — the main pipeline sets `status: 'SIGNAL'` but never sets `source`. The `source` field was only set in the multi-strategy fallback (line 5611).

**Impact:** 172 main pipeline signals had `source: None`, causing the prep script to classify them as "unknown" with a 4h hold window (wrong — they're 15m signals, should be 2h).

**Fix:** Added `'source': 'main_pipeline'` to line 3743.
- Backup saved: `scanner.py.bak_pre_source_fix`
- Committed: `3736e44`

**Result:** New scans will properly tag main pipeline signals. Tomorrow's 08:00 UTC analysis will have clean data.

---

## 5. Structural Break Deep Dive — The Real Problem

### Findings
- **structural_break** strategy: **29.2% WR** (n=24, 8h hold)
- ALL 24 signals fired in 48 hours (June 27-28) — clustered burst, not distributed
- ALL 24 in STRONG_DOWN + BEARISH swing bias
- ICS range: 0.313-0.525 (very low, bypassed by squeeze or M20)

### Root Cause: M13 Is Anti-Predictive
- M13 BULLISH → LONG: **44.3% WR** (n=379) — worse than coin flip
- M13 BEARISH → SHORT: **46.2% WR** (n=599) — barely better
- M13 BULLISH in DOWN trend → LONG: **44.6% WR** (n=269)

M13 is essentially a random signal with a slight negative bias when bullish. The structural_break strategy builds on this broken foundation.

### What Happened June 27-28
- June 27: M13 flipped BULLISH (score 0.90) during STRONG_DOWN. 11 LONG signals. Price kept dropping. 2W/9L.
- June 28: M13 flipped BEARISH. 13 SHORT signals. Price bounced. 5W/8L.
- M13 was late on both flips — turned bullish after move exhausted, bearish after bounce started.

### Recommended Fixes (Pending)
1. **Quick:** Add trend gate — don't fire LONG when trend_dir is STRONG_DOWN
2. **Medium:** Replace M13 with better directional input (M1 MACD? M2 EMA?)
3. **Nuclear:** Disable structural_break entirely (29.2% WR = actively harmful)

---

## 6. Other Findings Worth Investigating

### Squeeze Bypass Path
The squeeze system bypasses the ICS gate when confirmed. Need to audit:
- How many signals came through squeeze bypass?
- Were they profitable?
- Is the bypass too permissive?

### LONG 0.55-0.60 ICS = 13.3% WR vs SHORT 0.55-0.60 = 80.0% WR
Same conviction bucket, opposite results. Is the direction resolver broken for LONG at this level? Or is the bearish market regime making LONG conviction signals toxic?

### Directional ICS Gating
The original report suggested raising LONG ICS threshold to 0.60 in bearish markets. While the report's reasoning was flawed, this specific idea has merit for the 0.55-0.60 bucket where LONG performs terribly.

---

## 7. Files Changed This Session

| File | Change |
|------|--------|
| `scripts/scanner.py` | Added `'source': 'main_pipeline'` to main signal output (line 3743) |
| `scripts/deep_analysis_prep.py` | New v2 with hold-window-aware evaluation, min sample threshold, regime segmentation |
| `scripts/scanner.py.bak_pre_source_fix` | Backup before source fix |
| `data/deep_analysis_summary.json` | Updated summary with new analysis |

## 8. Pending for Next Session

- [ ] Implement trend gate for structural_break (quick fix)
- [ ] Investigate squeeze bypass path profitability
- [ ] Analyze LONG vs SHORT at 0.55-0.60 ICS bucket
- [ ] Evaluate replacing M13 as directional input for structural_break
- [ ] Review tomorrow's 08:00 UTC deep analysis report (first clean run with source tracking)
- [ ] Consider adding `main_pipeline` to the hold window mapping once enough data accumulates

---

*Session: 2026-06-29 04:00-05:10 UTC*
*VPS: 72.62.73.46*
*Commits: 3736e44*
