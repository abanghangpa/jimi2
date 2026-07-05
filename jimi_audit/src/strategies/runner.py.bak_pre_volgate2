"""
Strategy Runner — executes all registered strategies and picks the best signal.
Logs all signals for outcome tracking.
"""
from typing import List, Optional, Dict
from .base import BaseStrategy, SignalResult
import json
import os
from datetime import datetime, timezone

SIGNAL_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')


def _log_signal(strategy_name: str, data: dict, result: Optional[SignalResult] = None):
    """Log signal to JSONL for outcome tracking."""
    try:
        os.makedirs(SIGNAL_LOG_DIR, exist_ok=True)
        log_path = os.path.join(SIGNAL_LOG_DIR, 'strategy_signals.jsonl')
        entry = {
            'timestamp': str(data.get('timestamp', datetime.now(timezone.utc))),
            'strategy': strategy_name,
            'price': data.get('price', 0),
            'direction': result.direction if result else None,
            'conviction': round(result.conviction, 4) if result else None,
            'entry': round(result.entry, 2) if result else None,
            'sl': round(result.sl, 2) if result else None,
            'tp1': round(result.tp1, 2) if result else None,
            'rr1': round(result.rr1, 2) if result else None,
            'fired': result is not None,
            'vol_ratio': data.get('vol_ratio', None),
            'ema_200': data.get('ema_200', None),
            'outcome': None,  # filled later by outcome tracker
        }
        with open(log_path, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')
    except Exception:
        pass


class StrategyRunner:
    """Run all strategies and select the best signal."""

    def __init__(self, config=None):
        self.cfg = config or {}
        self.strategies: List[BaseStrategy] = []

    def register(self, strategy: BaseStrategy):
        self.strategies.append(strategy)

    def run_all(self, data: dict, df_15m=None, idx=None, **kwargs) -> List[SignalResult]:
        """Run all registered strategies, return all signals sorted by conviction."""
        signals = []
        for strat in self.strategies:
            try:
                # Volume ratio gate — skip if vol_ratio below strategy threshold
                _vr = data.get('vol_ratio', 1.0) or 1.0
                if strat.min_vol_ratio > 0 and _vr < strat.min_vol_ratio:
                    _log_signal(strat.name, data, None)
                    continue
                result = strat.check(data, df_15m=df_15m, idx=idx, **kwargs)
                if result is not None:
                    result.timestamp = data.get('timestamp', '')
                    signals.append(result)
                # Log every strategy (fired or not)
                _log_signal(strat.name, data, result)
            except Exception as e:
                # Log the attempt even on error
                _log_signal(strat.name, data, None)
                pass
        # Sort by conviction descending
        signals.sort(key=lambda s: s.conviction, reverse=True)
        return signals

    def best_signal(self, data: dict, df_15m=None, idx=None, **kwargs) -> Optional[SignalResult]:
        """Run all strategies, return only the best signal."""
        signals = self.run_all(data, df_15m=df_15m, idx=idx, **kwargs)
        return signals[0] if signals else None

    def summary(self, data: dict, df_15m=None, idx=None, **kwargs) -> dict:
        """Run all strategies, return summary with all signals."""
        signals = self.run_all(data, df_15m=df_15m, idx=idx, **kwargs)
        return {
            'total_strategies': len(self.strategies),
            'signals_fired': len(signals),
            'best': signals[0].to_dict() if signals else None,
            'all_signals': [s.to_dict() for s in signals],
        }
