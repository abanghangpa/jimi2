"""S22: Judas Sweep — detect stop-grab sweeps above resistance that reverse."""
from .base import BaseStrategy, SignalResult
import numpy as np


class JudasSweepStrategy(BaseStrategy):
    name = 'judas_sweep'
    strategy_type = 'event'
    description = 'Detect sweep above resistance (stop grab) that reverses — institutional trap pattern'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None

        # Config
        sweep_min_pct = 0.001   # 0.1% minimum sweep above resistance
        sweep_max_pct = 0.01    # 1.0% maximum sweep
        compression_max = 2.0   # max range width %
        compression_lookback = 48  # bars for compression check
        taker_threshold = 0.48  # bearish taker below this
        min_resistance_touches = 2

        closes = df_15m['Close'].values
        highs = df_15m['High'].values
        lows = df_15m['Low'].values
        volumes = df_15m['Volume'].values

        if idx < compression_lookback + 10:
            return None

        current_price = closes[idx]
        current_high = highs[idx]

        # Step 1: Check compression (narrow range = setup)
        lookback_highs = highs[max(0, idx - compression_lookback):idx + 1]
        lookback_lows = lows[max(0, idx - compression_lookback):idx + 1]
        range_high = np.max(lookback_highs)
        range_low = np.min(lookback_lows)
        if range_low <= 0:
            return None
        compression = (range_high - range_low) / range_low * 100

        if compression > compression_max:
            return None  # Not compressed — no Judas setup

        # Step 2: Find resistance levels from recent swing highs
        swing_period = 3
        window_start = max(0, idx - 200)
        swing_highs = []
        for i in range(window_start + swing_period, idx - swing_period):
            if all(highs[i] >= highs[i - j] for j in range(1, swing_period + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, swing_period + 1)):
                swing_highs.append(i)

        if len(swing_highs) < min_resistance_touches:
            return None

        # Cluster nearby swing highs into resistance zones
        sh_prices = np.sort(highs[swing_highs])
        clusters = []
        current_cluster = [sh_prices[0]]
        for p in sh_prices[1:]:
            if (p - current_cluster[-1]) / current_cluster[-1] < 0.002:  # 0.2% cluster
                current_cluster.append(p)
            else:
                if len(current_cluster) >= min_resistance_touches:
                    clusters.append(np.mean(current_cluster))
                current_cluster = [p]
        if len(current_cluster) >= min_resistance_touches:
            clusters.append(np.mean(current_cluster))

        if not clusters:
            return None

        # Step 3: Find nearest resistance above current price
        resistances = [c for c in clusters if c > current_price * 0.998]  # allow slightly below
        if not resistances:
            return None

        nearest_res = min(resistances, key=lambda x: abs(x - current_price))
        dist_to_res = abs(nearest_res - current_price) / current_price

        # Must be near resistance (within 1%)
        if dist_to_res > 0.01:
            return None

        # Step 4: Check if current bar sweeps above resistance
        sweep_pct = (current_high - nearest_res) / nearest_res

        if sweep_pct < sweep_min_pct or sweep_pct > sweep_max_pct:
            return None  # No sweep or sweep too large (breakout, not Judas)

        # Step 5: Check taker ratio (bearish — sellers present)
        taker_base = df_15m['Taker buy base asset volume'].values
        total_vol = df_15m['Volume'].values

        # Use 4-bar average taker for stability
        taker_window = max(0, idx - 3)
        taker_avg = np.mean(taker_base[taker_window:idx + 1]) / max(np.mean(total_vol[taker_window:idx + 1]), 1)

        # Also check if close is below resistance (swept and rejected)
        closed_below = closes[idx] < nearest_res

        if not closed_below and taker_avg > taker_threshold:
            return None  # No rejection and taker not bearish

        # Step 6: Calculate conviction
        sweep_score = min(sweep_pct / 0.005, 1.0) * 0.25  # tighter sweep = better
        compression_score = max(0, (compression_max - compression) / compression_max) * 0.2
        taker_score = max(0, (0.5 - taker_avg) / 0.5) * 0.25 if taker_avg < 0.5 else 0
        rejection_score = 0.3 if closed_below else 0.1

        conviction = sweep_score + compression_score + taker_score + rejection_score
        conviction = min(conviction, 0.95)

        if conviction < 0.4:
            return None

        # Step 7: Entry/SL/TP
        direction = 'SHORT'
        entry = current_price

        sl = current_high + atr * 0.3
        sl_pct = abs(sl - entry) / entry * 100

        support_levels = data.get('sr_levels', [])
        supports = [x[0] for x in support_levels if len(x) >= 3 and x[2] == 'SUPPORT' and x[0] < price]
        if supports:
            tp1 = max(supports)
        else:
            tp1 = entry - atr * 1.5
        tp2 = entry - atr * 2.5
        tp3 = entry - atr * 4.0

        tp1_pct = abs(tp1 - entry) / entry * 100

        size_mult = 0.8 if sl_pct > 0.3 else 1.0

        rr1 = tp1_pct / sl_pct if sl_pct > 0 else 0
        if rr1 < 1.0:
            return None  # Poor R:R

        return SignalResult(
            strategy_name=self.name,
            strategy_type=self.strategy_type,
            direction=direction,
            conviction=conviction,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            sl_pct=sl_pct,
            tp1_pct=tp1_pct,
            size_mult=size_mult,
            reason=f"Judas sweep: swept {sweep_pct*100:.2f}% above ${nearest_res:.2f}, "
                   f"compression={compression:.2f}%, taker={taker_avg:.3f}, "
                   f"{'rejected' if closed_below else 'sweeping'}",
            bypass_gates=True,
            details={
                'resistance': nearest_res,
                'sweep_pct': sweep_pct * 100,
                'compression': compression,
                'taker_avg': taker_avg,
                'closed_below': closed_below,
                'rr1': rr1,
            },
        )
