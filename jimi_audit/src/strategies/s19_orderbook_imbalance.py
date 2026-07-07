"""S19: Order Book Imbalance v2 — Enterprise Grade

REDESIGN based on analysis of 502 trades:
- Session filter: good hours {0,1,7,10,12,15,21}, bad hours {5,11,13,14,23}
- Direction: LONG only (+6.3pp WR over SHORT)
- Volume: skip vol_ratio 1.0-1.5 (32.8% WR zone)
- EMA200: prefer price 1-3% above (54.4% WR)
- Momentum: avoid recent selloffs (mom_5 < -0.01 = 30% WR)

ARCHITECTURE:
- State: Order book buy/sell imbalance detection
- Quality: session + direction + volume + EMA filters built-in
- TP: 2.5x ATR (let winners run)
- SL: structure-based (recent swing low)
"""
from .base import BaseStrategy, SignalResult
import numpy as np

# Best hours from analysis (UTC)
GOOD_HOURS = {0, 1, 7, 10, 12, 15, 21}
BAD_HOURS = {5, 11, 13, 14, 23}


class OrderBookImbalanceStrategy(BaseStrategy):
    min_vol_ratio = 0.12
    name = 'orderbook_imbalance'
    strategy_type = 'flow'
    description = 'Enterprise OB imbalance: session + LONG only + volume + EMA filters'

    def check(self, data, df_15m=None, idx=None, **kwargs):
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

        # ── DIRECTION: LONG only ──
        # Data shows LONG 48.4% WR vs SHORT 42.1% WR
        direction = 'LONG'

        # ── QUALITY FILTER 1: Volume ──
        vol_ratio = data.get('vol_ratio', 1.0) or 1.0
        if 1.0 <= vol_ratio < 1.5:
            return None  # Dead zone: 32.8% WR

        # ── QUALITY FILTER 2: EMA200 ──
        if ema_200 and ema_200 > 0:
            dist_ema = (price - ema_200) / ema_200
            if dist_ema < -0.01:
                return None  # Below EMA200 by >1%: 38.1% WR
            # Prefer 1-3% above (54.4% WR)
            ema_bonus = 0.10 if 0.01 < dist_ema < 0.03 else 0.0
        else:
            ema_bonus = 0.0

        # ── QUALITY FILTER 3: Momentum ──
        if idx >= 5:
            mom_5 = (float(df_15m['Close'].iloc[idx]) - float(df_15m['Close'].iloc[idx-5])) / float(df_15m['Close'].iloc[idx-5])
            if mom_5 < -0.01:
                return None  # Recent selloff: 30% WR
            mom_bonus = 0.05 if 0 < mom_5 < 0.01 else 0.0
        else:
            mom_bonus = 0.0

        # ── OB IMBALANCE DETECTION ──
        ob = data.get('ob_imbalance', {})
        if not ob:
            # Fallback: check order_flow data
            order_flow = data.get('order_flow', {})
            if order_flow:
                ob_ratio = order_flow.get('ob_imbalance', 0)
            else:
                return None
        else:
            ob_ratio = ob.get('ratio', 0)

        # Need significant imbalance
        if abs(ob_ratio) < 0.15:
            return None

        # For LONG: need buy-side imbalance
        if ob_ratio < 0:
            return None  # Sell-side dominant

        # ── CONVICTION ──
        base = 0.50
        if abs(ob_ratio) > 0.30:
            base += 0.15
        if abs(ob_ratio) > 0.50:
            base += 0.10
        conviction = min(base + ema_bonus + mom_bonus, 0.90)

        if conviction < 0.50:
            return None

        # ── STRUCTURE-BASED SL ──
        if idx >= 20:
            swing_low = float(df_15m['Low'].iloc[idx-20:idx].min())
        else:
            swing_low = price - 1.5 * atr

        sl_dist = price - swing_low
        if sl_dist <= 0:
            sl_dist = 1.0 * atr
        if sl_dist > 1.5 * atr:
            sl_dist = 1.5 * atr

        sl = price - sl_dist
        tp1 = price + 2.5 * atr
        tp2 = price + 4.0 * atr
        tp3 = price + 6.0 * atr

        sl_pct = (sl_dist / price) * 100
        tp1_pct = (2.5 * atr / price) * 100

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"OB imbalance v2 -> {direction}: ob_ratio={ob_ratio:.3f} "
                   f"vol={vol_ratio:.2f} dist_ema={dist_ema*100:.2f}%",
            bypass_gates=False,
            details={
                'ob_ratio': ob_ratio, 'vol_ratio': vol_ratio,
                'dist_ema200': dist_ema * 100 if ema_200 else 0,
                'sl_type': 'structure',
            },
        )
