"""S05: Kill Zone Scalp — session-timed entries during London/NY kill zones.
Fixed: Own direction logic instead of pipeline dependency."""
from .base import BaseStrategy, SignalResult

class KillZoneStrategy(BaseStrategy):
    name = 'kill_zone'
    strategy_type = 'session'
    description = 'Trade during high-volume kill zones with directional confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        m21 = data.get('m21', {})
        if m21.get('status') != 'PASS':
            return None

        zone = m21.get('kill_zone', '') or m21.get('zone', '')
        phase = m21.get('phase', '')
        if zone not in ('LONDON', 'NEW_YORK', 'LONDON_NY_OVERLAP', 'ASIA', 'LONDON_SESSION', 'NY_SESSION', 'OVERLAP', 'ASIAN', 'EUROPEAN', 'US', 'PREMIUM', 'DISCOUNT'):
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # OWN DIRECTION LOGIC — don't rely on pipeline
        taker = data.get('raw_taker_ratio', 0.5)
        ema_200 = data.get('ema_200', 0)
        rsi = data.get('rsi', 50)
        vol_ratio = data.get('vol_ratio', 0)

        # Need volume confirmation
        if vol_ratio < 0.5:
            return None

        # Direction from taker flow + RSI
        direction = None
        if taker > 0.55 and rsi < 65:
            direction = 'LONG'
        elif taker < 0.45 and rsi > 35:
            direction = 'SHORT'
        else:
            return None  # No clear direction

        # EMA200 trend filter
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200 * 0.97:
                return None
            if direction == 'SHORT' and price > ema_200 * 1.03:
                return None

        # Conviction from zone quality + volume
        zone_score = 0.3 if zone in ('LONDON_NY_OVERLAP', 'LONDON', 'NEW_YORK') else 0.2
        taker_strength = abs(taker - 0.5) * 2
        conviction = min(zone_score + taker_strength * 0.3 + min(vol_ratio / 3, 0.2), 0.85)

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Kill zone {zone} {phase} -> {direction} "
                   f"(vol={vol_ratio:.2f}, taker={taker:.3f})",
            bypass_gates=False,
            details={'zone': zone, 'phase': phase, 'vol_ratio': vol_ratio, 'taker': taker},
        )

