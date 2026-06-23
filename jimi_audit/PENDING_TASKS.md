# JIMI — Pending Tasks

*Updated: 2026-06-23*

## Next Actions (from M66–M73 triage)

### 1. M72 — Wire in BTC Dominance (CLEANEST WIN)
- Import `score_m72_btcdom` in `engine.py`
- Score in main scan loop
- Pass score to `calc_ics`
- Set explicit weight in CONFIG (currently 0.10 placeholder)
- **Status: NOT STARTED**

### 2. M73 — Wire in Stablecoin + Fix Cache Delta
- Import `score_m73_stablecoin` in `engine.py`
- Score in main scan loop
- Pass score to `calc_ics`
- Fix `_supply_cache` — module-level global resets on restart, delta is misleading on irregular polling
- **Status: NOT STARTED**

### 3. TradFi Data Pipeline (M66–M71) — BIGGEST LIFT
- Build `data/tradfi/aligned.csv` aligning with ETH 15m bars:
  - USD/JPY (M66)
  - DXY (M67)
  - 10Y Treasury yield (M68)
  - VIX (M69)
  - WTI Crude (M70)
  - Gold (M71)
- All 6 modules currently dead in backtest (no data file)
- Also fix operator precedence bug at engine.py line 489
- **Status: NOT STARTED**

## Recently Completed
- [x] M73 vs M75 overlap triage (2026-06-23) — NOT a double-count, different signals
- [x] M66–M73 group triage (2026-06-23) — 6/8 dead (no data), 2/8 dead code
- [x] Session verification report (2026-06-23) — pushed to GitHub
- [x] Liquidity reporter cron fix (2026-06-23) — re-trigger cleared 91 stale errors
