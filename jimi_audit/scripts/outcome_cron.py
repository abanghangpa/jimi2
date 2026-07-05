#!/usr/bin/env python3
"""
Outcome Pipeline Cron Job — runs periodically to:
1. Import new signals from scans
2. Evaluate pending outcomes
3. Update strategy performance stats
4. Check for health alerts

Designed to be called from OpenClaw cron or system cron.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.outcome import OutcomeTracker, OutcomeDB
from src.outcome.health_monitor import StrategyHealthMonitor


def main():
    db = OutcomeDB()
    tracker = OutcomeTracker(db)
    monitor = StrategyHealthMonitor(db)

    # Run pipeline
    result = tracker.run_full_pipeline()

    # Check for alerts
    alert_msg = monitor.generate_alert_message()

    # Output for cron delivery
    output = {
        'pipeline': result,
        'alert': alert_msg,
        'db_stats': {
            'total': db.get_signal_count(),
            'pending': db.get_signal_count('PENDING'),
            'evaluated': db.get_signal_count('EVALUATED'),
        },
    }

    print(json.dumps(output, indent=2, default=str))

    # Return alert for delivery
    if alert_msg:
        print("\n--- ALERT ---")
        print(alert_msg)


if __name__ == '__main__':
    main()
