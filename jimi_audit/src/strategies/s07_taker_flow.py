"""S07: Taker Flow Momentum v3 — follow aggressive taker flow.

v2 → v3 CHANGES:
1. Fallback to computing taker flow from df_15m if kwargs['taker_summary'] missing
2. Regime-aware EMA200 filter: tight (1.5%) in ranging, relaxed (3%) in trends
3. Freshness check: z-score must have crossed threshold recently (not stale)
"""
from .base import BaseStrategy, SignalResult
import numpy as np

GOOD_HOURS = {0, 1, 2, 7, 8, 9, 10, 12, 13, 15, 16, 21}
BAD_HOURS = {4, 5, 6, 19, 20, 22, 23}


class TakerFlowStrategy(BaseStrategy):
    name = 'taker_flow'
    strategy_type = 'flow'
    description = 'v3: df_15m fallback + regime-aware EMA + freshness check'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        ema_200 = data.get('ema_200', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None
        if idx < 60:
            return None

        # ── SESSION FILTER ──
        ts_str = data.get('timestamp', '')
        if ts_str:
            try:
                hour = int(ts_str[11:13])
                if hour in BAD_HOURS:
                    return None
            except (ValueError, IndexError):
                pass

        # ── GET TAKER DATA ──
        # Primary: from kwargs (pipeline)
        ts = data.get('taker_summary', {})
        current_taker = ts.get('momentum', None) if ts else None

        # Fallback: compute from df_15m (new)
        taker_base = df_15m['Taker buy base asset volume'].values.astype(float)
        volumes = df_15m['Volume'].values.astype(float)
        taker_ratios = taker_base / np.maximum(volumes, 1)

        if current_taker is None:
            # Compute current taker ratio from df_15m
            current_taker = taker_ratios[idx]

        # ── COMPUTE Z-SCORE ──
        window = taker_ratios[max(0, idx-60):idx+1]
        if len(window) < 20:
            return None

        taker_mean = np.mean(window)
        taker_std = np.std(window)
        if taker_std < 0.01:
            return None

        taker_zscore = (current_taker - taker_mean) / taker_std

        # ── FRESHNESS CHECK (new) ──
        # Z-score must have crossed threshold recently, not sitting above it
        # Check if z-score was below threshold within last 5 bars
        threshold = 0.8
        fresh = False
        for lookback in range(1, min(6, idx)):
            prev_taker = taker_ratios[idx - lookback]
            prev_z = (prev_taker - taker_mean) / taker_std
            if abs(prev_z) < threshold:
                fresh = True  # crossed threshold recently
                break

        # If z-score has been above threshold for 5+ bars, it's stale
        if not fresh:
            return None

        # ── FLOW ACCELERATION ──
        if idx >= 5:
            prev_window = taker_ratios[max(0, idx-60):idx-4]
            if len(prev_window) >= 20:
                prev_zscore = (taker_ratios[idx-5] - np.mean(prev_window)) / max(np.std(prev_window), 0.01)
                acceleration = taker_zscore - prev_zscore
            else:
                acceleration = 0
        else:
            acceleration = 0

        # ── DIRECTION ──
        if taker_zscore > threshold:
            direction = 'LONG'
        elif taker_zscore < -threshold:
            direction = 'SHORT'
        else:
            return None

        # ── REGIME-AWARE EMA200 FILTER (new) ──
        if ema_200 and ema_200 > 0:
            dist = (price - ema_200) / ema_200

            # Determine regime from recent price action
            closes = df_15m['Close'].values.astype(float)
            if idx >= 48:
                # 12-hour trend: compare current price to 48 bars ago
                trend_change = (closes[idx] - closes[idx-48]) / closes[idx-48]
                if abs(trend_change) > 0.03:
                    # Trending: relax EMA filter to 3%
                    ema_band = 0.03
                else:
                    # Ranging: tight EMA filter at 1.5%
                    ema_band = 0.015
            else:
                ema_band = 0.015

            if direction == 'LONG' and dist < -ema_band:
                return None
            if direction == 'SHORT' and dist > ema_band:
                return None

        # ── CONVICTION ──
        base = 0.40

        # Z-score strength
        z_strength = min(abs(taker_zscore) / 3.0, 0.25)

        # Acceleration bonus
        accel_bonus = min(abs(acceleration) / 2.0, 0.15) if acceleration != 0 else 0

        # Volume bonus
        vol_ratio = data.get('vol_ratio', 1.0) or 1.0
        vol_bonus = min((vol_ratio - 1.0) * 0.1, 0.15) if vol_ratio > 1.0 else 0

        # Taker summary bonus (if available from pipeline)
        if ts:
            momentum = ts.get('momentum', 0)
            if abs(momentum) > 0.1:
                vol_bonus += 0.05

        conviction = min(base + z_strength + accel_bonus + vol_bonus, 0.90)
        if conviction < 0.50:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Taker v3 {direction}: z={taker_zscore:.2f} accel={acceleration:.2f} "
                   f"vol={vol_ratio:.2f} fresh={fresh}",
            bypass_gates=False,
            details={
                'taker_zscore': float(taker_zscore), 'acceleration': float(acceleration),
                'current_taker': float(current_taker), 'vol_ratio': float(vol_ratio),
                'fresh': fresh, 'version': 'v3',
            },
        )
