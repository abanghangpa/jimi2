"""S03: Cascade Trade — ride macro cascade momentum (US Labor, EU Macro)."""
from .base import BaseStrategy, SignalResult

class CascadeStrategy(BaseStrategy):
    name = 'cascade'
    strategy_type = 'event'
    description = 'Trade macro cascade signals when US Labor or EU Macro cascades align'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        cascade = data.get('cascade', {})
        combined_signal = cascade.get('combined_signal', 'NONE')
        if combined_signal not in ('WITH', 'AGAINST'):
            return None

        direction = data.get('direction')
        if not direction:
            return None

        # Cascade WITH = momentum in trade direction, AGAINST = contrarian
        if combined_signal == 'AGAINST':
            direction = 'SHORT' if direction == 'LONG' else 'LONG'

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Conviction from cascade strength and active count
        strength = cascade.get('combined_score', 0)
        active = cascade.get('active_count', 0)
        total_weight = cascade.get('total_weight', 0)
        conviction = min(strength * 0.5 + (active / 5) * 0.3 + total_weight * 0.2, 0.90)

        if conviction < 0.45:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Cascade {combined_signal} → {direction} "
                   f"(strength={strength:.2f}, active={active})",
            bypass_gates=True,
            details={'cascade_signal': combined_signal, 'strength': strength,
                     'active_count': active},
        )
