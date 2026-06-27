"""S10: Structural Break — M13 bias flip + M4b divergence confirmation."""
from .base import BaseStrategy, SignalResult

class StructuralBreakStrategy(BaseStrategy):
    name = 'structural_break'
    strategy_type = 'structure'
    description = 'Trade structural breaks when M13 bias flips with M4b divergence confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        m13 = data.get('m13', {})
        m4b = data.get('m4b', {})

        m13_bias = m13.get('bias', 'NEUTRAL')
        m13_score = m13.get('score', 0)
        m4b_div = m4b.get('divergence', 'NONE')
        m4b_score = m4b.get('score', 0)

        if m13_bias == 'NEUTRAL' or m4b_div == 'NONE':
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Direction from M13 bias
        direction = 'LONG' if m13_bias == 'BULLISH' else 'SHORT'

        # M4b divergence should confirm
        if (direction == 'LONG' and m4b_div == 'BULLISH') or \
           (direction == 'SHORT' and m4b_div == 'BEARISH'):
            div_bonus = 0.2
        else:
            div_bonus = 0

        conviction = min(m13_score * 0.4 + m4b_score * 0.3 + div_bonus + 0.1, 0.85)
        if conviction < 0.5:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Structural break: M13={m13_bias} M4b={m4b_div} → {direction}",
            bypass_gates=False,
            details={'m13_bias': m13_bias, 'm13_score': m13_score,
                     'm4b_divergence': m4b_div, 'm4b_score': m4b_score},
        )
