"""S01: Failed Breakout — M20 detected failed breakout → contrarian entry."""
from .base import BaseStrategy, SignalResult

class FailedBreakoutStrategy(BaseStrategy):
    name = 'failed_breakout'
    strategy_type = 'event'
    description = 'Trade contrarian when M20 detects a failed breakout pattern'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        m20 = data.get('m20', {})
        if m20.get('status') != 'PASS':
            return None
        failure = m20.get('failure', {})
        if not failure.get('failed', False):
            return None

        direction = m20.get('contrarian_direction')
        if not direction:
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Conviction from reversal score and breakout quality
        reversal = m20.get('reversal_score', 0.5)
        quality = 1.0 - m20.get('breakout_quality', 0.5)  # low quality = more likely trap
        bars_since = failure.get('bars_since', 99)
        freshness = max(0, 1.0 - bars_since / 100)  # fresher = better
        conviction = (reversal * 0.4 + quality * 0.3 + freshness * 0.3)
        conviction = min(conviction, 0.95)

        # Wider stops for failed breakouts (they can retest the breakout level)
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(2.0, 3.5, 5.0), sl_mult=1.5)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,  # slightly smaller (wider stops)
            reason=f"M20 failed breakout: {m20.get('breakout_direction')} → {direction} "
                   f"(reversal={reversal:.2f}, quality={quality:.2f}, bars={bars_since})",
            bypass_gates=True,  # event-driven, skip normal gates
            details={'m20_score': m20.get('score'), 'level': m20.get('level'),
                     'bars_since': bars_since, 'reversal_score': reversal},
        )
