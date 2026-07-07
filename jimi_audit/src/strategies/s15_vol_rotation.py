"""S15: Vol Rotation — volume regime rotation with directional bias.
Fixed: Own direction logic instead of pipeline dependency."""
from .base import BaseStrategy, SignalResult

class VolRotationStrategy(BaseStrategy):
    name = 'vol_rotation'
    strategy_type = 'regime'
    description = 'Trade volume regime rotations with directional confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        vol_ratio = data.get('vol_ratio', 0)
        taker = data.get('raw_taker_ratio', 0.5)
        ema_200 = data.get('ema_200', 0)
        rsi = data.get('rsi', 50)
        vwap_dist = data.get('vwap_dist', 0)

        # Need volume expansion
        if vol_ratio < 0.3:
            return None

        # OWN DIRECTION LOGIC — use taker + RSI + VWAP
        direction = None
        
        # Primary: taker flow
        if taker > 0.58:
            direction = 'LONG'
        elif taker < 0.42:
            direction = 'SHORT'
        else:
            return None
        
        # RSI filter
        if direction == 'LONG' and rsi > 70:
            return None
        if direction == 'SHORT' and rsi < 30:
            return None
        
        # VWAP confirmation (price above VWAP = bullish, below = bearish)
        vwap_confirm = False
        if direction == 'LONG' and vwap_dist > 0:
            vwap_confirm = True
        elif direction == 'SHORT' and vwap_dist < 0:
            vwap_confirm = True

        # EMA200 filter
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200 * 0.97:
                return None
            if direction == 'SHORT' and price > ema_200 * 1.03:
                return None

        # Conviction
        taker_strength = abs(taker - 0.5) * 2
        conviction = min(0.4 + taker_strength * 0.3 + (0.1 if vwap_confirm else 0), 0.80)

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Vol rotation -> {direction}: vol={vol_ratio:.2f} "
                   f"taker={taker:.3f} vwap_confirm={vwap_confirm}",
            bypass_gates=False,
            details={'vol_ratio': vol_ratio, 'taker': taker, 'vwap_dist': vwap_dist, 'vwap_confirm': vwap_confirm},
        )

