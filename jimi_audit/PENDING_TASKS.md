# JIMI — Pending Tasks (VPS Agent Instructions)

*Updated: 2026-06-23*
*These tasks are ready for autonomous execution. Read this file first, then execute in order.*

---

## Task 1: M72 — Wire in BTC Dominance (CLEANEST WIN)

**Goal:** Make M72 actually contribute to ICS. Currently dead code — exists but never runs.

### Steps

1. **Read the module:**
   ```
   cat jimi_audit/src/modules/m72_btcdom.py
   ```
   Understand the `score_m72_btcdom()` function signature and return format.

2. **Edit `jimi_audit/src/engine.py`:**
   - Add import: `from src.modules.m72_btcdom import score_m72_btcdom` (or whatever the actual function name is — check the file first)
   - In the main scan loop (Phase 4 scoring section), add M72 scoring:
     ```python
     m72_status, m72_score, m72_details = score_m72_btcdom(config=cfg)
     ```
   - Pass to `calc_ics()`: add `m72_score=m72_score` and `use_m72=True` to the call
   - Find the `calc_ics` function signature and confirm it already has `m72_score` and `use_m72` parameters (it does — they default to 0.5 and False)

3. **Set explicit weight in CONFIG:**
   - Find the CONFIG dict in `jimi_audit/src/config.py`
   - Add: `'M72_WEIGHT': 0.10` (or calibrate if you have data)
   - Add: `'M72_ENABLED': True`

4. **Test:**
   ```bash
   cd /root/.openclaw/workspace/jimi_audit
   python3 -c "
   from src.config import CONFIG
   from src.engine import calc_ics
   # Quick sanity check that m72_score param works
   ics = calc_ics(0.5, 0.5, 0.5, 0.5, 0.5, m72_score=0.62, use_m72=True)
   print(f'ICS with M72=0.62: {ics}')
   ics_no = calc_ics(0.5, 0.5, 0.5, 0.5, 0.5, m72_score=0.5, use_m72=False)
   print(f'ICS without M72: {ics_no}')
   "
   ```

5. **Commit:**
   ```bash
   cd /root/.openclaw/workspace
   git add jimi_audit/src/engine.py jimi_audit/src/config.py
   git commit -m "Wire in M72 (BTC Dominance) to ICS scoring"
   git push origin main
   ```

---

## Task 2: M73 — Wire in Stablecoin + Fix Cache Delta

**Goal:** Make M73 contribute to ICS AND fix the fragile cache-based delta mechanism.

### Steps

1. **Read the module:**
   ```
   cat jimi_audit/src/modules/m73_stablecoin.py
   ```
   Note: `_supply_cache` is a module-level global that resets on process restart.

2. **Fix the cache delta:**
   The current logic compares current supply to last-seen supply. Problem: if the scanner misses bars, the delta window is irregular.

   **Fix approach:** Persist `_supply_cache` to a JSON file so it survives restarts:
   ```python
   import json
   
   CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'm73_supply_cache.json')
   
   def _load_cache():
       try:
           with open(CACHE_FILE) as f:
               return json.load(f)
       except (FileNotFoundError, json.JSONDecodeError):
           return {}
   
   def _save_cache(cache):
       with open(CACHE_FILE, 'w') as f:
           json.dump(cache, f)
   ```
   Replace the global `_supply_cache` dict with `_load_cache()` / `_save_cache()` calls.

3. **Edit `jimi_audit/src/engine.py`:**
   - Add import: `from src.modules.m73_stablecoin import score_m73_stablecoin` (check actual function name)
   - In scan loop: `m73_status, m73_score, m73_details = score_m73_stablecoin(config=cfg)`
   - Pass to `calc_ics()`: add `m73_score=m73_score, use_m73=True`

4. **Set explicit weight in CONFIG:**
   - Add: `'M73_WEIGHT': 0.05`
   - Add: `'M73_ENABLED': True`

5. **Test and commit** (same pattern as M72)

---

## Task 3: TradFi Data Pipeline (M66–M71) — BIGGEST LIFT

**Goal:** Create `data/tradfi/aligned.csv` so M66–M71 can actually score in backtest.

### What the file needs

Each row = one ETH 15m bar. Columns:
- `timestamp` — aligned with ETH bars
- `usdjpy` — USD/JPY price (M66)
- `dxy` — DXY index (M67)
- `tnx` — 10Y Treasury yield (M68)
- `vix` — VIX index (M69)
- `wti` — WTI crude oil (M70)
- `gold` — Gold price (M71)

### Steps

1. **Check existing data infrastructure:**
   ```bash
   ls jimi_audit/data/tradfi/ 2>/dev/null
   ls jimi_audit/data/fred/ 2>/dev/null
   ```

2. **Build the pipeline script:** `jimi_audit/scripts/build_tradfi_aligned.py`
   - Use `yfinance` to fetch historical data for each symbol:
     - USD/JPY: `JPY=X`
     - DXY: `DX-Y.NYB`
     - 10Y: `^TNX`
     - VIX: `^VIX`
     - WTI: `CL=F`
     - Gold: `GC=F`
   - Resample each to 15m or forward-fill daily values to 15m grid
   - Align to ETH 15m bar timestamps (read from existing ETH data)
   - Output: `data/tradfi/aligned.csv`

3. **Run it:**
   ```bash
   cd /root/.openclaw/workspace/jimi_audit
   python3 scripts/build_tradfi_aligned.py
   ```

4. **Verify M66–M71 can read it:**
   ```bash
   python3 -c "
   import pandas as pd
   df = pd.read_csv('data/tradfi/aligned.csv')
   print(f'Rows: {len(df)}')
   print(f'Columns: {list(df.columns)}')
   print(f'Null counts:\n{df.isnull().sum()}')
   "
   ```

5. **Fix operator precedence bug in engine.py line ~489:**
   ```python
   # BEFORE (broken):
   if os.path.exists(_tradfi_path) and cfg.get('M66_ENABLED', False) or \
      cfg.get('M67_ENABLED', False) or ...
   
   # AFTER (fixed):
   if os.path.exists(_tradfi_path) and (cfg.get('M66_ENABLED', False) or \
      cfg.get('M67_ENABLED', False) or ...)
   ```

6. **Commit:**
   ```bash
   git add jimi_audit/scripts/build_tradfi_aligned.py jimi_audit/data/tradfi/aligned.csv jimi_audit/src/engine.py
   git commit -m "Add tradfi data pipeline + fix M66-M71 backtest dependency"
   git push origin main
   ```

---

## Important Notes

- **Work in:** `/root/.openclaw/workspace/jimi_audit/`
- **Test before committing** — run a quick scan to make sure nothing breaks:
  ```bash
  cd /root/.openclaw/workspace/jimi_audit
  python3 scripts/scanner.py 2>&1 | tail -20
  ```
- **Don't change weights blindly** — the 0.10 for M72 and 0.05 for M73 are placeholder defaults. If you have backtest data, calibrate.
- **Commit after each task** — don't batch all 3 into one commit.
- **Report results** — after each task, update this file with what you did and any issues.
