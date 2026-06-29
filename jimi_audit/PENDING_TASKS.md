# JIMI — Pending Tasks (VPS Agent Instructions)

*Updated: 2026-06-29*
*All original tasks completed. See STRATEGY_ROADMAP.md for remaining strategy work.*

---

## ✅ Task 1: M72 — Wire in BTC Dominance — DONE

- M72 wired into engine.py (import, scoring, calc_ics)
- Config: `M72_ENABLED: True`, `M72_WEIGHT: 0.04`
- Cache: re-fetches BTC.D every 96 bars (24h)

## ✅ Task 2: M73 — Wire in Stablecoin + Fix Cache Delta — DONE

- M73 wired into engine.py (import, scoring, calc_ics)
- Config: `M73_ENABLED: True`, `M73_WEIGHT: 0.05`
- Cache: `data/m73_supply_cache.json` persists across restarts

## ✅ Task 3: TradFi Data Pipeline (M66–M71) — DONE

- `data/tradfi/aligned.csv` exists (277K rows)
- M66–M71 all have config keys (ENABLED, WEIGHT, thresholds)
- Modules wired into engine.py

---

## Remaining Work

See `STRATEGY_ROADMAP.md` for pending strategy upgrades (s05, s06, s07, s11, outcome tracker).
