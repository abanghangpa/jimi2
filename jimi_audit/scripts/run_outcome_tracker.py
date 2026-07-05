#!/usr/bin/env python3
"""
Outcome Tracker CLI — runs the outcome tracking pipeline.
Usage:
  python3 run_outcome_tracker.py              # Full pipeline
  python3 run_outcome_tracker.py --import     # Import only
  python3 run_outcome_tracker.py --evaluate   # Evaluate only
  python3 run_outcome_tracker.py --stats      # Show stats
"""
import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.outcome import OutcomeTracker, OutcomeDB


def main():
    db = OutcomeDB()
    tracker = OutcomeTracker(db)

    if '--stats' in sys.argv:
        # Show current stats
        total = db.get_signal_count()
        pending = db.get_signal_count('PENDING')
        evaluated = db.get_signal_count('EVALUATED')

        print(f"=== Outcome DB Stats ===")
        print(f"Total signals: {total}")
        print(f"Pending: {pending}")
        print(f"Evaluated: {evaluated}")
        print()

        # Show strategy performance
        perf = db.get_all_strategy_performance(days=30)
        if perf:
            print(f"=== Strategy Performance (30d) ===")
            print(f"{'Strategy':<25} {'Regime':<15} {'Dir':<8} {'WR%':<8} {'Total':<8} {'Avg PnL':<10}")
            print("-" * 80)
            for p in perf:
                print(f"{p['strategy']:<25} {p['regime']:<15} {p['direction']:<8} "
                      f"{p['win_rate']:<8.1f} {p['total_signals']:<8} {p['avg_pnl']:<10.4f}")
        else:
            print("No strategy performance data yet. Run the pipeline first.")

        return

    if '--import' in sys.argv:
        print("Importing signals...")
        imported_pending = tracker.import_from_pending_json()
        print(f"  Imported from pending_signals.json: {imported_pending}")
        imported_scans = tracker.import_from_scans(limit=500)
        print(f"  Imported from scan files: {imported_scans}")
        return

    if '--evaluate' in sys.argv:
        print("Evaluating pending signals...")
        result = tracker.evaluate_pending()
        print(f"  Evaluated: {result['evaluated']}")
        print(f"  Wins: {result['wins']}")
        print(f"  Losses: {result['losses']}")
        print(f"  Neutral: {result['neutral']}")
        print(f"  Errors: {result['errors']}")
        return

    # Full pipeline
    print("Running full outcome tracking pipeline...")
    result = tracker.run_full_pipeline()
    print(f"\n=== Results ===")
    print(f"Imported (pending): {result['imported_pending']}")
    print(f"Imported (scans): {result['imported_scans']}")
    print(f"Evaluated: {result['evaluated'].get('evaluated', 0)}")
    print(f"  Wins: {result['evaluated'].get('wins', 0)}")
    print(f"  Losses: {result['evaluated'].get('losses', 0)}")
    print(f"  Neutral: {result['evaluated'].get('neutral', 0)}")
    print(f"Performance updated: {result['performance_updated']} strategies")


if __name__ == '__main__':
    main()
