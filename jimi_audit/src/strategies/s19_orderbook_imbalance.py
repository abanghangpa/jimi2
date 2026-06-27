"""S19: Order Book Imbalance — trade multi-exchange order book pressure."""
from .base import BaseStrategy, SignalResult

class OrderBookImbalanceStrategy(BaseStrategy):
    name = 'orderbook_imbalance'
    strategy_type = 'flow'
    description = 'Trade when order book shows strong buy/sell imbalance across exchanges'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        # Get order flow data from kwargs (fetched separately)
        ob_data = kwargs.get('order_flow', {})
        if not ob_data:
            return None

        imbalance = ob_data.get('avg_imbalance', 1.0)
        consensus = ob_data.get('consensus', 'NEUTRAL')
        bullish_ex = ob_data.get('bullish_exchanges', 0)
        bearish_ex = ob_data.get('bearish_exchanges', 0)

        # Need strong imbalance
        if consensus == 'NEUTRAL':
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Direction from order book
        if consensus == 'BULLISH':
            direction = 'LONG'
            extreme = imbalance - 1.0
        else:
            direction = 'SHORT'
            extreme = 1.0 - imbalance

        # Conviction from imbalance strength and exchange agreement
        imbalance_score = min(extreme * 2, 0.4)
        exchange_score = min(max(bullish_ex, bearish_ex) / 3, 0.3)

        # Check for walls
        exchanges = ob_data.get('exchanges', {})
        wall_bonus = 0
        for ex_name, ex_data in exchanges.items():
            if direction == 'LONG' and ex_data.get('bid_wall_count', 0) > 0:
                wall_bonus = 0.15
                break
            elif direction == 'SHORT' and ex_data.get('ask_wall_count', 0) > 0:
                wall_bonus = 0.15
                break

        conviction = min(0.40 + imbalance_score + exchange_score + wall_bonus, 0.90)
        if conviction < 0.55:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=1.0,
            reason=f"Order book {consensus} → {direction}: imbalance={imbalance:.3f} "
                   f"({bullish_ex}B/{bearish_ex}S exchanges)",
            bypass_gates=True,
            details={'imbalance': imbalance, 'consensus': consensus,
                     'bullish_ex': bullish_ex, 'bearish_ex': bearish_ex},
        )
