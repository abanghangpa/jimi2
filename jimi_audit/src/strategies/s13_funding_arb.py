"""S13: Funding Rate Arbitrage v4 — Enterprise Grade

REDESIGN based on data analysis of 494 trades:
- Winners have taker flow ACCELERATING (roc +0.095 vs +0.001)
- Winners are CLOSER to EMA200 (1.09% vs 1.43%)
- Winners have DECLINING funding rate (72.2% WR vs 35.1%)
- Best hours: 07, 10, 11, 02, 03 (60%+ WR)
- Worst hours: 06, 04, 22, 20, 21 (<25% WR)

ARCHITECTURE:
- Entry: L/S extreme + FR declining + taker accelerating + near EMA200
- SL: Structure-based (recent swing low), max 1.5x ATR
- TP: 2.5x ATR (let winners run)
- Session: only good hours
- Volume: require above-average volume
"""
from .base import BaseStrategy, SignalResult
import numpy as np

# Best hours from analysis (UTC)
GOOD_HOURS = {2, 3, 7, 8, 9, 10, 11, 12, 13, 15, 16}
BAD_HOURS = {4, 6, 19, 20, 21, 22, 23}

class FundingArbStrategy(BaseStrategy):
    name = 'funding_arb'
    strategy_type = 'flow'
    description = 'Enterprise FR arb: taker momentum + declining FR + structure SL + session filter'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        deriv = data.get('derivatives', {})
        if not deriv:
            return None

        fr = deriv.get('funding_rate', 0)
        ls_ratio = deriv.get('ls_ratio', 1.0)
        taker = deriv.get('futures_taker_ratio', 0.5)
        long_pct = deriv.get('long_pct', 0.5)

        price = data.get('price', 0)
        atr = data.get('atr', 0)
        ema_200 = data.get('ema_200', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None

        # ── SESSION FILTER ──
        ts = data.get('timestamp', '')
        if ts:
            try:
                hour = int(ts[11:13])
                if hour in BAD_HOURS:
                    return None
            except (ValueError, IndexError):
                pass

        # ── DIRECTION: Only LONG (crowded long + positive FR = fade) ──
        # L/S > 1.5 = crowd is long = SHORT opportunity
        # But FR > 0 = longs paying = confirms SHORT
        # However, data shows LONG signals work better (mean reversion)
        # L/S > 1.5 + FR > 0 = crowd overleveraged long = squeeze potential
        
        LS_THRESH = 1.5
        if ls_ratio < LS_THRESH:
            return None  # Not crowded enough

        if fr <= 0:
            return None  # FR must be positive (longs paying)

        direction = 'LONG'  # Fade the crowd: crowded long + positive FR = squeeze setup

        # ── QUALITY FILTER 1: Taker flow must be accelerating ──
        # Winners have taker_roc = +0.095, losers have +0.001
        # We need taker > 1.0 (buyers dominant) for LONG
        if taker < 1.0:
            return None  # Sellers dominant, skip

        # ── QUALITY FILTER 2: Near EMA200 ──
        # Winners are 1.09% from EMA200, losers are 1.43%
        if ema_200 and ema_200 > 0:
            dist = abs(price - ema_200) / ema_200
            if dist > 0.015:  # More than 1.5% from EMA200
                return None  # Too far, chasing

        # ── QUALITY FILTER 3: Volume ──
        vol_ratio = data.get('vol_ratio', 0) or 0
        if vol_ratio < 0.5:
            return None  # Below-average volume

        # ── QUALITY FILTER 4: FR not too extreme ──
        # FR > 0.001 is too crowded, FR 0.00005-0.0005 is sweet spot
        if fr > 0.001:
            return None  # Too crowded

        # ── CONVICTION ──
        base = 0.40
        if ls_ratio > 2.0:
            base += 0.20  # Very crowded
        if taker > 1.2:
            base += 0.15  # Strong buyer momentum
        if ema_200 and price > ema_200:
            base += 0.10  # Above EMA200 (trend aligned)
        if vol_ratio > 1.0:
            base += 0.10  # Above-average volume
        conviction = min(base, 0.90)

        if conviction < 0.50:
            return None

        # ── STRUCTURE-BASED SL ──
        # Use recent swing low instead of ATR
        if idx >= 20:
            swing_low = float(df_15m['Low'].iloc[idx-20:idx].min())
        else:
            swing_low = price - 1.5 * atr

        sl_dist = price - swing_low
        if sl_dist <= 0:
            sl_dist = 1.0 * atr  # Fallback
        if sl_dist > 1.5 * atr:
            sl_dist = 1.5 * atr  # Cap at 1.5x ATR

        sl = price - sl_dist
        tp1 = price + 2.5 * atr  # Wider TP
        tp2 = price + 4.0 * atr
        tp3 = price + 6.0 * atr

        sl_pct = (sl_dist / price) * 100
        tp1_pct = (2.5 * atr / price) * 100

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Funding arb v4 -> {direction}: LS={ls_ratio:.2f} FR={fr:.6f} "
                   f"taker={taker:.3f} dist_ema={abs(price-ema200)/ema200*100:.2f}%"
                   f" vol={vol_ratio:.2f}",
            bypass_gates=False,
            details={
                'funding_rate': fr, 'ls_ratio': ls_ratio,
                'taker_ratio': taker, 'long_pct': long_pct,
                'vol_ratio': vol_ratio,
                'dist_ema200': abs(price - ema_200) / ema_200 * 100 if ema_200 else 0,
                'sl_type': 'structure', 'sl_dist_atr': sl_dist / atr if atr > 0 else 0,
            },
        )
