"""
Integration module — bridges outcome systems with the scanner.

Provides drop-in functions that the scanner can call to:
1. Filter strategies by regime (router)
2. Apply adaptive weights (gating)
3. Record signals for tracking (pipeline)
"""
import os
import json
from typing import Dict, List, Optional, Tuple
from .db import OutcomeDB
from .adaptive_gating import AdaptiveGatingEngine
from .regime_router import RegimeStrategyRouter
from .health_monitor import StrategyHealthMonitor

# Singleton instances
_db = None
_gating = None
_router = None
_monitor = None


def _get_db():
    global _db
    if _db is None:
        _db = OutcomeDB()
    return _db


def _get_gating():
    global _gating
    if _gating is None:
        _gating = AdaptiveGatingEngine(_get_db())
    return _gating


def _get_router():
    global _router
    if _router is None:
        _router = RegimeStrategyRouter()
    return _router


def _get_monitor():
    global _monitor
    if _monitor is None:
        _monitor = StrategyHealthMonitor(_get_db())
    return _monitor


def classify_regime(trend_dir: str, swing_bias: str) -> str:
    """Classify market regime from trend and swing data."""
    if 'STRONG_DOWN' in trend_dir:
        return 'STRONG_DOWN'
    elif 'DOWN' in trend_dir:
        return 'DOWN'
    elif 'STRONG_UP' in trend_dir:
        return 'STRONG_UP'
    elif 'UP' in trend_dir:
        return 'UP'
    else:
        return 'RANGING'


def filter_strategies_by_regime(strategy_signals: List[Dict],
                                 regime: str) -> Tuple[List[Dict], List[Dict]]:
    """
    Filter strategy signals based on regime compatibility.
    
    Returns: (allowed_signals, blocked_signals)
    """
    router = _get_router()
    result = router.filter_signals(strategy_signals, regime)
    return result['allowed'], result['blocked']


def apply_adaptive_weights(strategy_signals: List[Dict],
                           regime: str) -> Dict:
    """
    Apply adaptive weights to strategy signals based on outcome data.
    
    Returns:
        {
            'adjusted_signals': [...],
            'vetoed': [...],
            'boosted': [...],
            'reduced': [...],
        }
    """
    gating = _get_gating()
    return gating.apply_to_ensemble(strategy_signals, regime)


def record_signal_for_tracking(signal_data: Dict, regime: str):
    """Record a signal for outcome tracking."""
    db = _get_db()

    ts = signal_data.get('timestamp', '')
    source = signal_data.get('source', 'main_pipeline')
    direction = signal_data.get('direction', '')

    if not ts or not direction:
        return

    signal_id = f"{ts}_{source}_{direction}"

    db.insert_signal({
        'signal_id': signal_id,
        'timestamp': ts,
        'price': signal_data.get('price', 0),
        'direction': direction,
        'source': source,
        'regime': regime,
        'swing_bias': signal_data.get('swing_bias'),
        'trend_dir': signal_data.get('trend_dir'),
        'ics': signal_data.get('ics'),
        'conviction': signal_data.get('conviction'),
        'entry': signal_data.get('entry'),
        'sl': signal_data.get('sl'),
        'tp1': signal_data.get('tp1'),
        'tp2': signal_data.get('tp2'),
        'tp3': signal_data.get('tp3'),
        'sl_pct': signal_data.get('sl_pct'),
        'tp1_pct': signal_data.get('tp1_pct'),
        'hold_window_hours': signal_data.get('hold_window_hours', 2),
    })


def get_strategy_health_alert() -> Optional[str]:
    """Get critical health alerts for WhatsApp notification."""
    monitor = _get_monitor()
    return monitor.generate_alert_message()


def get_regime_veto_report(regime: str) -> str:
    """Get a report of vetoed strategies for a regime."""
    router = _get_router()
    blocked = router.get_blocked_strategies(regime)

    if not blocked:
        return f"No strategies vetoed for {regime} regime."

    lines = [f"Strategies vetoed in {regime}:"]
    for s in blocked:
        lines.append(f"  ❌ {s}")
    return "\n".join(lines)


# Signal ranker singleton
_ranker = None

def _get_ranker():
    global _ranker
    if _ranker is None:
        from .signal_ranker import SignalRanker
        _ranker = SignalRanker(_get_db())
    return _ranker


def rank_strategy_signals(strategy_signals: List[Dict], regime: str) -> Dict:
    """
    Rank strategy signals by expected WR.
    
    Returns:
        {
            'ranked': [...],
            'tier_a': [...],
            'tier_b': [...],
            'tier_c': [...],
            'rejected': [...],
            'best': {...},
        }
    """
    ranker = _get_ranker()
    return ranker.rank_signals(strategy_signals, regime)


def get_signal_tier(strategy: str, regime: str, direction: str) -> str:
    """Get the tier for a specific signal combo."""
    ranker = _get_ranker()
    result = ranker.score_signal(strategy, regime, direction)
    return result['tier']
