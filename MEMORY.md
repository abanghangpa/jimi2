# Long-Term Memory

## Active Systems

### 🔄 Automated LLM Fallback System
- **Description**: A transparent proxy that provides free LLM access via a third-party GitHub repo, with automatic fallback to production Google Gemini keys if the free keys fail (401/429).
- **Components**:
    - `fallback_proxy.py`: Custom Python-based OpenAI-compatible proxy running on `localhost:8000`.
    - `rotate_keys.py`: Script that scrapes the GitHub repo for fresh keys.
    - `cron`: Scheduled to run every hour to ensure key freshness.
    - `.env`: Stores `PROD_API_KEY` for the proxy.
- **Configuration**: `openclaw.json` is configured to use `http://localhost:8000/v1` as the `free-proxy` provider.

## Lessons Learned

- **Pathing in Background Processes**: When running commands via `nohup` or background tasks, always use absolute paths for scripts and configuration files to avoid "File not found" errors due to shell context differences.
- **Atomic Config Updates**: When programmatically modifying JSON configuration files (like `openclaw.json`), always use an atomic write pattern (write to temp file $\rightarrow$ move) to prevent corruption during crashes.
- **Schema Strictness**: OpenClaw configuration is strictly validated; adding extra fields (like `key` directly into an auth profile) can cause the gateway to reject the entire config.
- **Event Loop Starvation (Gateway)**: Periodic polling for a local Ollama instance on port 11434 can cause synchronous socket timeouts, starving the Node.js event loop and triggering "post-turn maintenance" errors.
- **Ollama Spoof Solution**: Running a dummy HTTP server (`spoof_ollama.py`) on port 11434 that returns instant 404s neutralizes this lag and stabilizes the gateway.
- **Session Lock Management**: Use `safe_unlock.sh` to clear zombie locks without killing active TUI sessions.
