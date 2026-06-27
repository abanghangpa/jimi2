# VPS OpenClaw Configuration (72.62.73.46)

*Last updated: 2026-06-27 10:52 UTC*

## ⚠️ IMPORTANT: Do NOT "fix" the fallback chain

The fallback chain contains models that may appear dead (502, 404, no provider prefix). **This is intentional.**

- **free-proxy models (#1-15):** Routed through local proxy `unified_proxy.py` on port 8821. The proxy pulls keys from GitHub (`alistaitsacle/free-llm-api-keys`) which rotate. Keys may be dead now but could work later when rotated. The cron job "Rotate Free Keys" runs every 10 min.
- **No-provider models (#48-73):** These are resolved by OpenClaw's internal routing. Do not remove them.
- **`text-embedding-3-small` (#65):** May be used by internal tools.

**If you see errors on these models, that's expected. The fallback chain will skip them and move to the next working model. Do not clean or reorganize the chain.**

## Providers

| Provider | Base URL | Models | Key Status |
|----------|----------|--------|------------|
| openrouter | openrouter.ai/api/v1 | 1 (free) | ✅ Active key |
| free-proxy | 127.0.0.1:8821 (local proxy) | 19 | 🔄 Keys rotate (may be dead temporarily) |
| nvidia | integrate.api.nvidia.com | 38 | ✅ Active key, all verified free endpoints |
| google | generativelanguage.googleapis.com | 6 | ✅ Key 1 |
| google2 | generativelanguage.googleapis.com | 6 | ✅ Key 2 |
| google3 | generativelanguage.googleapis.com | 6 | ✅ Key 3 |

## Fallback Chain (73 models)

Primary: `openrouter/free`

The chain is ordered by reliability/cost:
1. **openrouter/free** — free tier, rate-limited
2. **free-proxy (#1-15)** — local proxy with rotating GitHub keys
3. **nvidia (#16-29)** — verified free endpoints, 38 models available
4. **google (#30-35)** — Key 1
5. **google2 (#36-41)** — Key 2
6. **google3 (#42-47)** — Key 3
7. **Misc (#48-73)** — additional models via internal routing

## Proxy (Port 8821)

Local proxy `unified_proxy.py` with 5 tiers:
- Tier 3: Free keys from GitHub (auto-rotated by cron)
- Tier 2: OpenRouter
- Tier 1: Google Key 1
- Tier 1b: Google Key 2
- Tier 0: NVIDIA

If proxy returns 502, that's normal — the fallback chain will skip to the next provider.

## Cron Jobs

| Job | Model | Schedule | Notes |
|-----|-------|----------|-------|
| Jimi Scanner Report | openrouter/free | */15 * * * * | Quick market snapshot |
| JIMI Deep Analysis | nvidia/nemotron-3-super-120b-a12b | 0 8 * * * UTC | Python-first analysis, 1M context |
| Liquidity Collector | (default) | 5 * * * * | |
| Liquidity Reporter | (default) | 10 * * * * | |
| Rotate Free Keys | (default) | */10 * * * * | Pulls fresh keys from GitHub |

## Git Commits (this session)

```
ca94730d Update nvidia provider: 38 working free endpoints only
57b56868 Update NVIDIA API key
85e95e7b Update keys: OpenRouter + Google 1 + Google 2
0a68dcb8 Add google2 and google3 providers
f5534830 Clean fallback chain
30811aa7 Remove xiaomi and mistral providers
```

## Strategies (22 total)

| # | Strategy | Type | Status |
|---|----------|------|--------|
| s01 | failed_breakout | event | Active |
| s02 | squeeze_breakout | event | Active |
| s03 | cascade | event | Active |
| s04 | positioning_fade | structure | Active |
| s05 | kill_zone | session | **Needs upgrade** |
| s06 | liquidity_grab | structure | **Needs upgrade** |
| s07 | taker_flow | flow | **Needs upgrade** |
| s08 | regime_switch | regime | Active |
| s09 | power_of_3 | structure | Active |
| s10 | structural_break | structure | Active |
| s11 | cross_asset | flow | **Needs SHORT direction** |
| s12 | macro_surprise | event | Active |
| s13 | funding_arb | flow | Active |
| s14 | whale_watch | flow | Active |
| s15 | vol_rotation | regime | Active |
| s16 | mtf_confluence | structure | Active |
| s17 | scalp_v2 | session | Active |
| s18 | momentum_v2 | flow | Active |
| s19 | orderbook_imbalance | flow | Active |
| s20 | liquidation_cascade | event | Active |
| s21 | trade_flow | flow | Active |
| s22 | judas_sweep | event | ✅ v2 (validated 80.2% win) |

See `jimi_audit/STRATEGY_ROADMAP.md` for upgrade plan.
Signal logging active — all 22 strategies log to `data/strategy_signals.jsonl`.
