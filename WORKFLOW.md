# JIMI Framework - Workflow Loop

This document defines the core operational loop of the autonomous market analysis system.

## 🔄 The Execution Pipeline

1. **Watchdog Activation**
   - The `jimi_watchdog.py` script wakes up.
   - Triggered by:
     - `cron` (Baseline Pulse: every 15 minutes).
     - Internal Adaptive Timer (Live Mode: every 60 seconds when price is in the Decision Zone $1680 - $1695).

2. **Scanner Orchestration**
   - Watchdog executes `scripts/scanner.py` (via `run_full_scan()`).
   - The Scanner performs the full data pipeline:
     - Fetches 15m data $\rightarrow$ Loads Daily History $\rightarrow$ Computes Indicators.
     - Applies the **Dual-Gear Logic** (Gear 1: The Snap / Gear 2: The Leak).
     - Generates the **MSSP Analysis Report**.

3. **Result Evaluation**
   - The Watchdog receives the structured MSSP report.
   - It checks for significant state changes (e.g., price entering/leaving Decision Zone, signal flip).
   - The scan results are mirrored to `/root/.openclaw/workspace/latest_scan.json` for external visibility.

4. **Delivery**
   - The Watchdog delivers the output to WhatsApp.
   - **Reporting Frequency**: A full MSSP report is delivered every 15 minutes regardless of signal status.
   - **Trigger Alerts**: Specific high-conviction signals (The Snap) trigger immediate priority alerts.

## 🛠️ Critical Dependencies
- **Data Pipeline**: `latest_scan.json` must be updated by the scanner for the Watchdog to be effective.
- **Network Stability**: FRED API calls are spoofed/cached to prevent initialization hangs.
- **Schedules**: Managed via system `crontab`.
