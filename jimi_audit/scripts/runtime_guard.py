from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

SESSION_DIR = Path('/root/.openclaw/agents/main/sessions')
LOCK_MAX_AGE_SECONDS = 10 * 60
PKILL_PATTERNS = (
    r'master_tiered_proxy\.py',
)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _kill_leftovers() -> None:
    for pattern in PKILL_PATTERNS:
        _run(['pkill', '-f', pattern])


def _cleanup_stale_locks() -> None:
    if not SESSION_DIR.exists():
        return
    cutoff = time.time() - LOCK_MAX_AGE_SECONDS
    for lock in SESSION_DIR.glob('*.lock'):
        try:
            if lock.stat().st_mtime < cutoff:
                lock.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


def _install_signal_handlers() -> None:
    def _handler(signum, frame):
        _cleanup_stale_locks()
        raise SystemExit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except Exception:
            pass


def cleanup_before_run() -> None:
    _install_signal_handlers()
    _kill_leftovers()
    _cleanup_stale_locks()


if __name__ == '__main__':
    cleanup_before_run()
