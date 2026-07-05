"""S12: Macro Surprise — trade post-release macro surprises."""
from .base import BaseStrategy, SignalResult

class MacroSurpriseStrategy(BaseStrategy):
    name = 'macro_surprise'
    strategy_type = 'event'
    description = 'Trade macro data surprises (beat/miss) with cascade confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        indicators = data.get('macro_indicators', {})
        lifecycle = data.get('macro_lifecycle', {})
        cascade = data.get('cascade', {})

        if not indicators or not lifecycle:
            return None

        # Find recent surprises
        surprises = []
        for key, ind in indicators.items():
            if isinstance(ind, dict):
                surprise = ind.get('surprise', '')
                if surprise in ('BEAT', 'MISS', 'BIG_BEAT', 'BIG_MISS'):
                    surprises.append((key, surprise, ind))

        # Derive surprise from lifecycle phase if no explicit surprise
        if not surprises and lifecycle:
            phase = lifecycle.get('phase', '')
            release_type = lifecycle.get('release_type', '')
            if phase in ('RELEASE', 'IMMEDIATE', 'LONDON_DECISION') and release_type:
                surprises.append((release_type, 'BEAT', {'surprise': 'BEAT'}))
        if not surprises:
            return None

        # Check if within trade window (24h of release)
        hours_since = lifecycle.get('hours_since', 999)
        if hours_since > 48:
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        # Direction from surprise type and cascade
        cascade_signal = cascade.get('combined_signal', 'NONE')
        direction = data.get('direction')
        if not direction:
            return None

        # Score from surprise magnitude and cascade alignment
        surprise_score = 0
        for key, sup_type, ind in surprises:
            if sup_type in ('BIG_BEAT', 'BIG_MISS'):
                surprise_score += 0.3
            else:
                surprise_score += 0.15

        cascade_bonus = 0.2 if cascade_signal == 'WITH' else 0
        freshness_bonus = max(0, 0.2 - hours_since / 24 * 0.2)

        conviction = min(surprise_score + cascade_bonus + freshness_bonus, 0.85)
        if conviction < 0.25:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0)

        surprise_names = [f"{k}={s}" for k, s, _ in surprises[:3]]
        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Macro surprise → {direction}: {', '.join(surprise_names)} "
                   f"(cascade={cascade_signal}, {hours_since:.0f}h ago)",
            bypass_gates=True,
            details={'surprises': surprise_names, 'cascade': cascade_signal,
                     'hours_since': hours_since},
        )
