"""S01: Failed Breakout v2 — independent detection + quality grading.

v1 → v2 CHANGES:
1. Independent detection: doesn't need M20 module — detects failed breakouts from df_15m
2. EMA200 filter widened from 1% to 3% — more signals
3. Quality grading: how long the breakout held before failing (longer = more trapped traders)
4. Works in ranging AND trending regimes (with different filters)
"""
from .base import BaseStrategy, SignalResult
import numpy as np

GOOD_HOURS = {9, 10, 11, 12, 14, 15, 16, 18}


def _detect_failed_breakout(df_15m, idx, atr):
    """
    Detect failed breakout from price action alone.
    Returns dict with breakout info or None.

    A failed breakout is:
    1. Price breaks above a recent swing high (or below swing low)
    2. The breakout candle closes beyond the level
    3. The NEXT candle(s) reverse and close back inside the range
    4. The longer the breakout held, the more traders are trapped
    """
    if idx < 20:
        return None

    closes = df_15m['Close'].values.astype(float)
    highs = df_15m['High'].values.astype(float)
    lows = df_15m['Low'].values.astype(float)
    volumes = df_15m['Volume'].values.astype(float)

    current_close = closes[idx]
    current_high = highs[idx]
    current_low = lows[idx]

    # Find swing levels in recent history
    lookback = min(48, idx)  # 12 hours
    swing_high = float(np.max(highs[idx-lookback:idx]))
    swing_low = float(np.min(lows[idx-lookback:idx]))

    # Volume context
    vol_ma = np.mean(volumes[max(0, idx-20):idx+1])
    vol_ratio = volumes[idx] / max(vol_ma, 1)

    # ── CHECK FAILED BREAKOUT ABOVE ──
    # Did price break above swing_high in recent bars and then fail?
    for lookback_bars in range(1, min(8, idx)):  # check last 8 bars
        bar_idx = idx - lookback_bars
        bar_high = highs[bar_idx]
        bar_close = closes[bar_idx]
        bar_low = lows[bar_idx]

        # Did this bar break above swing_high?
        if bar_high > swing_high * 1.001:  # 0.1% above
            # Did it close below the level? (failed breakout candle)
            if bar_close < swing_high:
                # How many bars did the breakout hold before failing?
                bars_held = 0
                for j in range(bar_idx, idx + 1):
                    if highs[j] > swing_high:
                        bars_held += 1
                    else:
                        break

                # Quality: longer hold = more trapped traders = stronger signal
                quality = min(bars_held / 5, 1.0)  # max quality at 5 bars

                # Check if current bar confirms the failure (price below level)
                if current_close < swing_high:
                    return {
                        "direction": "SHORT",
                        "level": swing_high,
                        "level_type": "swing_high",
                        "bars_held": bars_held,
                        "quality": quality,
                        "breakout_bar": bar_idx,
                        "vol_ratio": vol_ratio,
                    }

    # ── CHECK FAILED BREAKOUT BELOW ──
    for lookback_bars in range(1, min(8, idx)):
        bar_idx = idx - lookback_bars
        bar_low = lows[bar_idx]
        bar_close = closes[bar_idx]
        bar_high = highs[bar_idx]

        if bar_low < swing_low * 0.999:  # 0.1% below
            if bar_close > swing_low:
                bars_held = 0
                for j in range(bar_idx, idx + 1):
                    if lows[j] < swing_low:
                        bars_held += 1
                    else:
                        break

                quality = min(bars_held / 5, 1.0)

                if current_close > swing_low:
                    return {
                        "direction": "LONG",
                        "level": swing_low,
                        "level_type": "swing_low",
                        "bars_held": bars_held,
                        "quality": quality,
                        "breakout_bar": bar_idx,
                        "vol_ratio": vol_ratio,
                    }

    return None


class FailedBreakoutStrategy(BaseStrategy):
    name = 'failed_breakout'
    strategy_type = 'event'
    description = 'v2: independent detection + quality grading + wider EMA filter'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None

        # ── SESSION FILTER ──
        ts = data.get('timestamp', '')
        if ts:
            try:
                hour = int(ts[11:13])
                if hour not in GOOD_HOURS:
                    return None
            except (ValueError, IndexError):
                pass

        # ── INDEPENDENT DETECTION (new) ──
        # Try independent detection first
        fb = _detect_failed_breakout(df_15m, idx, atr)

        # Fallback: M20 module (if available)
        if not fb:
            m20 = data.get('m20', {})
            if m20.get('status') == 'PASS':
                failure = m20.get('failure', {})
                if failure.get('failed', False):
                    direction = m20.get('contrarian_direction')
                    if direction:
                        fb = {
                            "direction": direction,
                            "level": m20.get('breakout_level', price),
                            "level_type": "m20_module",
                            "bars_held": failure.get('bars_since', 3),
                            "quality": 1.0 - m20.get('breakout_quality', 0.5),
                            "vol_ratio": data.get('vol_ratio', 1.0),
                        }

        if not fb:
            return None

        direction = fb["direction"]
        quality = fb["quality"]
        bars_held = fb["bars_held"]

        # ── QUALITY FILTER (new) ──
        # Need at least 1 bar held — instant reversals are noise
        if bars_held < 1:
            return None

        # ── EMA200 FILTER (widened) ──
        ema_200 = data.get('ema_200', 0)
        if ema_200 and ema_200 > 0:
            dist = (price - ema_200) / ema_200

            # Determine regime from recent price action
            closes = df_15m['Close'].values.astype(float)
            if idx >= 48:
                trend_change = (closes[idx] - closes[idx-48]) / closes[idx-48]
                if abs(trend_change) > 0.03:
                    ema_band = 0.05  # trending: very relaxed
                else:
                    ema_band = 0.03  # ranging: still wider than v1's 1%
            else:
                ema_band = 0.03

            if direction == 'LONG' and dist < -ema_band:
                return None
            if direction == 'SHORT' and dist > ema_band:
                return None

        # ── VOLUME FILTER ──
        vol_ratio = fb.get("vol_ratio", 1.0) or 1.0
        # In trending regimes, high volume breakouts are more likely to fail
        # In ranging, low volume breakouts are more likely to fail
        m9 = data.get('m9', {})
        vol_regime = m9.get('regime', 'UNKNOWN')
        if vol_regime in ('TRENDING', 'CRISIS'):
            # In trends, need high volume for failed breakout signal
            if vol_ratio < 1.2:
                return None
        else:
            # In ranging, prefer low volume (noise breakout)
            if vol_ratio > 2.0:
                return None  # too much volume — might be real breakout

        # ── CONVICTION ──
        base = 0.40

        # Quality bonus (longer hold = more trapped traders)
        quality_bonus = quality * 0.20

        # Bars held bonus
        bars_bonus = min(bars_held / 10, 0.15)

        # Level type bonus
        level_bonus = 0.10 if fb["level_type"] == "swing_high" or fb["level_type"] == "swing_low" else 0

        # Volume context
        vol_bonus = 0
        if vol_ratio < 1.0:
            vol_bonus = 0.10  # low volume breakout = more likely to fail

        conviction = min(base + quality_bonus + bars_bonus + level_bonus + vol_bonus, 0.90)

        # ── M20 MODULE BONUS ──
        if fb["level_type"] == "m20_module":
            m20 = data.get('m20', {})
            reversal = m20.get('reversal_score', 0.5)
            conviction = min(conviction + reversal * 0.10, 0.90)

        if conviction < 0.50:
            return None

        # ── TP/SL ──
        # Wider TP for quality breakouts (more trapped traders = bigger reversal)
        tp_mult = 2.5 if quality > 0.5 else 2.0
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(tp_mult, 4.0, 6.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Failed BO v2 {direction}: {fb['level_type']} ${fb['level']:.2f} "
                   f"held={bars_held}bars quality={quality:.2f}",
            bypass_gates=True,
            details={
                'level': fb['level'], 'level_type': fb['level_type'],
                'bars_held': bars_held, 'quality': quality,
                'vol_ratio': vol_ratio, 'vol_regime': vol_regime,
                'version': 'v2',
            },
        )
