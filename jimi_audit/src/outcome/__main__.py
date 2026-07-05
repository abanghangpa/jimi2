"""
JIMI Outcome Pipeline — CLI entry point.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.outcome import OutcomeTracker, OutcomeDB
from src.outcome.adaptive_gating import AdaptiveGatingEngine
from src.outcome.regime_router import RegimeStrategyRouter
from src.outcome.health_monitor import StrategyHealthMonitor


def cmd_pipeline():
    """Run the full outcome tracking pipeline."""
    db = OutcomeDB()
    tracker = OutcomeTracker(db)

    print("Running outcome tracking pipeline...")
    result = tracker.run_full_pipeline()

    print(f"\n=== Pipeline Results ===")
    print(f"Imported (pending): {result['imported_pending']}")
    print(f"Imported (scans): {result['imported_scans']}")
    print(f"Evaluated: {result['evaluated'].get('evaluated', 0)}")
    print(f"  Wins: {result['evaluated'].get('wins', 0)}")
    print(f"  Losses: {result['evaluated'].get('losses', 0)}")
    print(f"  Neutral: {result['evaluated'].get('neutral', 0)}")
    print(f"Performance updated: {result['performance_updated']} strategies")


def cmd_adaptive():
    """Show adaptive gating report."""
    db = OutcomeDB()
    engine = AdaptiveGatingEngine(db)
    print(engine.generate_report())


def cmd_router():
    """Show regime-strategy router matrix."""
    router = RegimeStrategyRouter()
    print(router.generate_report())


def cmd_health():
    """Show strategy health monitor report."""
    db = OutcomeDB()
    monitor = StrategyHealthMonitor(db)
    print(monitor.generate_report())


def cmd_alerts():
    """Show critical alerts only."""
    db = OutcomeDB()
    monitor = StrategyHealthMonitor(db)
    msg = monitor.generate_alert_message()
    if msg:
        print(msg)
    else:
        print("No critical alerts.")


def cmd_rank():
    """Show signal ranking report."""
    from src.outcome.signal_ranker import SignalRanker
    db = OutcomeDB()
    ranker = SignalRanker(db)
    print(ranker.generate_report())


def cmd_stats():
    """Show quick stats."""
    db = OutcomeDB()
    total = db.get_signal_count()
    pending = db.get_signal_count('PENDING')
    evaluated = db.get_signal_count('EVALUATED')

    print(f"=== Outcome DB ===")
    print(f"Total: {total} | Pending: {pending} | Evaluated: {evaluated}")

    perf = db.get_all_strategy_performance(days=30)
    if perf:
        print(f"\n=== Top Performers (30d) ===")
        top = sorted([p for p in perf if p['total_signals'] >= 5],
                     key=lambda x: x['win_rate'], reverse=True)[:10]
        for p in top:
            print(f"  {p['strategy']:<25} {p['regime']:<15} {p['direction']:<8} "
                  f"WR: {p['win_rate']:.1f}% (n={p['total_signals']})")

        print(f"\n=== Worst Performers (30d) ===")
        worst = sorted([p for p in perf if p['total_signals'] >= 5],
                       key=lambda x: x['win_rate'])[:5]
        for p in worst:
            print(f"  {p['strategy']:<25} {p['regime']:<15} {p['direction']:<8} "
                  f"WR: {p['win_rate']:.1f}% (n={p['total_signals']})")


COMMANDS = {
    'pipeline': cmd_pipeline,
    'adaptive': cmd_adaptive,
    'router': cmd_router,
    'health': cmd_health,
    'alerts': cmd_alerts,
    'rank': cmd_rank,
    'stats': cmd_stats,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print("Usage: python -m src.outcome <command>")
        print()
        print("Commands:")
        print("  pipeline  — Run full outcome tracking pipeline")
        print("  adaptive  — Show adaptive gating report")
        print("  router    — Show regime-strategy router matrix")
        print("  health    — Show strategy health monitor report")
        print("  alerts    — Show critical alerts only")
        print("  stats     — Show quick stats")
        print("  rank      — Show signal ranking by expected WR")
        return

    cmd = sys.argv[1]
    if cmd in COMMANDS:
        COMMANDS[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)


if __name__ == '__main__':
    main()
