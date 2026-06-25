# JIMI Framework — Module Reference

*Last updated: 2026-06-25*

This document describes what each module in the JIMI trading system actually measures. Use this as a quick reference when tuning weights, debugging signals, or understanding the ICS (Integrated Conviction Score).

---

## Module Scores

### Technical Modules (M1–M9)

| Module | Description |
|--------|-------------|
| **m1** | MACD histogram direction **+** RSI divergence **+** momentum-shift acceleration |
| **m2** | EMA trend detection (short-term vs long-term crossovers) |
| **m3** | VWAP deviation and institutional fair-value anchoring |
| **m4** | CVD (Cumulative Volume Delta) — buying vs selling pressure |
| **m5** | Swing-high/low stop-liquidity magnets **+** HVN absorption zones **+** FVG reversion targets **+** order-block institutional-rejection levels **+** volume-profile skew/acceleration **+** cascade detection (up/down, with/against) |
| **m6** | Derivatives — OI-weighted basis, funding skew, L/S ratio, taker flow |
| **m7** | Market regime classification (Trending/Ranging/Volatile/Crisis) |
| **m8** | Funding rate analysis — open interest weighted, exchange-specific |
| **m9** | Volatility regime — ATR expansion/contraction, historical vs implied |

### Macro-Cross Modules (M10–M13)

| Module | Description |
|--------|-------------|
| **m10** | BTC-trend (EMA21 vs EMA55) **+** ETH/BTC relative strength (7-day ROC) **+** BTC momentum (7-day ROC with 14-day confirmation) |
| **m11** | Momentum oscillator — RSI, Stochastic, rate-of-change convergence |
| **m12** | Order book depth — bid/ask imbalance, wall detection, spread analysis |
| **m13** | Swing-high levels **+** swing-low levels **+** fair-value gaps (FVGs) **+** order blocks (OBs) |

### Microstructure Modules (M14–M21)

| Module | Description |
|--------|-------------|
| **m14** | Liquidity sweep detection — stop-hunt identification, sweep velocity |
| **m15** | Liquidity level mapping — resting stops, liquidation clusters |
| **m16** | Exchange activity — per-exchange OI changes, volume anomalies |
| **m17** | Resistance quality — how many times tested, volume at level, age |
| **m18** | Squeeze detection — Bollinger Band compression, Keltner squeeze |
| **m19** | Breakout confirmation — volume, follow-through, retest behavior |
| **m20** | Failed breakout detection — false break traps, reclaim speed |
| **m21** | Wyckoff phase (Accumulation/Markup/Distribution/Markdown) **+** zone (Premium/Discount/Equilibrium) **+** kill-zone time filters **+** spring/up-thrust detection |

### Macro Event Modules (M22–M65)

| Module | Event |
|--------|-------|
| **m22** | Inflation regime aggregator — PPI/CPI/Fed stance composite |
| **m23** | PPI session impact |
| **m24** | NBS PMI (China official) |
| **m25** | Caixin PMI (China private) |
| **m26** | EZ PMI |
| **m27** | ISM Manufacturing PMI |
| **m28** | ISM Services PMI |
| **m29** | JOLTS (Job Openings) |
| **m30** | China CPI/PPI |
| **m31** | UK CPI |
| **m32** | UK Wages |
| **m33** | US Retail Sales |
| **m34** | Housing Starts |
| **m35** | PBOC LPR (China rate) |
| **m36** | ADP Employment |
| **m37** | NFP (Non-Farm Payrolls) |
| **m38** | IFO (Germany business climate) |
| **m39** | UMich Consumer Sentiment |
| **m40** | Germany CPI |
| **m41** | EZ CPI |
| **m42** | EZ GDP |
| **m43** | US GDP |
| **m44** | Durable Goods Orders |
| **m45** | PCE (Personal Consumption Expenditures) |
| **m46** | Japan CPI |
| **m47** | BOJ Rate Decision |
| **m48** | ECB Rate Decision |
| **m49** | BOE Rate Decision |
| **m50** | CB Consumer Confidence |
| **m51** | UK GDP Monthly |
| **m52** | RBA Rate Decision |
| **m53** | Australia CPI |
| **m54** | China GDP |
| **m55** | Treasury Auction (bid-to-cover, tail) |
| **m56** | US CPI |
| **m57** | FOMC Decision |
| **m58** | Powell Press Conference |
| **m59** | FOMC Minutes |
| **m60** | US PPI |
| **m61** | US Jobless Claims |
| **m62** | US Unemployment Rate |
| **m65** | China Activity (IP, Retail, Fixed Asset) |

### Cross-Asset Modules (M66–M75)

| Module | Description |
|--------|-------------|
| **m66** | USD/JPY — correlation with ETH, risk-on/risk-off signal |
| **m67** | DXY (Dollar Index) — inverse correlation strength |
| **m68** | US Treasury Yields — 10Y/2Y spread, yield curve shape |
| **m69** | VIX (Volatility Index) — fear gauge, regime filter |
| **m70** | WTI Crude — inflation proxy, risk appetite |
| **m71** | Gold — safe haven demand, real rates proxy |
| **m72** | BTC Dominance — alt-rotation signal, risk appetite |
| **m73** | Stablecoin dominance — USDT/USDC supply ratio, capital flow |
| **m74** | USDT.T (Tether treasury) — mint/burn activity |
| **m75** | TOF (Token Open Interest Flow) — cross-exchange net flow |

---

## Scoring Pipeline

```
Phase 1: Indicator warm-up (populate all module inputs)
Phase 2: M9 regime classification
Phase 3: M13/M7 bias resolution
Phase 4: Direction resolver (M10 + M13 + M21)
Phase 5: Full module scoring (M1–M75)
Phase 6: Veto system + coherence filter + entry optimizer
Phase 7: ICS calculation (weighted average with vetoes)
```

## ICS (Integrated Conviction Score)

- Range: 0.0 – 1.0
- Signal threshold: ~0.65
- Components: technical (M1–M21) + macro (M22–M65) + cross-asset (M66–M75)
- Vetoes can force ICS to 0 regardless of individual scores

---

*When you modify any module, update this file to reflect the change.*
