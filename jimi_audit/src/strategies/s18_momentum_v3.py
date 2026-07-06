"""S18: Momentum v3 — Exhaustion Detector (state filter)

NOT a momentum chaser. Detects when momentum is DYING.

Signals:
1. Momentum deceleration: price moved but rate of change is slowing
2. Volume-momentum divergence: price rising but volume declining
3. OI-momentum divergence: price moving but OI dropping (covering, not conviction)
4. Percentile rank: is this move extreme (>90th percentile)?

Architecture: STATE FILTER — pairs with event triggers.
When event fires + momentum is exhausted → high probability reversal.
"""
from .base import BaseStrategy, SignalResult
import numpy as np


class MomentumV3Strategy(BaseStrategy):
    name = 'momentum_v3'
    strategy_type = 'exhaustion'
    description = 'Momentum exhaustion detector — deceleration + volume divergence'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None
        if idx < 80:
            return None

        closes = df_15m['Close'].values.astype(float)
        volumes = df_15m['Volume'].values.astype(float)

        # ── 1. MOMENTUM DECELERATION ──
        # Compare short-term momentum vs medium-term momentum
        mom_5 = (closes[idx] - closes[idx - 5]) / closes[idx - 5]  # 5-bar momentum
        mom_10 = (closes[idx] - closes[idx - 10]) / closes[idx - 10]  # 10-bar momentum
        mom_20 = (closes[idx] - closes[idx - 20]) / closes[idx - 20]  # 20-bar momentum

        # Acceleration: is momentum speeding up or slowing down?
        # If mom_5 < mom_10/2, momentum is decelerating
        accel = mom_5 - mom_10 / 2

        decel_signal = False
        if mom_5 > 0 and accel < 0:
            decel_signal = True  # UP but decelerating → exhaustion SHORT
        elif mom_5 < 0 and accel > 0:
            decel_signal = True  # DOWN but decelerating → exhaustion LONG

        # ── 2. VOLUME-MOMENTUM DIVERGENCE ──
        vol_recent = np.mean(volumes[idx - 5:idx])
        vol_prior = np.mean(volumes[idx - 15:idx - 5])
        vol_change = (vol_recent - vol_prior) / vol_prior if vol_prior > 0 else 0

        vol_divergence = False
        if mom_5 > 0.005 and vol_change < -0.1:
            vol_divergence = True  # price up, volume down → exhaustion
        elif mom_5 < -0.005 and vol_change < -0.1:
            vol_divergence = True  # price down, volume down → exhaustion

        # ── 3. PERCENTILE RANK ──
        # Is current move extreme compared to recent history?
        moves = []
        for j in range(idx - 80, idx - 5):
            m = abs(closes[j + 5] - closes[j]) / closes[j]
            moves.append(m)
        current_move = abs(closes[idx] - closes[idx - 5]) / closes[idx - 5]
        percentile = sum(1 for m in moves if m < current_move) / len(moves) * 100

        extreme_move = percentile > 85

        # ── 4. OI DIVERGENCE (if derivatives available) ──
        deriv = data.get('derivatives', {})
        oi_roc = deriv.get('oi_roc_1h', 0)
        oi_divergence = False
        if mom_5 > 0.005 and oi_roc < -0.02:
            oi_divergence = True  # price up, OI dropping → short covering
        elif mom_5 < -0.005 and oi_roc < -0.02:
            oi_divergence = True  # price down, OI dropping → long liquidation

        # ── COMBINE SIGNALS ──
        # Need at least 2 of 4 exhaustion signals
        signals_count = sum([decel_signal, vol_divergence, extreme_move, oi_divergence])
        if signals_count < 2:
            return None

        # Direction: fade the momentum
        if mom_5 > 0:
            direction = 'SHORT'  # momentum was up, fade it
        elif mom_5 < 0:
            direction = 'LONG'   # momentum was down, fade it
        else:
            return None

        # ── CONVICTION ──
        base = 0.40
        if decel_signal:
            base += 0.15
        if vol_divergence:
            base += 0.15
        if extreme_move:
            base += 0.10
        if oi_divergence:
            base += 0.10
        conviction = min(base, 0.85)

        # ── TP/SL ──
        # Tighter TP (exhaustion = small reversal), wider SL
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Exhaustion -> {direction}: mom5={mom_5:.4f} accel={accel:.4f} "
                   f"vol_div={vol_divergence} extreme={extreme_move} oi_div={oi_divergence}",
            bypass_gates=False,
            details={'mom_5': mom_5, 'mom_10': mom_10, 'accel': accel,
                     'vol_change': vol_change, 'percentile': percentile,
                     'decel': decel_signal, 'vol_div': vol_divergence,
                     'extreme': extreme_move, 'oi_div': oi_divergence,
                     'signals_count': signals_count},
        )
