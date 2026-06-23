# M73 vs M75 Deep Check — Triage Report
*Date: 2026-06-23 | Evaluator: JIMI Evaluator | Protocol: EVAL.md Priority 1*

---

## ⚠️ EXECUTIVE SUMMARY

**Critical finding: M73, M74, and M75 are all DEAD CODE.** None are imported, none are scored in the main scan loop, and none pass actual scores to `calc_ics`. The "overlap" between M73 and M75 is currently moot because neither module is active. However, the architecture reveals a deeper problem: three separate stablecoin/order-flow modules exist with overlapping intent, and if any one were enabled without fixing the integration, it would silently contribute a neutral 0.5 to ICS.

---

## Module Source Analysis

### M73 — Stablecoin Mint Flows (`m73_stablecoin.py`)

| Attribute | Value |
|-----------|-------|
| **Data source** | DeFiLlama `stablecoins.llama.fi` API |
| **Input metric** | USDT + USDC total circulating supply (all chains) |
| **Signal type** | On-chain macro — stablecoin supply delta (mint/burn activity) |
| **Scoring logic** | Computes supply change from a cached previous reading; classifies as MEGA_MINT / LARGE_MINT / LARGE_BURN / NORMAL |
| **Output range (LONG)** | 0.40 (LARGE_BURN) → 0.50 (NORMAL) → 0.58 (LARGE_MINT) → 0.62 (MEGA_MINT) |
| **Output range (SHORT)** | Inverted: 0.38 → 0.50 → 0.42 → 0.60 |
| **Directional mapping** | Large mints = capital queuing to buy crypto = bullish ETH. ✅ Correct. |

**Critical bugs found:**
1. **Not imported in `engine.py`** — no `from src.modules.m73_stablecoin import ...` exists
2. **Not scored in main loop** — `m73_score` is never assigned in the scan loop
3. **Not passed to `calc_ics`** — the call at line 1806 omits `m73_score=` and `use_m73=`
4. **`calc_ics` defaults** — `m73_score=0.5, use_m73=False` (function signature defaults)
5. **Config: `M73_ENABLED: False`** — disabled in config defaults
6. **Cache-based delta is fragile** — `_supply_cache` is module-level global; resets on process restart. In a scanner running once per bar, the "change" is the delta since the last bar's API call, not a calendar day. If the scanner misses bars, the delta is misleading.
7. **No weight in CONFIG** — `M73_WEIGHT` is not set in config defaults; falls back to `cfg.get('M73_WEIGHT', 0.05)` in `calc_ics`

### M74 — USDT Dominance (`m74_usdt_d.py`)

| Attribute | Value |
|-----------|-------|
| **Data source** | CoinGecko `/api/v3/global` API |
| **Input metric** | USDT market cap / total crypto market cap × 100 (USDT.D %) |
| **Signal type** | On-chain macro — relative stablecoin dominance |
| **Scoring logic** | Threshold-based: >4.0% = HIGH_USDT_D (risk-off, score 0.35), <2.5% = LOW_USDT_D (risk-on, score 0.60), else NEUTRAL (0.50) |
| **Output range (LONG)** | 0.35 → 0.50 → 0.60 |
| **Directional mapping** | USDT.D rising = flight to stablecoins = risk-off = bearish ETH. ✅ Correct. |

**Critical bugs found:**
1. **Not imported in `engine.py`**
2. **Not scored in main loop**
3. **Hard-coded neutral in `calc_ics`** — lines 263–267: `m74_score = 0.5` is set unconditionally, then only appended if `M74_ENABLED`. Even if enabled, score is always 0.5.
4. **Config: `M74_ENABLED: False`** — disabled in config defaults
5. **Duplicate function name** — both `m74_usdt_d.py` and `m75_tof.py` define `score_mxx_usdt_d()` with **different signatures**. Import collision risk if both are imported.

### M75 — Toxic Order Flow (`m75_tof.py`)

| Attribute | Value |
|-----------|-------|
| **Data source** | Exchange bar data (close, buy_vol, sell_vol, OI, funding) |
| **Input metric** | Composite of 4 sub-signals: taker persistence, CVD divergence, OI direction, funding contrarian |
| **Signal type** | Exchange microstructure — informed/directional order flow |
| **Scoring logic** | Weighted composite: taker (0.30) + CVD (0.35) + OI (0.20) + funding (0.15) |
| **Output range** | **[-1.0, +1.0]** (clipped) |
| **Directional mapping** | BULL_TOF (>0.35) = informed buying = bullish ETH. BEAR_TOF (<-0.35) = informed selling = bearish ETH. ✅ Correct. |

**Critical bugs found:**
1. **Not imported in `engine.py`**
2. **Not scored in main loop**
3. **Hard-coded neutral in `calc_ics`** — lines 268–272: `m75_score = 0.5` set unconditionally, same pattern as M74
4. **Config: `M75_ENABLED: False`** — disabled in config defaults
5. **OUTPUT RANGE MISMATCH** — TOF score is [-1, +1] but `calc_ics` expects [0, 1] range (all other modules output 0–1). If TOF were actually passed to ICS, a -1.0 score would drag ICS negative, distorting the entire signal.
6. **Misleading function name** — `score_mxx_usdt_d()` in this file is actually the TOF scorer (takes a DataFrame with OHLCV + order flow data), not USDT.D. Name collision with M74's identically-named function.
7. **`score_mxx_usdt_d` returns dict, not tuple** — returns `{"tof_score": ..., "tof_signal": ..., "tof_components": ...}` but JIMI's scoring contract expects `(status, score, details)` tuple. If ever wired in, this would crash.

---

## Five Triage Questions

### 1. SIGNAL DIRECTION — Is the directional mapping to ETH/USDT correct?

| Module | Mapping | Verdict |
|--------|---------|---------|
| M73 | Mint > $1B → bullish (0.62); Burn > $500M → bearish (0.40) | ✅ Correct logic |
| M75 | TOF composite → BULL_TOF (>0.35) = bullish, BEAR_TOF (<-0.35) = bearish | ✅ Correct logic |
| M74 | USDT.D > 4% → risk-off → bearish (0.35); < 2.5% → risk-on → bullish (0.60) | ✅ Correct logic |

**All three have correct directional mappings.** The logic is sound; the problem is none of them are wired in.

### 2. WEIGHT — What is each module's weight in calc_ics?

| Module | Config Key | Default | In CONFIG dict? | Status |
|--------|-----------|---------|-----------------|--------|
| M73 | `M73_WEIGHT` | 0.05 | ❌ Not set | Placeholder fallback |
| M74 | `M74_WEIGHT` | 0.08 | ❌ Not set | Placeholder fallback |
| M75 | `M75_WEIGHT` | 0.10 | ✅ Set (0.10) | Intentional |

**Verdict:** M73 and M74 weights are not explicitly configured — they rely on `cfg.get()` defaults in `calc_ics`. This is a placeholder pattern. M75 has an explicit weight in CONFIG, suggesting it was more intentionally designed.

### 3. OUTPUT RANGE — What range does each module output?

| Module | Actual Output | calc_ics Expects | Match? |
|--------|--------------|-----------------|--------|
| M73 | 0.40 – 0.62 (LONG) | 0.0 – 1.0 | ✅ Within range |
| M74 | 0.35 – 0.60 (LONG) | 0.0 – 1.0 | ✅ Within range |
| M75 (TOF) | **-1.0 to +1.0** | 0.0 – 1.0 | ❌ **RANGE MISMATCH** |
| M75 (wrapper) | Returns dict, not float | (status, score, details) tuple | ❌ **CONTRACT VIOLATION** |

**Verdict:** M75 has a critical output range mismatch. TOF scores go negative, which would corrupt ICS if wired in. The `score_mxx_usdt_d` wrapper returns a dict instead of the expected tuple format.

### 4. DATA FRESHNESS — How often does each module's input data update?

| Module | Data Source | Update Frequency | Staleness Risk |
|--------|-----------|-----------------|----------------|
| M73 | DeFiLlama stablecoins API | Real-time (supply updates within hours of mint events) | ⚠️ Medium — cache-based delta depends on polling frequency |
| M74 | CoinGecko global API | Near-real-time (market cap updates) | ⚠️ Medium — API rate limits may cause gaps |
| M75 | Exchange bar data (OHLCV + OI + funding) | Per-bar (15m) | ✅ Low — fed from live bar data |

**Verdict:** M73 and M74 depend on external APIs with potential rate limits. M73's cache-based delta is fragile — if the scanner misses bars, the delta is computed over an irregular window, not a fixed period.

### 5. INTERACTION RISK — Does this module overlap with any existing module?

| Pair | Overlap? | Details |
|------|----------|---------|
| **M73 vs M75** | ❌ **NO OVERLAP** | M73 measures stablecoin supply changes (on-chain macro). M75 measures order flow toxicity (exchange microstructure). Completely different data, different signals, different timeframes. |
| **M73 vs M74** | ⚠️ **PARTIAL OVERLAP** | Both are stablecoin-related macro signals. M73 = absolute supply change (mint/burn). M74 = relative dominance (% of total market cap). Related but not identical — M73 can be flat while M74 moves (if crypto market cap changes). However, both capture "capital flight to stablecoins" from different angles. |
| **M74 vs M75** | ❌ **NO OVERLAP** | M74 = USDT dominance %. M75 = order flow toxicity. Different signals. |
| **M75 vs M8 (Funding)** | ⚠️ **MINOR** | M75's funding sub-signal (weight 0.15) overlaps with M8 funding rate scorer. Combined, funding gets double-weighted in ICS if both active. |

---

## M73 vs M75 Deep Check

### Input Series Comparison

| Dimension | M73 (Stablecoin) | M75 (TOF) |
|-----------|------------------|-----------|
| **Data source** | DeFiLlama API (off-chain) | Exchange bar data (on-exchange) |
| **Input** | USDT+USDC circulating supply | close, buy_vol, sell_vol, OI, funding |
| **Signal concept** | Macro liquidity inflow | Micro order flow toxicity |
| **Timeframe** | Daily/infrequent (supply changes) | Per-bar (15m) |
| **Response speed** | Slow (hours to days) | Fast (15m bars) |
| **What it captures** | "Is new capital entering crypto?" | "Is informed money trading directionally?" |

### Correlation Assessment

**Cannot compute actual correlation** — both modules are dead code with no historical output data. However, theoretical correlation analysis:

These modules measure fundamentally different things:
- M73 responds to **infrequent, large events** ($500M+ mint events happen a few times per month)
- M75 responds to **continuous, high-frequency signals** (every 15m bar)

**Expected correlation: LOW (<0.30)** — The signals operate on different timescales, different data sources, and measure different market mechanics. A stablecoin mint doesn't immediately cause CVD divergence or taker persistence changes.

### Verdict: NOT A DOUBLE-COUNT

M73 and M75 are **genuinely different signals**:
- M73 = on-chain macro liquidity (stablecoin supply)
- M75 = exchange microstructure (order flow toxicity)

**The real overlap risk flagged in EVAL.md Rule 3 appears to be based on a naming confusion.** M75's file contains a function called `score_mxx_usdt_d` which was likely intended to be a USDT.D scorer, but the actual implementation is the TOF (order flow) scorer with a misleading function name. The real USDT.D scorer is in M74, not M75.

### Actual Double-Count Risk: M73 + M74

If both M73 and M74 were enabled, there would be partial overlap:
- Both measure stablecoin-related sentiment
- M73: absolute supply change
- M74: relative dominance
- Combined weight: 0.05 + 0.08 = 0.13 for stablecoin-related signals
- Not a full double-count (different metrics), but the combined weight for "stablecoin sentiment" would be higher than intended

---

## Triage Verdicts

### M73 (Stablecoin Mint Flows)

| Question | Answer | Status |
|----------|--------|--------|
| Signal direction | Correct (mints = bullish) | ✅ |
| Weight | 0.05 default, not in CONFIG | ⚠️ Placeholder |
| Output range | 0.40–0.62, within 0–1 | ✅ |
| Data freshness | API-dependent, cache-based delta | ⚠️ Fragile |
| Interaction risk | Partial overlap with M74 | ⚠️ |

**Verdict: ⚠️ CAUTION** — Logic is sound but module is dead code. Not imported, not scored, not passed to ICS. If enabled without fixing integration, it would silently contribute 0.5 (neutral) to ICS, adding weight without signal. The cache-based delta mechanism is fragile and would produce misleading signals if polling is irregular.

### M75 (TOF / Toxic Order Flow)

| Question | Answer | Status |
|----------|--------|--------|
| Signal direction | Correct (BULL_TOF = bullish) | ✅ |
| Weight | 0.10, explicitly in CONFIG | ✅ Intentional |
| Output range | **[-1, +1] vs expected [0, 1]** | 🔴 **MISMATCH** |
| Data freshness | Per-bar (15m) | ✅ |
| Interaction risk | Minor overlap with M8 (funding sub-signal) | ⚠️ |
| Function contract | Returns dict, not tuple | 🔴 **VIOLATION** |

**Verdict: 🔴 FIX** — Module has two critical bugs that must be resolved before it can be enabled:
1. Output range [-1, +1] would corrupt ICS (needs normalization to [0, 1])
2. `score_mxx_usdt_d` returns a dict instead of the expected `(status, score, details)` tuple
3. Not imported or scored in engine.py (dead code)

### M74 (USDT Dominance) — bonus finding

| Question | Answer | Status |
|----------|--------|--------|
| Signal direction | Correct (USDT.D rising = risk-off = bearish) | ✅ |
| Weight | 0.08, not in CONFIG | ⚠️ Placeholder |
| Output range | 0.35–0.60, within 0–1 | ✅ |
| Data freshness | CoinGecko API, rate-limited | ⚠️ |
| Interaction risk | Partial overlap with M73 | ⚠️ |
| Calc_ics wiring | Hard-coded `m74_score = 0.5` — **always neutral** | 🔴 **BUG** |

**Verdict: 🔴 FIX** — Even if `M74_ENABLED` is set to True, the score is hard-coded to 0.5 inside `calc_ics`. The module would add weight (0.08) with zero signal, diluting all other modules. This is a silent ICS distortion bug.

---

## Group Verdict

### Are M73/M74/M75 collectively safe to include in the next full backtest?

**NO.**

### Reasoning

| Issue | Severity | Impact |
|-------|----------|--------|
| All 3 modules are dead code (not imported, not scored) | 🔴 Critical | No signal contribution, just architecture confusion |
| M74 hard-coded to 0.5 in calc_ics | 🔴 Critical | If enabled, silently adds 8% weight of pure noise |
| M75 output range mismatch ([-1,1] vs [0,1]) | 🔴 Critical | Would corrupt ICS if wired in |
| M75 returns dict, not tuple | 🔴 Critical | Would crash if called by scanner |
| M73 cache-based delta is fragile | ⚠️ Medium | Unreliable signals if polling is irregular |
| M73/M74 partial overlap | ⚠️ Medium | 13% combined weight for stablecoin sentiment if both enabled |
| M75 funding sub-signal overlaps M8 | ⚠️ Low | Minor double-weighting of funding signal |

### Estimated ICS Distortion Risk: HIGH

If any of these modules were enabled without fixing the integration bugs:
- M74 would add 0.08 weight of pure 0.5 noise (dilutes all real signals by ~8%)
- M75 with [-1,+1] range would drag ICS below 0 in bearish scenarios
- M73 contributes nothing (not wired in) but creates false confidence that stablecoin signals are being monitored

### Recommended Actions

1. **M73/M74/M75 integration must be completed or removed** — dead code that claims to provide signal coverage is worse than no code
2. **M75 output range must be normalized** to [0, 1] before wiring: `normalized = (tof_score + 1) / 2`
3. **M75 `score_mxx_usdt_d` must return the standard tuple** `(status, score, details)` or be renamed
4. **M74 hard-coded `m74_score = 0.5`** in calc_ics must be fixed — either wire in actual scoring or remove the module
5. **Choose one stablecoin signal** — M73 (supply change) or M74 (dominance %), not both. They're related enough that combined 0.13 weight is excessive for the signal class.
6. **Rename M75's `score_mxx_usdt_d`** to `score_m75_tof` to eliminate the naming collision with M74

---

## Failure Modes Confirmed

| Failure Mode from EVAL.md | Status | Evidence |
|---------------------------|--------|----------|
| M73/M75 double-count | ❌ Not active | Both are dead code; no actual double-count occurring |
| Output range mismatch | ✅ **CONFIRMED** | M75 TOF outputs [-1,+1], calc_ics expects [0,1] |
| Weight placeholder | ✅ **CONFIRMED** | M73 weight (0.05) not in CONFIG dict |
| Silent zero-fill | ✅ **CONFIRMED** | M74 hard-coded to 0.5 in calc_ics |
| Function name collision | ✅ **NEW** | Both M74 and M75 define `score_mxx_usdt_d()` with different signatures |

---

## Session Log

```
=== EVAL SESSION ===
Date: 2026-06-23
Module / Phase: M73, M74, M75 / Phase 4
Phase number: 4
Session type: TRIAGE
Upstream phases stable? N/A (not evaluating upstream)
M66–M73 triage complete? IN PROGRESS (this is Priority 1)
Hypothesis: M73 and M75 measure the same underlying signal (stablecoin dominance)
Pass condition: Correlation < 0.85 OR different data sources confirmed
Fail condition: Same data, same signal, both active with non-zero weights

--- POST-EVAL ---
Hypothesis result: FALSIFIED — M73 measures stablecoin supply changes (on-chain macro),
  M75 measures order flow toxicity (exchange microstructure). Completely different signals.
  The real overlap is M73 vs M74, not M73 vs M75.
Baseline metrics: N/A (modules are dead code, no output history)
What improved: Identified 5 critical bugs in module integration
What degraded: N/A
Statistically ambiguous: Cannot compute actual correlation (no output data)
Direction drift detected: N/A
Cascade risk detected: N/A
M73/M75 overlap check: FAIL (not double-count, but both are dead code with integration bugs)
Weight registry verified: NO (M73/M74 weights not in CONFIG)
Verdict: M73=CAUTION, M75=FIX, M74=FIX
Next action: Complete M66–M73 group triage
Cooling period ends: N/A (no changes made)
====================
```
