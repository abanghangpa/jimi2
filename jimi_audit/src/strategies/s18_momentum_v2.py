"""S18: Momentum v2 — bar range expansion + volume surge + taker flow.
Fixed: Own direction logic instead of pipeline dependency."""
from .base import BaseStrategy, SignalResult

class MomentumV2Strategy(BaseStrategy):
    name = 'momentum_v2'
    strategy_type = 'momentum'
    description = 'Bar range expansion + volume surge + taker flow momentum'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        bar_expansion = data.get('bar_range_expansion', 0)
        vol_ratio = data.get('vol_ratio', 0)
        taker = data.get('raw_taker_ratio', 0.5)
        ema_200 = data.get('ema_200', 0)
        rsi = data.get('rsi', 50)

        # Need expansion + volume
        if bar_expansion < 0.015 or vol_ratio < 0.08:
            return None

        # OWN DIRECTION LOGIC — don't rely on pipeline
        # Use taker flow + RSI + EMA200 for direction
        direction = None
        
        # Taker flow: > 0.55 = buying pressure, < 0.45 = selling pressure
        if taker > 0.55:
            direction = 'LONG'
        elif taker < 0.45:
            direction = 'SHORT'
        else:
            return None  # No clear taker direction
        
        # RSI confirmation
        if direction == 'LONG' and rsi > 70:
            return None  # Overbought, don't chase
        if direction == 'SHORT' and rsi < 30:
            return None  # Oversold, don't chase
        
        # EMA200 trend filter
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200 * 0.98:
                return None  # Too far below EMA200 for LONG
            if direction == 'SHORT' and price > ema_200 * 1.02:
                return None  # Too far above EMA200 for SHORT

        # Conviction from expansion + taker alignment
        taker_strength = abs(taker - 0.5) * 2  # 0-1 scale
        conviction = min(0.5 + taker_strength * 0.3 + min(bar_expansion / 5, 0.2), 0.90)

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(2.0, 3.5, 5.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Momentum v2 -> {direction}: expansion={bar_expansion:.1f}x "
                   f"vol={vol_ratio:.2f} taker={taker:.3f}",
            bypass_gates=True,
            details={'bar_expansion': bar_expansion, 'vol_ratio': vol_ratio, 'taker': taker},
        )

