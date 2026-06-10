# Adaptive Timeout Rule for M4B Module
- **Trigger**: If the `M4B` (Intrabar CVD) module fails to complete (timeout or error) more than 2 consecutive times.
- **Action**: Automatically increase the timeout duration by 5 seconds for subsequent runs.
- **Reset**: If a run succeeds, reset the failure count and the timeout to the base configuration value.
- **Persistence**: This state (current timeout and failure count) must be stored in a local file (e.g., `.m4b_timeout_state.json`) to persist across separate scanner executions.
