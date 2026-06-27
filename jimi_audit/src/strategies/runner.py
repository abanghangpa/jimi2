"""
Strategy Runner — executes all registered strategies and picks the best signal.
"""
from typing import List, Optional, Dict
from .base import BaseStrategy, SignalResult


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
                result = strat.check(data, df_15m=df_15m, idx=idx, **kwargs)
                if result is not None:
                    result.timestamp = data.get('timestamp', '')
                    signals.append(result)
            except Exception as e:
                # Don't let one strategy crash the whole runner
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
