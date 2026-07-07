"""S02: Squeeze Breakout — volatility compression -> expansion trade.
Fixed: Own direction logic instead of relying on squeeze module direction."""
from .base import BaseStrategy, SignalResult

class SqueezeBreakoutStrategy(BaseStrategy):
    name = 'squeeze_breakout'
    strategy_type = 'event'
    description = 'Trade squeeze release with directional confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        squeeze = data.get('squeeze', {})
        confirmed = data.get('squeeze_confirmed', False)
        if not confirmed or squeeze.get('squeeze_status') != 'TRIGGERED':
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # OWN DIRECTION LOGIC — don't rely on squeeze module direction
        taker = data.get('raw_taker_ratio', 0.5)
        ema_200 = data.get('ema_200', 0)
        rsi = data.get('rsi', 50)
        vol_ratio = data.get('vol_ratio', 0)

        # Direction from taker flow + RSI + EMA200
        direction = None
        
        # Primary: taker flow (strong signal during squeeze release)
        if taker > 0.58:
            direction = 'LONG'
        elif taker < 0.42:
            direction = 'SHORT'
        else:
            return None  # No clear direction during squeeze
        
        # RSI confirmation
        if direction == 'LONG' and rsi > 70:
            return None  # Overbought
        if direction == 'SHORT' and rsi < 30:
            return None  # Oversold
        
        # EMA200 trend filter
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200 * 0.97:
                return None  # Too far below EMA200
            if direction == 'SHORT' and price > ema_200 * 1.03:
                return None  # Too far above EMA200

        # Conviction from squeeze quality + taker alignment
        quality = squeeze.get('squeeze_quality', 0.5)
        bars = squeeze.get('compression_bars', 0)
        score = squeeze.get('squeeze_score', 0.5)
        duration_bonus = min(bars / 50, 0.3)
        taker_strength = abs(taker - 0.5) * 2
        conviction = min(quality * 0.3 + score * 0.2 + duration_bonus + taker_strength * 0.2, 0.95)

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(2.0, 3.5, 6.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=1.0,
            reason=f"Squeeze {squeeze.get('squeeze_type')} -> {direction} "
                   f"(quality={quality:.2f}, bars={bars}, taker={taker:.3f})",
            bypass_gates=True,
            details={'squeeze_type': squeeze.get('squeeze_type'), 'quality': quality,
                     'compression_bars': bars, 'direction': direction, 'taker': taker},
        )

