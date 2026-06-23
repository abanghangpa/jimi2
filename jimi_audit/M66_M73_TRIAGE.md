# M66–M73 Group Triage Report
*Date: 2026-06-23 | Evaluator: JIMI Evaluator | Protocol: EVAL.md Priority 2*

---

## ⚠️ EXECUTIVE SUMMARY

**Critical finding: M66–M71 are wired into `calc_ics` but effectively dead in backtest** because the required data file (`data/tradfi/aligned.csv`) does not exist. M72 and M73 are completely dead code — not imported, not scored, not passed to `calc_ics`. All 8 modules use placeholder fallback weights (not explicitly set in CONFIG dict). Collectively, these modules account for up to 0.58 of ICS weight if enabled, but contribute zero signal. The architecture is sound for M66–M71; the problem is missing data infrastructure and placeholder integration for M72–M73.

---

## Module-by-Module Triage

### M66 — USD/JPY Carry Trade Proxy

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | USD/JPY drop + DXY flat = carry unwind → bearish ETH. USD/JPY drop + DXY drop = USD weakness → neutral. DXY cross-check prevents false carry signals. | ✅ Correct |
| **WEIGHT** | `cfg.get('M66_WEIGHT', 0.08)` — fallback default, not in CONFIG dict | ⚠️ Placeholder |
| **OUTPUT RANGE** | 0.0–1.0 (clipped via `max(0.0, min(1.0, score))`) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | Backtest: depends on `data/tradfi/aligned.csv` (usdjpy column). **File does not exist** → all scores default to 0.5 SKIP. Live: uses yfinance 1m bars (real-time). | 🔴 Dead in backtest |
| **INTERACTION RISK** | Partial overlap with M67 (both USD strength proxies). M66 measures carry unwind; M67 measures DXY/ETH divergence. Different mechanics, same underlying USD factor. Combined weight: 0.08 + 0.06 = 0.14 for USD-related signals. | ⚠️ Moderate overlap |

**Verdict: ⚠️ CAUTION** — Logic is sound. DXY cross-check is a good design. But module is dead in backtest (missing tradfi data) and weight is a placeholder.

---

### M67 — DXY Divergence Filter

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | DXY rising + ETH falling = CONFIRMED_BEARISH (0.25). DXY rising + ETH rising = BULLISH_DIVERGENCE (0.70). DXY falling + ETH rising = CONFIRMED_BULLISH (0.75). DXY falling + ETH falling = BEARISH_DIVERGENCE (0.30). | ✅ Correct |
| **WEIGHT** | `cfg.get('M67_WEIGHT', 0.06)` — fallback default, not in CONFIG dict | ⚠️ Placeholder |
| **OUTPUT RANGE** | 0.0–1.0 (no explicit clip, but all branch values are within 0.25–0.75) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | Backtest: `data/tradfi/aligned.csv` (dxy column). **File does not exist** → dead. Live: yfinance DX-Y.NYB 15m bars. | 🔴 Dead in backtest |
| **INTERACTION RISK** | Overlap with M66 (both USD proxies). M67 also uses ETH price directly, which most other modules don't — this is actually a unique input. | ⚠️ Moderate overlap with M66 |

**Verdict: ⚠️ CAUTION** — Good design (divergence detection is more informative than raw DXY). Dead in backtest. Placeholder weight.

---

### M68 — 10Y Treasury Yield + TIPS Real Yield

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | 10Y yield spike = bearish ETH (rate hike risk). TIPS cross-check distinguishes inflation-driven (bearish) from growth-driven (ambiguous). Extreme spike (>10bps/1h) = suppress longs regardless. | ✅ Correct |
| **WEIGHT** | `cfg.get('M68_WEIGHT', 0.10)` — fallback default, not in CONFIG dict. Highest weight among M66–M73. | ⚠️ Placeholder (and disproportionately high) |
| **OUTPUT RANGE** | 0.0–1.0 (all branch values: 0.15, 0.25, 0.30, 0.40, 0.50) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | Backtest: `data/tradfi/aligned.csv` (tnx column). **File does not exist** → dead. Live: yfinance ^TNX 1h bars. TIPS: **SPOOFED** — `fetch_tips_yield()` returns None with a warning. TIPS cross-check never activates. | 🔴 Dead in backtest; TIPS disabled |
| **INTERACTION RISK** | None identified. Unique signal (yield curve). | ✅ No overlap |

**Verdict: ⚠️ CAUTION** — Best-designed module in the group (inflation/growth decomposition). But dead in backtest, TIPS is spoofed, and 0.10 weight is disproportionately high for an unvalidated module.

---

### M69 — VIX Regime Classifier

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | Non-linear VIX/ETH relationship with crisis type detection. VIX > 30 + DXY falling = LIQUIDITY_CRISIS → contrarian long (0.60). VIX > 30 + DXY rising = STRUCTURAL_BREAK → stay short (0.25). Rate-of-change override: spike >3pts = immediate risk-off. | ✅ Correct (innovative) |
| **WEIGHT** | `cfg.get('M69_WEIGHT', 0.08)` — fallback default, not in CONFIG dict | ⚠️ Placeholder |
| **OUTPUT RANGE** | 0.0–1.0 (all branch values: 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | Backtest: `data/tradfi/aligned.csv` (vix column). **File does not exist** → dead. Live: yfinance ^VIX daily bars (15min delayed). | 🔴 Dead in backtest |
| **INTERACTION RISK** | M69 (VIX fear gauge) vs M9 (vol regime classifier). EVAL.md flags this. Analysis: M9 classifies ETH's own vol regime (ATR-based); M69 measures equity market fear (S&P options). **Different data, different markets, different signals.** Minor conceptual overlap in CRISIS regime (both would flag extreme conditions), but the mechanisms are genuinely different. | ✅ No meaningful overlap |

**Verdict: ⚠️ CAUTION** — Best crisis-type classification logic in the framework. Dead in backtest. Placeholder weight. No real overlap with M9.

---

### M70 — WTI Crude Oil

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | Oil spike + DXY up = SUPPLY_SHOCK → bearish (0.25). Oil spike + DXY down = DEMAND_RISK_ON → neutral (0.50). Oil drop + DXY up = RECESSION_FEAR → slightly bearish (0.45). Oil drop + DXY down = REFLATION_EASING → mildly bullish (0.60). | ⚠️ Weak rationale |
| **WEIGHT** | `cfg.get('M70_WEIGHT', 0.05)` — fallback default, not in CONFIG dict | ⚠️ Placeholder |
| **OUTPUT RANGE** | 0.0–1.0 (all branch values: 0.25, 0.45, 0.50, 0.60) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | Backtest: `data/tradfi/aligned.csv` (wti column). **File does not exist** → dead. Live: yfinance CL=F 4h bars. | 🔴 Dead in backtest |
| **INTERACTION RISK** | None identified. Unique signal (commodity). | ✅ No overlap |

**Verdict: ⚠️ CAUTION** — Weakest signal rationale in the group. The oil→ETH mapping is indirect (oil → inflation → rates → ETH) and only triggers on >3% moves on 4h bars, which is rare. Mostly harmless (defaults to NEUTRAL). Dead in backtest. Placeholder weight.

---

### M71 — Gold + DXY Geopolitical Filter

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | Gold up + DXY up = GEOPOLITICAL_SAFE_HAVEN → bearish ETH (0.25). Gold up + DXY down = FIAT_DEBASEMENT → bullish ETH (0.65). Critical correction documented: "Gold and ETH only co-move during fiat debasement. During geopolitical crises, gold rallies while ETH crashes." | ✅ Correct (well-documented) |
| **WEIGHT** | `cfg.get('M71_WEIGHT', 0.06)` — fallback default, not in CONFIG dict | ⚠️ Placeholder |
| **OUTPUT RANGE** | 0.0–1.0 (all branch values: 0.25, 0.35, 0.50, 0.65) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | Backtest: `data/tradfi/aligned.csv` (gold column). **File does not exist** → dead. Live: yfinance GC=F 4h bars. | 🔴 Dead in backtest |
| **INTERACTION RISK** | None identified. Unique signal (precious metal + geopolitical). | ✅ No overlap |

**Verdict: ⚠️ CAUTION** — Excellent design. The geopolitical vs fiat-debasement distinction is historically validated (Ukraine Feb 2022, Oct 2023 Middle East). Dead in backtest. Placeholder weight.

---

### M72 — BTC Dominance

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | BTC.D > 55% = BTC_DOMINANT → ETH underperforms (0.38). BTC.D < 48% = ALTCOIN_SEASON → ETH outperforms (0.62). | ✅ Correct |
| **WEIGHT** | `cfg.get('M72_WEIGHT', 0.10)` — fallback default, not in CONFIG dict. Highest weight alongside M68. | ⚠️ Placeholder (disproportionately high) |
| **OUTPUT RANGE** | 0.0–1.0 (branch values: 0.38, 0.50, 0.62) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | CoinGecko `/api/v3/global` API (real-time). No backtest data source — would need historical BTC.D data. | ⚠️ Live-only; no backtest path |
| **INTERACTION RISK** | None identified. Unique signal (altcoin rotation). | ✅ No overlap |
| **INTEGRATION** | **Not imported in engine.py. Not scored in main loop. Not passed to calc_ics.** Dead code. | 🔴 Dead code |

**Verdict: 🔴 FIX** — Sound logic, correct direction, but completely unwired. Must be imported, scored, and passed to `calc_ics` before it contributes anything. Weight of 0.10 is disproportionately high for an unvalidated module.

---

### M73 — Stablecoin Mint Flows

| Question | Answer | Verdict |
|----------|--------|---------|
| **SIGNAL DIRECTION** | >$1B mint = MEGA_MINT → bullish (0.62). >$500M mint = LARGE_MINT → bullish (0.58). >$500M burn = LARGE_BURN → bearish (0.40). | ✅ Correct |
| **WEIGHT** | `cfg.get('M73_WEIGHT', 0.05)` — fallback default, not in CONFIG dict | ⚠️ Placeholder |
| **OUTPUT RANGE** | 0.0–1.0 (branch values: 0.40, 0.50, 0.58, 0.62) | ✅ Matches calc_ics |
| **DATA FRESHNESS** | DeFiLlama `stablecoins.llama.fi` API. Cache-based delta (`_supply_cache` is module-level global). Resets on process restart. Delta is computed from last polling interval, not a fixed period. **Fragile.** | ⚠️ Fragile |
| **INTERACTION RISK** | Partial overlap with M74 (USDT.D). M73 = absolute supply change. M74 = relative dominance %. Related but not identical. Combined stablecoin signal weight: 0.05 + 0.08 = 0.13. | ⚠️ Moderate overlap with M74 |
| **INTEGRATION** | **Not imported in engine.py. Not scored in main loop. Not passed to calc_ics.** Dead code. | 🔴 Dead code |

**Verdict: 🔴 FIX** — Same finding as M73/M75 triage. Dead code with fragile cache mechanism. Must be wired in or removed.

---

## Cross-Module Analysis

### DXY Dependency Map

M66, M67, M68, M69, M70, M71 all use DXY as a cross-check input. This is intentional — DXY is the macro denominator. But it means:

1. **If DXY data is missing/stale, 6 modules degrade simultaneously.** All would default to their non-DXY classification (less accurate).
2. **DXY is fetched once per bar** from the aligned tradfi CSV. If the CSV has gaps, all 6 modules are affected.
3. **No DXY staleness check exists.** If the tradfi data is 24h old (weekend gap), all modules would use Friday's DXY for Saturday's scan.

### Combined Weight Budget

| Module | Default Fallback Weight | In CONFIG? | Actually Wired? |
|--------|------------------------|------------|-----------------|
| M66 | 0.08 | ❌ | ✅ (but dead — no data) |
| M67 | 0.06 | ❌ | ✅ (but dead — no data) |
| M68 | 0.10 | ❌ | ✅ (but dead — no data) |
| M69 | 0.08 | ❌ | ✅ (but dead — no data) |
| M70 | 0.05 | ❌ | ✅ (but dead — no data) |
| M71 | 0.06 | ❌ | ✅ (but dead — no data) |
| M72 | 0.10 | ❌ | ❌ Dead code |
| M73 | 0.05 | ❌ | ❌ Dead code |
| **Total** | **0.58** | — | — |

**If all 8 were enabled with fallback weights, they would consume 58% of ICS.** This is dangerous — it would dilute the validated M1–M5 base modules to 42% of ICS. The weights appear to be round-number placeholders, not calibrated values.

### Operator Precedence Bug (engine.py:489–492)

```python
if os.path.exists(_tradfi_path) and cfg.get('M66_ENABLED', False) or \
   cfg.get('M67_ENABLED', False) or cfg.get('M68_ENABLED', False) or \
   cfg.get('M69_ENABLED', False) or cfg.get('M70_ENABLED', False) or \
   cfg.get('M71_ENABLED', False):
```

Python `and` binds tighter than `or`. This evaluates as:
`(exists AND M66) OR M67 OR M68 OR M69 OR M70 OR M71`

If M67–M71 are enabled but M66 is not, and the file doesn't exist, the code will still attempt to load it (and fail in the try/except). **Low severity** — the try/except catches it — but it's a logic bug that should be fixed with parentheses.

---

## Failure Modes Checklist (from EVAL.md)

| Failure Mode | Status | Evidence |
|---|---|---|
| M73/M75 double-count | ✅ Already resolved | M73/M75 triage confirmed different signals |
| M66/M67 double-count | ⚠️ **ACTIVE** | Both are USD proxies; combined 0.14 weight if enabled |
| Phase contamination | N/A | Triage, not deep eval |
| Direction drift | N/A | Not evaluating direction |
| Weight placeholder | ✅ **CONFIRMED** | All 8 modules use cfg.get() fallbacks, not CONFIG dict |
| Output range mismatch | ✅ All correct | All modules output 0.0–1.0 |
| VIX fixed threshold | ❌ **FALSIFIED** | M69 uses adaptive thresholds with crisis-type classification |
| WTI rationale missing | ⚠️ **PARTIAL** | Rationale exists (oil→inflation→rates→ETH) but is weak and indirect |
| Gold interpretation flip | ❌ **FALSIFIED** | M71 explicitly documents geopolitical vs fiat-debasement distinction |
| Silent zero-fill | ✅ **CONFIRMED** | All 6 tradfi modules silently default to 0.5 when tradfi data missing |

---

## Triage Verdicts

| Module | Verdict | Rationale |
|--------|---------|-----------|
| **M66** | ⚠️ CAUTION | Sound logic, DXY cross-check. Dead in backtest (no tradfi data). Placeholder weight. |
| **M67** | ⚠️ CAUTION | Good divergence design. Dead in backtest. Placeholder weight. Overlap with M66. |
| **M68** | ⚠️ CAUTION | Best design (inflation/growth decomposition). Dead in backtest. TIPS spoofed. Disproportionate weight. |
| **M69** | ⚠️ CAUTION | Innovative crisis-type classification. Dead in backtest. Placeholder weight. No real M9 overlap. |
| **M70** | ⚠️ CAUTION | Weakest rationale. Dead in backtest. Mostly harmless (defaults to NEUTRAL). |
| **M71** | ⚠️ CAUTION | Excellent geopolitical filter. Dead in backtest. Placeholder weight. |
| **M72** | 🔴 FIX | Sound logic but completely dead code — not imported, not scored, not passed to calc_ics. |
| **M73** | 🔴 FIX | Same as M73/M75 triage — dead code with fragile cache mechanism. |

---

## Group Verdict

### Are M66–M73 collectively safe to include in the next full backtest?

**NO.**

### Reasoning

| Issue | Severity | Impact |
|-------|----------|--------|
| `data/tradfi/aligned.csv` does not exist | 🔴 Critical | M66–M71 all score 0.5 SKIP in backtest — zero signal contribution |
| M72 not imported/scored/passed | 🔴 Critical | Dead code; contributes nothing even if "enabled" |
| M73 not imported/scored/passed | 🔴 Critical | Dead code; same as M73/M75 triage finding |
| All weights are placeholder fallbacks | ⚠️ Medium | No explicit CONFIG entries; weights are round numbers, not calibrated |
| Combined weight budget = 0.58 | 🔴 Critical | Would dilute validated M1–M5 base to 42% of ICS |
| M66/M67 USD overlap (0.14 combined) | ⚠️ Medium | Double-counting USD strength signal |
| TIPS spoofed in M68 | ⚠️ Low | Inflation/growth decomposition disabled; only nominal yield used |
| M73 cache-based delta fragile | ⚠️ Medium | Irregular polling → misleading supply change signals |
| Operator precedence bug (line 489) | ⚠️ Low | try/except catches it, but logic is wrong |

### Estimated ICS Distortion Risk: LOW (currently) → HIGH (if force-enabled)

**Currently LOW** because all 8 modules are effectively dead — they contribute 0.5 (neutral) or are not wired in. No distortion occurs because no signal passes through.

**Would be HIGH if force-enabled** because:
1. M66–M71 would need `data/tradfi/aligned.csv` to exist and be properly aligned with ETH bars
2. M72–M73 would need to be imported, scored, and passed to `calc_ics`
3. Combined 0.58 weight with uncalibrated scores would dilute validated modules
4. No backtest validation has been performed on any of these modules

### Recommended Actions (Priority Order)

1. **Create `data/tradfi/aligned.csv`** — This is the blocking dependency for M66–M71. Build a data pipeline that aligns USD/JPY, DXY, 10Y yield, VIX, WTI, and gold with ETH 15m bars. Without this, these 6 modules are dead weight in the codebase.

2. **Wire in M72 and M73** — Import `score_m72_btcdom` and `score_m73_stablecoin` in engine.py. Add scoring code in the main loop. Pass scores to `calc_ics`. OR: explicitly disable and remove from the ENABLED config keys to avoid confusion.

3. **Set explicit weights in CONFIG** — Replace all `cfg.get('M*_WEIGHT', X)` fallbacks with explicit CONFIG dict entries. Total weight budget for M66–M73 should be ≤ 0.20 (not 0.58) to avoid diluting the validated base.

4. **Fix operator precedence bug** — Line 489: add parentheses around the OR chain.

5. **Choose one stablecoin signal** — M73 (supply change) or M74 (dominance %), not both. Per M73/M75 triage recommendation.

6. **Un-spoof TIPS** — M68's inflation/growth decomposition is its key innovation. The FRED API call should be implemented properly.

7. **Validate against baseline** — After data infrastructure is built, run each module individually against the frozen baseline (298,649 bars) before enabling all 8 together.

---

## Session Log

```
=== EVAL SESSION ===
Date: 2026-06-23
Module / Phase: M66–M73 / Phase 4
Phase number: 4
Session type: TRIAGE (group)
Upstream phases stable? N/A (not evaluating upstream)
M66–M73 triage complete? YES (this session)
Hypothesis: M66–M73 are safe to include in the next full backtest
Pass condition: All 8 modules have correct direction, intentional weights, valid output ranges, and are properly wired
Fail condition: Any module has broken integration, placeholder weights, or dead code status

--- POST-EVAL ---
Hypothesis result: FALSIFIED — 6/8 modules are dead (no data file), 2/8 are dead code (not wired)
What improved: Identified all integration gaps, weight placeholders, and data dependencies
What degraded: N/A
Statistically ambiguous: Cannot validate signal quality (no backtest data)
Direction drift detected: N/A
Cascade risk detected: N/A — all modules default to 0.5, no cascade possible
M73/M75 overlap check: RESOLVED (per M73/M75 triage — different signals)
Weight registry verified: NO — all 8 use cfg.get() fallbacks, not CONFIG dict
Verdict: M66=CAUTION, M67=CAUTION, M68=CAUTION, M69=CAUTION, M70=CAUTION, M71=CAUTION, M72=FIX, M73=FIX
Group verdict: NO — not safe for next backtest
ICS distortion risk: LOW (currently dead) → HIGH (if force-enabled without fixes)
Next action: Build tradfi data pipeline; wire in M72/M73; set explicit weights
Cooling period ends: N/A (no changes made)
====================
```
