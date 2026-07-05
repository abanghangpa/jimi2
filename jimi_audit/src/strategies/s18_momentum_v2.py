"""S18: Momentum v2 — improved momentum with taker flow and ignition detection."""
from .base import BaseStrategy, SignalResult

class MomentumV2Strategy(BaseStrategy):
    name = 'momentum_v2'
    strategy_type = 'flow'
    description = 'Improved momentum entry with taker flow confirmation and ignition detection'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        direction = data.get('direction')
        if not direction:
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Need multiple momentum confirmations
        ts = data.get('taker_summary', {})
        bar_expansion = data.get('bar_range_expansion', 1.0)
        vol_ratio = data.get('vol_ratio', 0)
        taker = data.get('taker_ratio', 0.5)

        # Momentum ignition: bar expansion + volume + taker
        ignition = bar_expansion > 0.010 and vol_ratio > 0.05

        # Taker flow alignment
        taker_aligned = False
        if direction == 'LONG' and taker > 0.40:
            taker_aligned = True
        elif direction == 'SHORT' and taker < 0.60:
            taker_aligned = True

        if not (ignition and taker_aligned):
            return None

        # Conviction from ignition strength
        ignition_score = min(bar_expansion / 0.05, 0.3)
        vol_score = min(vol_ratio / 0.3, 0.25)
        taker_score = min(abs(taker - 0.5) * 2, 0.25)
        regime_score = 0.15 if ts.get('regime') in ('TRENDING', 'STRONG') else 0.05

        conviction = ignition_score + vol_score + taker_score + regime_score
        if conviction < 0.20:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(2.0, 3.5, 5.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=min(conviction, 0.90),
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Momentum v2 → {direction}: ignition={bar_expansion:.1f}x "
                   f"vol={vol_ratio:.2f} taker={taker:.3f}",
            bypass_gates=True,
            details={'bar_expansion': bar_expansion, 'vol_ratio': vol_ratio,
                     'taker': taker, 'regime': ts.get('regime')},
        )
