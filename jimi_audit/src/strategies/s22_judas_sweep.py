"""S22: Judas Sweep v2 — bidirectional stop-grab traps with volume-weighted levels and dynamic thresholds."""
from .base import BaseStrategy, SignalResult
import numpy as np
import json
import os
from datetime import datetime, timezone

# Signal log path for outcome tracking
SIGNAL_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                          'data', 'judas_sweep_signals.jsonl')


def _log_signal(signal_data: dict):
    """Append signal to JSONL log for later outcome analysis."""
    try:
        os.makedirs(os.path.dirname(SIGNAL_LOG), exist_ok=True)
        with open(SIGNAL_LOG, 'a') as f:
            f.write(json.dumps(signal_data, default=str) + '\n')
    except Exception:
        pass  # Don't let logging crash the strategy


def _find_swing_points(series, period=3, mode='high'):
    """Find fractal swing highs or lows."""
    swings = []
    for i in range(period, len(series) - period):
        if mode == 'high':
            if all(series[i] >= series[i - j] for j in range(1, period + 1)) and \
               all(series[i] >= series[i + j] for j in range(1, period + 1)):
                swings.append(i)
        else:
            if all(series[i] <= series[i - j] for j in range(1, period + 1)) and \
               all(series[i] <= series[i + j] for j in range(1, period + 1)):
                swings.append(i)
    return swings


def _cluster_levels(prices, volumes, cluster_pct=0.002, min_touches=2):
    """Cluster nearby price points into zones, weighted by volume."""
    if len(prices) < min_touches:
        return []

    sorted_indices = np.argsort(prices)
    sorted_prices = prices[sorted_indices]
    sorted_vols = volumes[sorted_indices] if volumes is not None else np.ones(len(prices))

    clusters = []
    current_cluster_prices = [sorted_prices[0]]
    current_cluster_vols = [sorted_vols[0]]

    for i in range(1, len(sorted_prices)):
        if (sorted_prices[i] - current_cluster_prices[-1]) / current_cluster_prices[-1] < cluster_pct:
            current_cluster_prices.append(sorted_prices[i])
            current_cluster_vols.append(sorted_vols[i])
        else:
            if len(current_cluster_prices) >= min_touches:
                vol_weights = np.array(current_cluster_vols) / sum(current_cluster_vols)
                avg_price = np.average(current_cluster_prices, weights=vol_weights)
                total_vol = sum(current_cluster_vols)
                clusters.append({
                    'price': avg_price,
                    'touches': len(current_cluster_prices),
                    'volume': total_vol,
                    'strength': len(current_cluster_prices) * (1 + np.log1p(total_vol)),
                })
            current_cluster_prices = [sorted_prices[i]]
            current_cluster_vols = [sorted_vols[i]]

    # Last cluster
    if len(current_cluster_prices) >= min_touches:
        vol_weights = np.array(current_cluster_vols) / sum(current_cluster_vols)
        avg_price = np.average(current_cluster_prices, weights=vol_weights)
        total_vol = sum(current_cluster_vols)
        clusters.append({
            'price': avg_price,
            'touches': len(current_cluster_prices),
            'volume': total_vol,
            'strength': len(current_cluster_prices) * (1 + np.log1p(total_vol)),
        })

    clusters.sort(key=lambda x: x['strength'], reverse=True)
    return clusters[:10]


class JudasSweepStrategy(BaseStrategy):
    name = 'judas_sweep'
    strategy_type = 'event'
    description = 'Bidirectional stop-grab trap detection with volume-weighted levels'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None

        closes = df_15m['Close'].values
        highs = df_15m['High'].values
        lows = df_15m['Low'].values
        volumes = df_15m['Volume'].values
        taker_base = df_15m['Taker buy base asset volume'].values

        lookback = 200
        if idx < lookback + 50:
            return None

        current_price = closes[idx]
        current_high = highs[idx]
        current_low = lows[idx]

        # ── Dynamic thresholds based on ATR ──
        atr_pct = atr / current_price
        sweep_min_pct = max(0.0003, atr_pct * 0.2)   # 0.2x ATR minimum sweep (lower)
        sweep_max_pct = min(0.02, atr_pct * 3.0)      # 3x ATR maximum sweep
        compression_max_pct = atr_pct * 100            # 100x ATR% as compression ceiling (wider)
        compression_bars = max(24, int(48 / max(atr_pct / 0.003, 0.5)))  # dynamic lookback

        # ── Step 1: Compression check ──
        window_start = max(0, idx - compression_bars)
        range_high = np.max(highs[window_start:idx + 1])
        range_low = np.min(lows[window_start:idx + 1])
        if range_low <= 0:
            return None
        compression = (range_high - range_low) / range_low * 100

        if compression > compression_max_pct:
            return None

        # ── Step 2: Volume-weighted resistance/support detection ──
        swing_highs = _find_swing_points(highs[window_start:idx + 1], period=3, mode='high')
        swing_lows = _find_swing_points(lows[window_start:idx + 1], period=3, mode='low')

        # Offset to global index
        swing_highs = [s + window_start for s in swing_highs]
        swing_lows = [s + window_start for s in swing_lows]

        sh_prices = highs[swing_highs] if swing_highs else np.array([])
        sl_prices = lows[swing_lows] if swing_lows else np.array([])
        sh_vols = volumes[swing_highs] if swing_highs else np.array([])
        sl_vols = volumes[swing_lows] if swing_lows else np.array([])

        resistance_clusters = _cluster_levels(sh_prices, sh_vols, cluster_pct=0.003, min_touches=1)
        support_clusters = _cluster_levels(sl_prices, sl_vols, cluster_pct=0.003, min_touches=1)

        # ── Step 3: Detect sweep direction ──
        direction = None
        level_price = None
        sweep_pct = 0
        level_type = ''

        # Check SHORT: sweep above resistance
        if resistance_clusters:
            near_res = [c for c in resistance_clusters if abs(c['price'] - current_price) / current_price < 0.015]
            if near_res:
                best_res = min(near_res, key=lambda x: abs(x['price'] - current_price))
                sp = (current_high - best_res['price']) / best_res['price']
                if sweep_min_pct <= sp <= sweep_max_pct:
                    direction = 'SHORT'
                    level_price = best_res['price']
                    sweep_pct = sp
                    level_type = 'resistance'

        # Check LONG: sweep below support
        if direction is None and support_clusters:
            near_sup = [c for c in support_clusters if abs(c['price'] - current_price) / current_price < 0.015]
            if near_sup:
                best_sup = min(near_sup, key=lambda x: abs(x['price'] - current_price))
                sp = (best_sup['price'] - current_low) / best_sup['price']
                if sweep_min_pct <= sp <= sweep_max_pct:
                    direction = 'LONG'
                    level_price = best_sup['price']
                    sweep_pct = sp
                    level_type = 'support'

        if direction is None:
            return None

        # ── Step 4: Taker ratio (directional confirmation) ──
        taker_window = max(0, idx - 3)
        taker_avg = np.mean(taker_base[taker_window:idx + 1]) / max(np.mean(volumes[taker_window:idx + 1]), 1)

        if direction == 'SHORT' and taker_avg > 0.52:
            return None  # Buyers still active, not a trap
        if direction == 'LONG' and taker_avg < 0.48:
            return None  # Sellers still active, not a trap

        # ── Step 5: Rejection confirmation ──
        if direction == 'SHORT':
            rejected = closes[idx] < level_price
        else:
            rejected = closes[idx] > level_price

        if not rejected:
            # Allow if taker is very directional
            if direction == 'SHORT' and taker_avg < 0.45:
                rejected = True  # Strong selling pressure
            elif direction == 'LONG' and taker_avg > 0.55:
                rejected = True  # Strong buying pressure
            else:
                return None

        # ── Step 6: Conviction scoring ──
        # Sweep precision (tighter = better)
        sweep_score = min(sweep_pct / (sweep_max_pct * 0.5), 1.0) * 0.20

        # Compression (more compressed = better)
        compression_ratio = compression / compression_max_pct
        compression_score = max(0, (1.0 - compression_ratio)) * 0.15

        # Taker directional confirmation
        if direction == 'SHORT':
            taker_score = max(0, (0.5 - taker_avg) / 0.5) * 0.20
        else:
            taker_score = max(0, (taker_avg - 0.5) / 0.5) * 0.20

        # Rejection strength
        if direction == 'SHORT':
            rejection_dist = (level_price - closes[idx]) / atr if closes[idx] < level_price else 0
        else:
            rejection_dist = (closes[idx] - level_price) / atr if closes[idx] > level_price else 0
        rejection_score = min(rejection_dist / 1.0, 1.0) * 0.20

        # Level strength (volume-weighted)
        level_strength = 0
        if level_type == 'resistance' and resistance_clusters:
            matched = [c for c in resistance_clusters if abs(c['price'] - level_price) / level_price < 0.005]
            if matched:
                level_strength = min(matched[0]['strength'] / 10.0, 1.0) * 0.15
        elif level_type == 'support' and support_clusters:
            matched = [c for c in support_clusters if abs(c['price'] - level_price) / level_price < 0.005]
            if matched:
                level_strength = min(matched[0]['strength'] / 10.0, 1.0) * 0.15

        conviction = sweep_score + compression_score + taker_score + rejection_score + level_strength
        conviction = min(conviction, 0.95)

        if conviction < 0.40:
            return None

        # ── Step 7: Entry/SL/TP ──
        entry = current_price

        if direction == 'SHORT':
            sl = current_high + atr * 0.3
            sl_pct = abs(sl - entry) / entry * 100

            support_levels = data.get('sr_levels', [])
            supports = [x[0] for x in support_levels if len(x) >= 3 and x[2] == 'SUPPORT' and x[0] < price]
            tp1 = max(supports) if supports else entry - atr * 1.5
            tp2 = entry - atr * 2.5
            tp3 = entry - atr * 4.0
        else:
            sl = current_low - atr * 0.3
            sl_pct = abs(sl - entry) / entry * 100

            support_levels = data.get('sr_levels', [])
            resistances = [x[0] for x in support_levels if len(x) >= 3 and x[2] == 'RESISTANCE' and x[0] > price]
            tp1 = min(resistances) if resistances else entry + atr * 1.5
            tp2 = entry + atr * 2.5
            tp3 = entry + atr * 4.0

        tp1_pct = abs(tp1 - entry) / entry * 100
        rr1 = tp1_pct / sl_pct if sl_pct > 0 else 0

        if rr1 < 1.0:
            return None

        size_mult = 0.8 if sl_pct > 0.3 else 1.0

        # ── Step 8: Log signal for outcome tracking ──
        _log_signal({
            'timestamp': str(data.get('timestamp', datetime.now(timezone.utc))),
            'strategy': self.name,
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'conviction': conviction,
            'level_price': level_price,
            'level_type': level_type,
            'sweep_pct': sweep_pct * 100,
            'compression': compression,
            'taker_avg': taker_avg,
            'atr': atr,
            'rr1': rr1,
            'outcome': None,  # filled in later by outcome tracker
        })

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
            reason=f"Judas sweep {direction}: swept {sweep_pct*100:.2f}% {('above' if direction == 'SHORT' else 'below')} "
                   f"${level_price:.2f} ({level_type}), comp={compression:.2f}%, taker={taker_avg:.3f}, "
                   f"{'rejected' if rejected else 'sweeping'}",
            bypass_gates=True,
            details={
                'level_price': level_price,
                'level_type': level_type,
                'sweep_pct': sweep_pct * 100,
                'compression': compression,
                'taker_avg': taker_avg,
                'rejected': rejected,
                'rr1': rr1,
                'resistance_clusters': len(resistance_clusters),
                'support_clusters': len(support_clusters),
            },
        )
