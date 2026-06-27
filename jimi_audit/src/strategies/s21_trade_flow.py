"""S21: Trade Flow Momentum — follow aggressive recent trade flow."""
from .base import BaseStrategy, SignalResult

class TradeFlowStrategy(BaseStrategy):
    name = 'trade_flow'
    strategy_type = 'flow'
    description = 'Follow aggressive trade flow when recent trades show strong directional pressure'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        trade_data = kwargs.get('trade_flow', {})
        if not trade_data:
            return None

        taker_ratio = trade_data.get('taker_ratio', 0.5)
        net_flow = trade_data.get('net_flow', 0)
        large_buys = trade_data.get('large_buy_count', 0)
        large_sells = trade_data.get('large_sell_count', 0)

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Need strong directional flow
        if taker_ratio > 0.60 and net_flow > 0:
            direction = 'LONG'
        elif taker_ratio < 0.40 and net_flow < 0:
            direction = 'SHORT'
        else:
            return None

        # Conviction from flow strength
        flow_strength = abs(taker_ratio - 0.5) * 2  # 0-1
        flow_score = min(flow_strength * 0.4, 0.35)

        # Large trade confirmation
        if direction == 'LONG' and large_buys > large_sells:
            large_bonus = min((large_buys - large_sells) * 0.05, 0.2)
        elif direction == 'SHORT' and large_sells > large_buys:
            large_bonus = min((large_sells - large_buys) * 0.05, 0.2)
        else:
            large_bonus = 0

        conviction = min(0.45 + flow_score + large_bonus, 0.90)
        if conviction < 0.55:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Trade flow → {direction}: taker={taker_ratio:.3f} "
                   f"net=${net_flow/1000:.0f}k large(B={large_buys}/S={large_sells})",
            bypass_gates=True,
            details={'taker_ratio': taker_ratio, 'net_flow': net_flow,
                     'large_buys': large_buys, 'large_sells': large_sells},
        )
