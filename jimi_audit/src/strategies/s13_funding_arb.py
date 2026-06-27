"""S13: Funding Rate Arb — trade funding rate extremes."""
from .base import BaseStrategy, SignalResult

class FundingArbStrategy(BaseStrategy):
    name = 'funding_arb'
    strategy_type = 'flow'
    description = 'Trade funding rate extremes — negative funding = long, positive = short'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        deriv = data.get('derivatives', {})
        if not deriv:
            return None

        # Get funding-related data
        oi = deriv.get('oi', 0)
        oi_roc = deriv.get('oi_roc_1h', 0)
        ls_ratio = deriv.get('ls_ratio', 1.0)

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Extreme OI + declining = funding squeeze
        if abs(oi_roc) < 0.02:
            return None

        # Direction from OI flow
        if oi_roc < -0.03 and ls_ratio > 1.5:
            # Longs closing + high L/S = short squeeze potential
            direction = 'LONG'
        elif oi_roc > 0.03 and ls_ratio < 0.7:
            # Shorts closing + low L/S = long squeeze potential
            direction = 'SHORT'
        else:
            return None

        conviction = min(0.35 + abs(oi_roc) * 5, 0.75)

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.6,
            reason=f"Funding arb → {direction}: OI_roc={oi_roc:.4f} L/S={ls_ratio:.2f}",
            bypass_gates=False,
            details={'oi': oi, 'oi_roc_1h': oi_roc, 'ls_ratio': ls_ratio},
        )
