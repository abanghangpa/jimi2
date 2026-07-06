"""S13: Funding Rate Arb v3 — FR as confirmation + L/S direction.

LESSON LEARNED: FR > 0 is NORMAL in crypto (75% of time).
Using FR as primary signal fails because positive FR is not extreme.

NEW DESIGN:
- FR is a CONFIRMATION filter (like whale_watch), not the primary signal
- Direction comes from L/S ratio extreme + FR confirmation
- FR extreme: top/bottom 25% of recent FR values (adaptive)
- EMA200 trend filter
- TP=3.0x ATR, SL=0.6x ATR (5:1 ratio)

ARCHITECTURE:
- State: L/S ratio (crowd positioning)
- State: FR (cost of carry — confirms crowd conviction)
- Both must agree on direction
- At least one must be at extreme level
"""
from .base import BaseStrategy, SignalResult
import numpy as np


class FundingArbStrategy(BaseStrategy):
    name = 'funding_arb'
    strategy_type = 'flow'
    description = 'FR + L/S confirmation — both must agree on direction'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        deriv = data.get('derivatives', {})
        if not deriv:
            return None

        fr = deriv.get('funding_rate', 0)
        ls_ratio = deriv.get('ls_ratio', 1.0)

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        ema_200 = data.get('ema_200', 0)
        if not price or not atr:
            return None

        # ── DIRECTION FROM L/S RATIO ──
        # L/S > 2.0: crowd heavily long -> SHORT
        # L/S < 0.8: crowd heavily short -> LONG
        LS_LONG_THRESH = 0.8
        LS_SHORT_THRESH = 2.0
        LS_MODERATE_LONG = 1.0
        LS_MODERATE_SHORT = 1.5

        direction = None
        ls_extreme = False

        if ls_ratio > LS_SHORT_THRESH:
            direction = 'SHORT'
            ls_extreme = True
        elif ls_ratio < LS_LONG_THRESH:
            direction = 'LONG'
            ls_extreme = True
        elif ls_ratio > LS_MODERATE_SHORT:
            direction = 'SHORT'
        elif ls_ratio < LS_MODERATE_LONG:
            direction = 'LONG'
        else:
            return None  # L/S too neutral

        # ── FR CONFIRMATION ──
        # FR > 0: longs paying (confirms SHORT)
        # FR < 0: shorts paying (confirms LONG)
        fr_confirms = False
        fr_extreme = False

        if direction == 'SHORT':
            if fr > 0:
                fr_confirms = True
            if fr > 0.00005:
                fr_extreme = True
        elif direction == 'LONG':
            if fr < 0:
                fr_confirms = True
            if fr < -0.00005:
                fr_extreme = True

        # ── ENTRY RULE ──
        # At least one of (ls_extreme, fr_extreme) must be true
        # And fr must confirm direction (same sign)
        if not fr_confirms:
            return None  # FR contradicts direction

        if not ls_extreme and not fr_extreme:
            return None  # neither is extreme enough

        # ── EMA200 TREND FILTER ──
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200:
                return None
            if direction == 'SHORT' and price > ema_200:
                return None

        # ── CONVICTION ──
        base = 0.40
        if ls_extreme:
            base += 0.20
        if fr_extreme:
            base += 0.15
        conviction = min(base, 0.85)

        # ── TP/SL (5:1 ratio) ──
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(3.0, 5.0, 8.0), sl_mult=0.6)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Funding arb v3 -> {direction}: FR={fr:.6f} L/S={ls_ratio:.2f} extreme={ls_extreme or fr_extreme}",
            bypass_gates=False,
            details={'funding_rate': fr, 'ls_ratio': ls_ratio,
                     'ls_extreme': ls_extreme, 'fr_extreme': fr_extreme},
        )
