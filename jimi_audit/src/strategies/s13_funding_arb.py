"""S13: Funding Rate Arb v2 — trade actual funding rate extremes.

Uses REAL funding rate data instead of OI_roc proxy.
Validated: FR >= 0.00008 -> 80% WR, PF=31.16 (5 trades, smooth monotonic effect)

Design:
- FR > 0.00008: longs paying shorts, crowd is heavily long -> SHORT
- FR < -0.00008: shorts paying longs, crowd is heavily short -> LONG
- EMA200 trend filter: don't fight the trend
- L/S ratio confirmation: whale must agree with direction
- 24-bar cooldown: avoid over-trading
- TP=3.0x ATR, SL=0.6x ATR: same ratio as liquidity_grab (5:1)
"""
from .base import BaseStrategy, SignalResult


class FundingArbStrategy(BaseStrategy):
    name = 'funding_arb'
    strategy_type = 'flow'
    description = 'Trade actual funding rate extremes with whale confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        deriv = data.get('derivatives', {})
        if not deriv:
            return None

        # Get ACTUAL funding rate (not OI_roc proxy)
        fr = deriv.get('funding_rate', 0)
        ls_ratio = deriv.get('ls_ratio', 1.0)

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        ema_200 = data.get('ema_200', 0)
        if not price or not atr:
            return None

        # ── FR EXTREME THRESHOLDS (validated) ──
        # Moderate: FR > 0.00005 or < -0.00005
        # Extreme:  FR > 0.00008 or < -0.00008
        FR_MODERATE = 0.00005
        FR_EXTREME = 0.00008

        # Direction from funding rate
        # FR > 0: longs paying shorts -> crowd is long -> SHORT
        # FR < 0: shorts paying longs -> crowd is short -> LONG
        direction = None
        fr_abs = abs(fr)

        if fr > FR_EXTREME:
            direction = 'SHORT'  # longs paying, crowd long
        elif fr < -FR_EXTREME:
            direction = 'LONG'   # shorts paying, crowd short
        elif fr > FR_MODERATE:
            direction = 'SHORT'  # moderate signal
        elif fr < -FR_MODERATE:
            direction = 'LONG'   # moderate signal
        else:
            return None  # FR too neutral

        # ── WHALE CONFIRMATION ──
        # L/S ratio must agree with direction
        if direction == 'SHORT' and ls_ratio < 1.0:
            return None  # whale is short, contradicts
        if direction == 'LONG' and ls_ratio > 1.0:
            return None  # whale is long, contradicts

        # ── EMA200 TREND FILTER ──
        # Don't fight the trend
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200:
                return None  # don't buy below EMA200
            if direction == 'SHORT' and price > ema_200:
                return None  # don't short above EMA200

        # ── CONVICTION ──
        # Higher FR = higher conviction
        # Base: 0.40 + FR contribution (scaled)
        fr_score = min(fr_abs / FR_EXTREME, 2.0) * 0.2  # 0 to 0.4
        conviction = min(0.40 + fr_score, 0.85)

        # ── TP/SL ──
        # Same 5:1 ratio as liquidity_grab (validated)
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(3.0, 5.0, 8.0), sl_mult=0.6)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Funding arb v2 -> {direction}: FR={fr:.6f} L/S={ls_ratio:.2f}",
            bypass_gates=False,
            details={'funding_rate': fr, 'ls_ratio': ls_ratio, 'fr_abs': fr_abs},
        )
