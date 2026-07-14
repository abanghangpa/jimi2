"""S10: Structural Break v2 — independent BOS/ChoCH detection.

v1 → v2 CHANGES:
1. Independent detection: doesn't need M1/M2 modules — detects BOS/ChoCH from df_15m
2. BOS (Break of Structure): price breaks a swing high/low in trend direction
3. ChoCH (Change of Character): price breaks a swing high/low against trend direction
4. Momentum confirmation: volume + taker flow must agree with direction
5. EMA200 trend filter: regime-aware (3% ranging, 5% trending)
"""
from .base import BaseStrategy, SignalResult
import numpy as np


def _detect_structure_break(df_15m, idx, atr):
    """
    Detect BOS (Break of Structure) and ChoCH (Change of Character).

    BOS: In an uptrend, price breaks above the last swing high → continuation LONG
         In a downtrend, price breaks below the last swing low → continuation SHORT
    ChoCH: In an uptrend, price breaks below the last swing low → reversal SHORT
           In a downtrend, price breaks above the last swing high → reversal LONG

    Returns dict with break info or None.
    """
    if idx < 30:
        return None

    closes = df_15m['Close'].values.astype(float)
    highs = df_15m['High'].values.astype(float)
    lows = df_15m['Low'].values.astype(float)
    volumes = df_15m['Volume'].values.astype(float)

    current_close = closes[idx]
    current_high = highs[idx]
    current_low = lows[idx]

    # ── FIND RECENT SWING POINTS ──
    swing_highs = []
    swing_lows = []

    for i in range(3, min(48, idx - 3)):
        bar_idx = idx - i
        # Swing high
        if (highs[bar_idx] > highs[bar_idx-1] and
            highs[bar_idx] > highs[bar_idx-2] and
            highs[bar_idx] > highs[bar_idx-3] and
            highs[bar_idx] > highs[bar_idx+1] and
            highs[bar_idx] > highs[bar_idx+2] and
            highs[bar_idx] > highs[bar_idx+3]):
            swing_highs.append({"price": highs[bar_idx], "idx": bar_idx})
        # Swing low
        if (lows[bar_idx] < lows[bar_idx-1] and
            lows[bar_idx] < lows[bar_idx-2] and
            lows[bar_idx] < lows[bar_idx-3] and
            lows[bar_idx] < lows[bar_idx+1] and
            lows[bar_idx] < lows[bar_idx+2] and
            lows[bar_idx] < lows[bar_idx+3]):
            swing_lows.append({"price": lows[bar_idx], "idx": bar_idx})

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    # Sort by recency
    swing_highs.sort(key=lambda x: x["idx"], reverse=True)
    swing_lows.sort(key=lambda x: x["idx"], reverse=True)

    # ── DETERMINE TREND FROM SWING STRUCTURE ──
    # Higher highs + higher lows = uptrend
    # Lower highs + lower lows = downtrend
    recent_sh = swing_highs[:3]
    recent_sl = swing_lows[:3]

    hh_count = 0  # higher highs
    lh_count = 0  # lower highs
    hl_count = 0  # higher lows
    ll_count = 0  # lower lows

    for i in range(len(recent_sh) - 1):
        if recent_sh[i]["price"] > recent_sh[i+1]["price"]:
            hh_count += 1
        else:
            lh_count += 1

    for i in range(len(recent_sl) - 1):
        if recent_sl[i]["price"] > recent_sl[i+1]["price"]:
            hl_count += 1
        else:
            ll_count += 1

    # Determine trend
    uptrend_score = hh_count + hl_count
    downtrend_score = lh_count + ll_count

    if uptrend_score > downtrend_score:
        trend = 'UP'
    elif downtrend_score > uptrend_score:
        trend = 'DOWN'
    else:
        trend = 'NEUTRAL'

    # ── CHECK FOR BOS/ChoCH ──
    last_sh = swing_highs[0]["price"]
    last_sl = swing_lows[0]["price"]
    prev_sh = swing_highs[1]["price"] if len(swing_highs) > 1 else last_sh
    prev_sl = swing_lows[1]["price"] if len(swing_lows) > 1 else last_sl

    # Check current bar for break
    vol_ma = np.mean(volumes[max(0, idx-20):idx+1])
    vol_ratio = volumes[idx] / max(vol_ma, 1)

    # BOS UP: price breaks above last swing high in uptrend
    if current_high > last_sh and trend == 'UP':
        # Confirm: close above the level
        if current_close > last_sh:
            # Volume confirmation
            if vol_ratio > 0.8:
                return {
                    "type": "BOS",
                    "direction": "LONG",
                    "level": last_sh,
                    "trend": trend,
                    "vol_ratio": vol_ratio,
                    "break_pct": (current_high - last_sh) / last_sh * 100,
                }

    # BOS DOWN: price breaks below last swing low in downtrend
    if current_low < last_sl and trend == 'DOWN':
        if current_close < last_sl:
            if vol_ratio > 0.8:
                return {
                    "type": "BOS",
                    "direction": "SHORT",
                    "level": last_sl,
                    "trend": trend,
                    "vol_ratio": vol_ratio,
                    "break_pct": (last_sl - current_low) / last_sl * 100,
                }

    # ChoCH DOWN: price breaks below last swing low in uptrend (reversal)
    if current_low < last_sl and trend == 'UP':
        if current_close < last_sl:
            if vol_ratio > 1.0:  # need stronger volume for reversal
                return {
                    "type": "ChoCH",
                    "direction": "SHORT",
                    "level": last_sl,
                    "trend": trend,
                    "vol_ratio": vol_ratio,
                    "break_pct": (last_sl - current_low) / last_sl * 100,
                }

    # ChoCH UP: price breaks above last swing high in downtrend (reversal)
    if current_high > last_sh and trend == 'DOWN':
        if current_close > last_sh:
            if vol_ratio > 1.0:
                return {
                    "type": "ChoCH",
                    "direction": "LONG",
                    "level": last_sh,
                    "trend": trend,
                    "vol_ratio": vol_ratio,
                    "break_pct": (current_high - last_sh) / last_sh * 100,
                }

    return None


class StructuralBreakStrategy(BaseStrategy):
    name = 'structural_break'
    strategy_type = 'structure'
    description = 'v2: independent BOS/ChoCH detection + momentum confirmation'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None

        # ── INDEPENDENT DETECTION (new) ──
        sb = _detect_structure_break(df_15m, idx, atr)

        # Fallback: M1/M2 modules (if available)
        if not sb:
            m1 = data.get('m1', {})
            m2 = data.get('m2', {})
            m1_dir = m1.get('direction', 'NEUTRAL')
            m2_status = m2.get('status', 'NEUTRAL')

            if m1_dir != 'NEUTRAL':
                if m1_dir == 'BULLISH' and m2_status in ('BULLISH', 'NEUTRAL'):
                    sb = {"type": "module", "direction": "LONG", "level": price, "trend": "UP", "vol_ratio": 1.0, "break_pct": 0}
                elif m1_dir == 'BEARISH' and m2_status in ('BEARISH', 'NEUTRAL'):
                    sb = {"type": "module", "direction": "SHORT", "level": price, "trend": "DOWN", "vol_ratio": 1.0, "break_pct": 0}

        if not sb:
            return None

        direction = sb["direction"]
        break_type = sb["type"]

        # ── MOMENTUM CONFIRMATION (new) ──
        # Taker flow must agree with direction
        taker = data.get('raw_taker_ratio', 0.5)
        if direction == 'LONG' and taker < 0.45:
            return None  # seller-dominated — don't go LONG
        if direction == 'SHORT' and taker > 0.55:
            return None  # buyer-dominated — don't go SHORT

        # ── EMA200 FILTER (regime-aware) ──
        ema_200 = data.get('ema_200', 0)
        if ema_200 and ema_200 > 0:
            dist = (price - ema_200) / ema_200

            # Determine regime
            closes = df_15m['Close'].values.astype(float)
            if idx >= 48:
                trend_change = (closes[idx] - closes[idx-48]) / closes[idx-48]
                ema_band = 0.05 if abs(trend_change) > 0.03 else 0.03
            else:
                ema_band = 0.03

            if direction == 'LONG' and dist < -ema_band:
                return None
            if direction == 'SHORT' and dist > ema_band:
                return None

        # ── CONVICTION ──
        base = 0.40

        # Break type bonus (BOS is stronger than ChoCH)
        type_bonus = 0.15 if break_type == "BOS" else 0.10

        # Volume bonus
        vol_bonus = min((sb.get("vol_ratio", 1.0) - 1.0) * 0.10, 0.15)

        # Break magnitude bonus
        break_bonus = min(sb.get("break_pct", 0) / 2, 0.10)

        # Taker alignment bonus
        taker_bonus = 0
        if direction == 'LONG' and taker > 0.55:
            taker_bonus = 0.10
        elif direction == 'SHORT' and taker < 0.45:
            taker_bonus = 0.10

        # Module bonus (if modules agree)
        module_bonus = 0
        if break_type == "module":
            m1 = data.get('m1', {})
            m13 = data.get('m13', {})
            module_bonus = (m1.get('score', 0.5) * 0.4 + m13.get('score', 0.5) * 0.3) * 0.10

        conviction = min(base + type_bonus + vol_bonus + break_bonus + taker_bonus + module_bonus, 0.90)
        if conviction < 0.50:
            return None

        # ── TP/SL ──
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Struct break v2 {direction}: {break_type} ${sb['level']:.2f} "
                   f"trend={sb['trend']} vol={sb.get('vol_ratio',1):.2f} taker={taker:.3f}",
            bypass_gates=False,
            details={
                'break_type': break_type, 'level': sb['level'],
                'trend': sb['trend'], 'vol_ratio': sb.get('vol_ratio', 1),
                'break_pct': sb.get('break_pct', 0), 'taker': taker,
                'version': 'v2',
            },
        )
