"""S06: Liquidity Grab — trade bounces at liquidity clusters and S/R levels."""
from .base import BaseStrategy, SignalResult

class LiquidityGrabStrategy(BaseStrategy):
    name = 'liquidity_grab'
    strategy_type = 'structure'
    description = 'Enter at liquidity clusters, bid/ask walls, and magnet levels'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        liq = data.get('liquidity_levels', {})
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or not liq:
            return None

        bid_walls = liq.get('bid_walls', [])
        ask_walls = liq.get('ask_walls', [])
        below = liq.get('below', [])
        above = liq.get('above', [])
        magnets = data.get('magnets', [])
        squeeze = data.get('squeeze_quality', 0.5)
        # Dynamic proximity: tighter in compression, wider in expansion
        proximity_mult = 0.5 + squeeze * 0.5  # range: 0.5-1.0 (wider for more signals)

        # Find nearest liquidity level
        nearest_below = min(below, key=lambda x: abs(x.get('price', 0) - price)) if below else None
        nearest_above = min(above, key=lambda x: abs(x.get('price', 0) - price)) if above else None

        if not nearest_below and not nearest_above:
            return None

        # Check if price is near a liquidity level (within 0.5 ATR)
        direction = None
        level_price = None
        level_type = ''

        if nearest_below:
            dist = price - nearest_below.get('price', price)
            pct_dist = dist / price * 100 if price else 0
            if 0 < dist < proximity_mult * atr or (0 < pct_dist < 1.0):
                direction = 'LONG'  # bounce off support
                level_price = nearest_below.get('price')
                level_type = nearest_below.get('type', 'support')

        if nearest_above:
            dist = nearest_above.get('price', price) - price
            if 0 < dist < proximity_mult * atr:
                if direction is None:
                    direction = 'SHORT'  # rejection at resistance
                    level_price = nearest_above.get('price')
                    level_type = nearest_above.get('type', 'resistance')

        if not direction:
            return None

        # Check for bid/ask wall confirmation
        wall_confirm = 0
        if direction == 'LONG' and bid_walls:
            wall_confirm = 0.15
        elif direction == 'SHORT' and ask_walls:
            wall_confirm = 0.15

        # Magnet bonus
        magnet_bonus = 0.1 if magnets else 0

        conviction = min(0.40 + wall_confirm + magnet_bonus, 0.80)

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Liquidity grab: {level_type} at ${level_price:.2f} → {direction}",
            bypass_gates=False,
            details={'level_price': level_price, 'level_type': level_type,
                     'bid_walls': len(bid_walls), 'ask_walls': len(ask_walls)},
        )
