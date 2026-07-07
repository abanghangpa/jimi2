"""S01: Failed Breakout (Enterprise Grade) — M20 detected failed breakout -> contrarian entry.
QUALITY FILTERS:
- Session: only trade 09:00-18:00 UTC (kill zone hours)
- Volume: skip high-volume bars (noise, not real failed breakouts)
- Conviction: only high-quality M20 signals (>= 0.7)
- EMA200: trend-aligned only
- Wider TP: 2.5x ATR (let winners run)
"""
from .base import BaseStrategy, SignalResult
from datetime import datetime, timezone

# Best hours from backtest analysis (UTC)
GOOD_HOURS = {9, 10, 11, 12, 14, 15, 16, 18}

class FailedBreakoutStrategy(BaseStrategy):
    name = 'failed_breakout'
    strategy_type = 'event'
    description = 'Enterprise-grade failed breakout: session + volume + conviction filtered'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        m20 = data.get('m20', {})
        if m20.get('status') != 'PASS':
            return None
        failure = m20.get('failure', {})
        if not failure.get('failed', False):
            return None

        direction = m20.get('contrarian_direction')
        if not direction:
            return None

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        ema_200 = data.get('ema_200', 0)
        if not price or not atr:
            return None

        # ── QUALITY FILTER 1: Session ──
        ts = data.get('timestamp', '')
        if ts:
            try:
                hour = int(ts[11:13])
                if hour not in GOOD_HOURS:
                    return None  # skip low-activity hours
            except (ValueError, IndexError):
                pass

        # ── QUALITY FILTER 2: Volume ──
        vol_ratio = data.get('vol_ratio', 1.0) or 1.0
        if vol_ratio > 1.0:
            return None  # skip high-volume bars (noise)

        # ── QUALITY FILTER 3: EMA200 trend ──
        if ema_200 and ema_200 > 0:
            if direction == 'LONG' and price < ema_200:
                return None  # don't buy below EMA200
            if direction == 'SHORT' and price > ema_200:
                return None  # don't short above EMA200

        # ── QUALITY FILTER 4: Near EMA200 (<1%) ──
        if ema_200 and ema_200 > 0:
            dist = abs(price - ema_200) / ema_200
            if dist > 0.01:
                return None  # too far from EMA200

        # ── CONVICTION ──
        reversal = m20.get('reversal_score', 0.5)
        quality = 1.0 - m20.get('breakout_quality', 0.5)
        bars_since = failure.get('bars_since', 99)
        freshness = max(0, 1.0 - bars_since / 100)
        conviction = (reversal * 0.4 + quality * 0.3 + freshness * 0.3)
        conviction = min(conviction, 0.95)

        # ── QUALITY FILTER 5: High conviction only ──
        if conviction < 0.7:
            return None  # low-quality signal

        # ── TP/SL: Wider TP to let winners run ──
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(2.5, 4.0, 6.0), sl_mult=1.0)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"M20 failed BO: {m20.get('breakout_direction')} -> {direction} "
                   f"(rev={reversal:.2f} qual={quality:.2f} bars={bars_since})",
            bypass_gates=True,
            details={'m20_score': m20.get('score'), 'bars_since': bars_since,
                     'reversal': reversal, 'quality': quality, 'vol_ratio': vol_ratio},
        )
