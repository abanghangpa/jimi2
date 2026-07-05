# MEMORY.md — JIMI Framework Knowledge

## TP/SL Rules (learned 2026-07-02)
- TP=SL=$15 (1:1 R:R) does NOT work — 46% WR, coin flip
- $15 is noise-level for ETH ($1,600 asset, $66 daily range)
- Wide SL ($30) is required to survive intraday noise before $15 TP is hit
- Production config: TP=$15 SL=$30 → 74% WR, +$3.30/trade expected
- 70% WR with equal TP/SL is NOT achievable at $15 granularity

## Signal Quality (learned 2026-07-02)
- Only 2 strategies are profitable: orderbook_imbalance (+0.254 avg_RR) and trade_flow (+0.214)
- regime_switch is the worst: 31.9% WR, fires 100% of scans, should be disabled or capped
- SHORT signals outperform LONG in downtrend periods
- Higher conviction correlates with higher WR (43% for 0.7+ vs 37.6% for 0.5-0.7)
- Simulated direction accuracy (price moved right way) is very different from actual trade outcomes (TP hit before SL)

## Data Quality (learned 2026-07-02)
- Filter fields (ensemble_passes, sweep_blocked, m20_blocked) are NOT persisted in scan files
- Without these fields, filter analysis is meaningless — always check filter_data_quality first
- strategy_signals.jsonl has actual fired signals with entry/SL/TP — use this for outcome analysis, not scan files

## Cron Job Config
- JIMI Deep Analysis: 08:10 UTC, model=free-proxy/qwen/qwen3.6-27b
- Model was changed from openrouter/free due to rate limiting

## TP/SL Update (2026-07-02)
- Changed from TP=$15 SL=$30 to TP=$12 SL=$36 (1:3 R:R)
- Backtest: 79.8% WR, $2.30 EV/trade (vs 72.1% WR, $2.44 EV with old config)
- Rationale: wider SL survives noise, tighter TP hits more often
- Also deployed: strategy-specific volume gating (orderbook_imbalance, trade_flow, cross_asset require vol_ratio > 0.12-0.15)
- Also deployed: EMA200 + vol_ratio in scan output and signal logging

## Session Updates (2026-07-02)
### TP/SL
- TP=$12 SL=$36 (1:3 R:R) replacing TP=$15 SL=$30
- TP: use liquidity pool if beyond $12 minimum
- SL: always enforce $36 minimum

### Volume Gating
- orderbook_imbalance, trade_flow: 0.15
- cross_asset: 0.12

### Scanner Fixes
- EMA200 + vol_ratio in output
- Flip prevention (1h window)
- Entry/SL/TP always shown
- Power of 3 phase-direction fix
- BaseStrategy cfg init fix
