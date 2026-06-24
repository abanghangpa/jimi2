# JIMI Framework - Workflow Loop

*Last updated: 2026-06-24*

This document defines the core operational loop of the autonomous market analysis system.

---

## 🔄 The Execution Pipeline

### 1. Trigger — OpenClaw Cron Jobs

All scheduling is managed by **OpenClaw cron** (not system crontab). Four jobs run the system:

| Job | Schedule | Type | What it does |
|-----|----------|------|-------------|
| **Jimi Scanner Report** | Every 15 min | agentTurn | Runs scanner → formats MSSP report → delivers to WhatsApp |
| **Liquidity Collector** | Every hour at :05 | command | Runs `liquidity_collector.py` → logs to `data/liquidity_collector.log` |
| **Liquidity Reporter** | Every hour at :10 | command | Runs `liquidity_reporter.py` → generates hourly liquidity report |
| **Rotate Free Keys** | Every hour at :10 (+5m stagger) | agentTurn | Runs `rotate_keys.py` → scrapes fresh API keys from GitHub |

Additionally, **system crontab** runs `rotate_keys_v2.py` every 30 minutes (key rotation backup, logs to `rotation.log`).

### 2. Scanner Orchestration

The **Jimi Scanner Report** cron job is the primary pipeline:

1. OpenClaw spawns an isolated agent session
2. Agent executes `scripts/scanner.py --json`
3. Scanner performs the full data pipeline:
   - Fetches 15m data → Loads Daily History → Computes Indicators
   - **Phase 0**: EMA, MACD, RSI, ATR, VWAP, Vol Ratio, Swing Bias, CVD
   - **Phase 1**: M9 vol regime classification (NEUTRAL / COMPRESSING / TRENDING / CHOP_MILD / CHOP_BULL / CHOP_BEAR / CRISIS)
   - **Phase 2**: M13 structural bias, M7 macro bias, target prep (magnets, gaps, S/R)
   - **Phase 3**: `resolve_direction()` → direction locked for Phase 4
   - **Phase 4**: Full module scoring (M21–M75) → ICS calculation
   - **Phase 5**: Veto, coherence, entry filters → SIGNAL or NO_SIGNAL
4. Agent formats the JSON output into the MSSP report template
5. Report delivered to WhatsApp via OpenClaw announce

### 3. Data Outputs

- `latest_scan.json` — current scan snapshot (consumed by other scripts)
- `scan_history.json` — rolling 96-entry history (24h of 15-min scans)
- `data/liquidity_collector.log` — hourly liquidity data collection log

### 4. Auxiliary Systems

- **Unified Proxy** (`localhost:8821`): Python proxy providing free LLM access via scraped API keys, with production fallback. Managed by `key-proxy.service` (systemd user service).
- **Key Rotation**: `rotate_keys.py` scrapes fresh keys from GitHub → writes `free_keys.json` → proxy auto-reloads.

---

## 🛠️ Critical Dependencies

| Dependency | Purpose | Failure impact |
|-----------|---------|---------------|
| `latest_scan.json` | Scanner output consumed by reporter/eval scripts | Downstream jobs get stale data |
| FRED API cache | Macro data (spoofed/cached to prevent hangs) | M23–M65 scores unavailable |
| `free_keys.json` | API keys for proxy tier | Proxy returns 403 |
| `key-proxy.service` | Unified proxy on :8821 | LLM fallback chain breaks |
| OpenClaw gateway | Cron scheduling + WhatsApp delivery | All automation stops |

---

## 📋 Legacy (Deprecated)

The following are no longer active but remain in the workspace:

- **`jimi_watchdog.py`** — Former trigger script (system crontab). Replaced by OpenClaw cron. Commented out in crontab since 2026-06-16. Last log: `jimi_watchdog.log`.
- **`last_alert_state.json`** — Former watchdog state file. Stale since 2026-06-16.

These can be removed in a future cleanup.

---

## 🔄 Session Context

The system runs as a single-user setup on VPS `72.62.73.46`. Primary interaction is via WhatsApp. The OpenClaw agent (`main`) handles:
- Cron job execution (isolated sessions)
- WhatsApp DM conversation (shared session: `agent:main:direct:+601112827947`)
- Control UI access at `http://72.62.73.46:18789/`
