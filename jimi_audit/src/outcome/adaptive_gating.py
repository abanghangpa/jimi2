"""
Adaptive Strategy Gating — dynamically adjusts strategy weights and vetoes
based on real outcome data.

Enterprise-grade: data-driven, no hardcoded thresholds for specific strategies.
"""
import hashlib
import json
from typing import Dict, List, Optional, Tuple
from .db import OutcomeDB

# Gating thresholds
MIN_SAMPLES_FOR_VETO = 15      # Need at least 15 signals to veto
MIN_SAMPLES_FOR_WEIGHT = 10    # Need at least 10 to adjust weight
VETO_WR_THRESHOLD = 35.0       # WR below 35% → hard veto
WEIGHT_DOWN_THRESHOLD = 45.0   # WR below 45% → reduce weight
WEIGHT_UP_THRESHOLD = 60.0     # WR above 60% → boost weight
STRONG_UP_THRESHOLD = 70.0     # WR above 70% → strong boost


class AdaptiveGatingEngine:
    """
    Regime-adaptive strategy gating engine.
    
    Reads outcome data from SQLite and computes dynamic weights/vetoes
    for each (strategy, regime, direction) combination.
    """

    def __init__(self, db: OutcomeDB = None, static_weights: Dict = None):
        self.db = db or OutcomeDB()
        self.static_weights = static_weights or {}
        self._perf_cache = {}
        self._cache_ts = None

    def _refresh_cache(self, days: int = 30):
        """Refresh performance cache from database."""
        perf = self.db.get_all_strategy_performance(days=days)
        self._perf_cache = {}
        for p in perf:
            key = (p['strategy'], p['regime'], p['direction'])
            self._perf_cache[key] = p

    def get_dynamic_weight(self, strategy: str, regime: str,
                           direction: str, days: int = 30) -> Tuple[float, str, Dict]:
        """
        Get dynamic weight for a strategy in a given regime/direction.
        
        Returns:
            (weight_multiplier, action, details)
            weight_multiplier: 0.0 to 2.0
            action: 'ALLOW', 'VETO', 'BOOST', 'REDUCE'
            details: dict with reasoning
        """
        self._refresh_cache(days)
        key = (strategy, regime, direction)
        perf = self._perf_cache.get(key)

        static_w = self.static_weights.get(strategy, 1.0)

        if not perf or perf['total_signals'] < MIN_SAMPLES_FOR_WEIGHT:
            return static_w, 'ALLOW', {
                'reason': 'insufficient_data',
                'total': perf['total_signals'] if perf else 0,
                'min_required': MIN_SAMPLES_FOR_WEIGHT,
            }

        total = perf['total_signals']
        wr = perf['win_rate']
        avg_pnl = perf['avg_pnl']

        # Hard veto
        if total >= MIN_SAMPLES_FOR_VETO and wr < VETO_WR_THRESHOLD:
            return 0.0, 'VETO', {
                'reason': 'low_win_rate',
                'win_rate': wr,
                'total': total,
                'threshold': VETO_WR_THRESHOLD,
            }

        # Weight adjustments
        if wr >= STRONG_UP_THRESHOLD:
            multiplier = 2.0
            action = 'BOOST'
        elif wr >= WEIGHT_UP_THRESHOLD:
            multiplier = 1.5
            action = 'BOOST'
        elif wr < WEIGHT_DOWN_THRESHOLD:
            multiplier = 0.3
            action = 'REDUCE'
        else:
            multiplier = 1.0
            action = 'ALLOW'

        return static_w * multiplier, action, {
            'reason': 'adaptive',
            'win_rate': wr,
            'total': total,
            'avg_pnl': avg_pnl,
            'multiplier': multiplier,
            'static_weight': static_w,
        }

    def get_vetoed_strategies(self, regime: str, direction: str,
                               days: int = 30) -> List[Dict]:
        """Get all strategies that should be vetoed for a regime/direction."""
        self._refresh_cache(days)
        vetoed = []

        for key, perf in self._perf_cache.items():
            s_strategy, s_regime, s_direction = key
            if s_regime == regime and s_direction == direction:
                if perf['total_signals'] >= MIN_SAMPLES_FOR_VETO and perf['win_rate'] < VETO_WR_THRESHOLD:
                    vetoed.append({
                        'strategy': s_strategy,
                        'regime': s_regime,
                        'direction': s_direction,
                        'win_rate': perf['win_rate'],
                        'total': perf['total_signals'],
                        'avg_pnl': perf['avg_pnl'],
                    })

        return vetoed

    def apply_to_ensemble(self, strategy_signals: List[Dict],
                          regime: str, days: int = 30) -> Dict:
        """
        Apply adaptive gating to ensemble signals.
        
        Returns:
            {
                'adjusted_signals': [...],
                'vetoed': [...],
                'boosted': [...],
                'reduced': [...],
            }
        """
        adjusted = []
        vetoed = []
        boosted = []
        reduced = []

        for sig in strategy_signals:
            strategy = sig.get('strategy', '')
            direction = sig.get('direction', '')

            weight, action, details = self.get_dynamic_weight(
                strategy, regime, direction, days)

            if action == 'VETO':
                vetoed.append({
                    'strategy': strategy,
                    'direction': direction,
                    'reason': details,
                })
                continue

            # Adjust conviction by weight multiplier
            original_conviction = sig.get('conviction', 0)
            adjusted_conviction = min(original_conviction * (weight / 1.0), 1.0)

            adjusted_sig = dict(sig)
            adjusted_sig['conviction'] = round(adjusted_conviction, 4)
            adjusted_sig['adaptive_weight'] = round(weight, 4)
            adjusted_sig['adaptive_action'] = action
            adjusted_sig['adaptive_details'] = details
            adjusted.append(adjusted_sig)

            if action == 'BOOST':
                boosted.append({
                    'strategy': strategy,
                    'direction': direction,
                    'multiplier': details.get('multiplier', 1.0),
                })
            elif action == 'REDUCE':
                reduced.append({
                    'strategy': strategy,
                    'direction': direction,
                    'multiplier': details.get('multiplier', 1.0),
                })

        return {
            'adjusted_signals': adjusted,
            'vetoed': vetoed,
            'boosted': boosted,
            'reduced': reduced,
        }

    def generate_report(self, days: int = 30) -> str:
        """Generate a human-readable gating report."""
        self._refresh_cache(days)

        lines = []
        lines.append("=" * 80)
        lines.append("  ADAPTIVE STRATEGY GATING REPORT")
        lines.append("  Period: %d days" % days)
        lines.append("=" * 80)
        lines.append("")

        # Group by regime
        regimes = {}
        for key, perf in self._perf_cache.items():
            strategy, regime, direction = key
            if regime not in regimes:
                regimes[regime] = []
            regimes[regime].append((strategy, direction, perf))

        for regime in sorted(regimes.keys()):
            entries = regimes[regime]
            lines.append(f"--- {regime} ---")
            lines.append(f"  {'Strategy':<25} {'Dir':<8} {'WR%':<8} {'Total':<8} {'Action':<10} {'Weight':<8}")
            lines.append("  " + "-" * 70)

            for strategy, direction, perf in sorted(entries, key=lambda x: x[2]['win_rate']):
                wr = perf['win_rate']
                total = perf['total_signals']
                weight, action, _ = self.get_dynamic_weight(strategy, regime, direction, days)

                status = '🟢' if action == 'BOOST' else '🔴' if action == 'VETO' else '🟡' if action == 'REDUCE' else '⚪'
                lines.append(f"  {status} {strategy:<23} {direction:<8} {wr:<8.1f} {total:<8} {action:<10} {weight:<8.2f}")

            lines.append("")

        return "\n".join(lines)
