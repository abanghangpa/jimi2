"""S05: Kill Zone Scalp — session-timed entries during London/NY kill zones."""
from .base import BaseStrategy, SignalResult

class KillZoneStrategy(BaseStrategy):
    name = 'kill_zone'
    strategy_type = 'session'
    description = 'Trade during high-volume kill zones with directional confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        m21 = data.get('m21', {})
        if m21.get('status') != 'PASS':
            return None

        zone = m21.get('kill_zone', '')
        phase = m21.get('phase', '')
        if zone not in ('LONDON', 'NEW_YORK', 'LONDON_NY_OVERLAP'):
            return None

        direction = data.get('direction')
        if not direction:
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Need volume confirmation
        vol_ratio = data.get('vol_ratio', 0)
        taker = data.get('taker_ratio', 0.5)
        bar_expansion = data.get('bar_range_expansion', 1.0)

        # Score components
        zone_score = 0.3 if zone == 'LONDON_NY_OVERLAP' else 0.2
        vol_score = min(vol_ratio / 2.0, 0.3) if vol_ratio > 0 else 0
        taker_score = 0
        atr_pct = atr / price if price else 0
        taker_long_thresh = 0.5 + atr_pct * 5
        taker_short_thresh = 0.5 - atr_pct * 5
        if direction == 'LONG' and taker > taker_long_thresh:
            taker_score = 0.2
        elif direction == 'SHORT' and taker < taker_short_thresh:
            taker_score = 0.2
        expansion_score = min(bar_expansion / 2.0, 0.2)

        conviction = zone_score + vol_score + taker_score + expansion_score
        if conviction < 0.5:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=min(conviction, 0.85),
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Kill zone {zone} {phase} → {direction} "
                   f"(vol={vol_ratio:.2f}, taker={taker:.3f})",
            bypass_gates=False,
            details={'zone': zone, 'phase': phase, 'vol_ratio': vol_ratio,
                     'taker': taker, 'bar_expansion': bar_expansion},
        )
