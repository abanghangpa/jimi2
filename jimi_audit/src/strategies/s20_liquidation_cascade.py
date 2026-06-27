"""S20: Liquidation Cascade — trade when liquidations are heavily one-sided."""
from .base import BaseStrategy, SignalResult

class LiquidationCascadeStrategy(BaseStrategy):
    name = 'liquidation_cascade'
    strategy_type = 'event'
    description = 'Trade liquidation cascades when one side is getting heavily liquidated'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        liq_data = kwargs.get('liquidations', {})
        if not liq_data:
            return None

        long_liq_pct = liq_data.get('long_liq_pct', 0.5)
        short_liq_pct = liq_data.get('short_liq_pct', 0.5)
        total_vol = liq_data.get('total_liq_volume', 0)

        # Need significant liquidation volume and one-sided
        if total_vol < 100000:  # min $100k liquidations
            return None
        if abs(long_liq_pct - 0.5) < 0.2:  # need 70/30 split minimum
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Direction: fade the liquidation cascade
        # Longs being liquidated = price dropping → buy the dip
        # Shorts being liquidated = price rising → sell the rally
        if long_liq_pct > 0.7:
            direction = 'LONG'  # buy the long liquidation cascade
            extreme = long_liq_pct
        elif short_liq_pct > 0.7:
            direction = 'SHORT'
            extreme = short_liq_pct
        else:
            return None

        # Conviction from liquidation volume and one-sidedness
        vol_score = min(total_vol / 1000000, 0.3)  # $1M = max vol score
        extreme_score = min((extreme - 0.7) * 2, 0.4)  # 0.7=0, 0.9=max

        conviction = min(0.45 + vol_score + extreme_score, 0.90)
        if conviction < 0.55:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(2.0, 3.5, 5.0), sl_mult=1.5)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Liquidation cascade → {direction}: "
                   f"long_liq={long_liq_pct:.0%} short_liq={short_liq_pct:.0%} "
                   f"vol=${total_vol/1000:.0f}k",
            bypass_gates=True,
            details={'long_liq_pct': long_liq_pct, 'short_liq_pct': short_liq_pct,
                     'total_volume': total_vol},
        )
