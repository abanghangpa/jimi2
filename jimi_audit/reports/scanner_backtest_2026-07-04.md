# Scanner Backtest Report — 2026-07-04

## Summary
Backtest of JIMI scanner's 22 strategies using 4,117 fired signals (Jun 27 - Jul 4).
**Result:** Only 3 strategies profitable. Scanner should keep its liquidity-based TP/SL, NOT use fixed %.

## Strategy Performance (Default TP/SL)

| Strategy | Signals | WR | PF | DD | Capital | Status |
|----------|---------|-----|-----|-----|---------|--------|
| trade_flow | 779 | 53.7% | 1.17 | 65.5% | $27,592 | Best |
| cross_asset | 346 | 53.1% | 1.25 | 77.6% | $15,631 | Strong |
| orderbook_imbalance | 410 | 54.5% | 1.28 | 50.0% | $2,243 | Good |
| funding_arb | 418 | 48.8% | 1.09 | 96.4% | $355 | Marginal |
| structural_break | 140 | 42.5% | 0.95 | 89.1% | $128 | Bad |
| mtf_confluence | 256 | 39.7% | 0.90 | 94.5% | $63 | Bad |
| scalp_v2 | 502 | 37.3% | 0.86 | 93.9% | $21 | Bad |
| failed_breakout | 760 | 38.9% | 0.69 | 99.1% | $12 | Bad |
| regime_switch | 481 | 36.1% | 0.74 | 99.8% | $1 | Worst |

## Key Findings
1. trade_flow is best: $27,592, 53.7% WR, 1.17 PF
2. cross_asset second: $15,631, 53.1% WR, 1.25 PF
3. orderbook_imbalance highest WR (54.5%) but fewer signals
4. Scanner TP/SL is liquidity-based, NOT fixed % — do not replace
5. regime_switch is worst: 36.1% WR, nearly blows up every time
6. Only 3/10 strategies consistently profitable

## Recommendations
- Enable only: trade_flow, cross_asset, orderbook_imbalance
- Disable: regime_switch, failed_breakout, scalp_v2, mtf_confluence, structural_break
- Keep scanner's liquidity-based TP/SL (sl_tp.py)
- Add conviction filter (min 0.5)
- Add regime-based direction filter (downtrend favors SHORT)

## Scanner vs Trader.py
- Trader.py (BB+mom6): 69.3% WR, 2.24 PF, 14.8% DD
- Scanner (best): 54.5% WR, 1.28 PF, 50.0% DD
- Trader.py significantly outperforms on all metrics

*Report: 2026-07-04 23:06 UTC+8*
