"""S14: Whale Watch v2 — real on-chain whale data + contrarian L/S.

v1 → v2 CHANGES:
1. Uses real whale data from whale_tracker.py (exchange flow, accumulation/distribution)
2. Combines with derivatives L/S ratio for confirmation
3. Time-in-position filter: whale signal must be sustained (not just a snapshot)
4. Reads whale_signals.jsonl for recent whale activity
5. Independent of pipeline — reads from data files directly
"""
from .base import BaseStrategy, SignalResult
import json, os
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WHALE_STATE = os.path.join(BASE_DIR, "data", "whale", "whale_state.json")
WHALE_SIGNALS = os.path.join(BASE_DIR, "data", "whale", "whale_signals.jsonl")
DERIV_CSV = os.path.join(BASE_DIR, "data", "derivatives_history", "derivatives_collected.csv")

ROLLING_WINDOW = 200


def _read_whale_state():
    """Read current whale tracker state."""
    if not os.path.exists(WHALE_STATE):
        return None
    try:
        with open(WHALE_STATE) as f:
            return json.load(f)
    except Exception:
        return None


def _read_whale_signals(minutes=60):
    """Read recent whale signals."""
    if not os.path.exists(WHALE_SIGNALS):
        return []
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cutoff_iso = cutoff.isoformat()
    signals = []
    try:
        with open(WHALE_SIGNALS) as f:
            for line in f:
                try:
                    sig = json.loads(line.strip())
                    if sig.get("timestamp", "") >= cutoff_iso:
                        signals.append(sig)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return signals


def _read_rolling_ls_stats():
    """Compute rolling mean and std of L/S ratio."""
    if not os.path.exists(DERIV_CSV):
        return None
    try:
        ratios = []
        with open(DERIV_CSV) as f:
            header = f.readline().strip().split(",")
            ls_idx = header.index("ls_ratio") if "ls_ratio" in header else -1
            if ls_idx < 0:
                return None
            for line in f:
                parts = line.strip().split(",")
                if len(parts) > ls_idx:
                    try:
                        r = float(parts[ls_idx])
                        if r > 0:
                            ratios.append(r)
                    except ValueError:
                        continue
        if len(ratios) < 30:
            return None
        window = ratios[-ROLLING_WINDOW:]
        return {"mean": float(np.mean(window)), "std": float(np.std(window)), "count": len(window)}
    except Exception:
        return None


def _read_ls_duration(ls_ratio, threshold):
    """How long has L/S been above/below threshold."""
    if not os.path.exists(DERIV_CSV):
        return 0
    try:
        ratios = []
        with open(DERIV_CSV) as f:
            header = f.readline().strip().split(",")
            ls_idx = header.index("ls_ratio") if "ls_ratio" in header else -1
            if ls_idx < 0:
                return 0
            for line in f:
                parts = line.strip().split(",")
                if len(parts) > ls_idx:
                    try:
                        ratios.append(float(parts[ls_idx]))
                    except ValueError:
                        continue
        if not ratios:
            return 0
        direction = "above" if ls_ratio > threshold else "below"
        count = 0
        for r in reversed(ratios):
            if direction == "above" and r > threshold:
                count += 1
            elif direction == "below" and r < threshold:
                count += 1
            else:
                break
        return count * 15  # 15 min per entry
    except Exception:
        return 0


class WhaleWatchStrategy(BaseStrategy):
    name = 'whale_watch'
    strategy_type = 'flow'
    description = 'v2: real on-chain whale data + contrarian L/S + time-in-position'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr:
            return None

        deriv = data.get('derivatives', {})
        ls_ratio = deriv.get('ls_ratio', 1.0)

        # ── READ WHALE DATA (new) ──
        whale_state = _read_whale_state()
        whale_signals = _read_whale_signals(minutes=60)

        if not whale_state and not whale_signals:
            return None

        # ── WHALE EXCHANGE FLOW ──
        net_flow = whale_state.get("net_exchange_flow_24h", 0) if whale_state else 0
        accumulation_score = whale_state.get("accumulation_score", 0) if whale_state else 0
        total_transfers = whale_state.get("total_transfers", 0) if whale_state else 0

        # ── WHALE SIGNAL DIRECTION ──
        whale_direction = None
        whale_strength = 0

        # Primary: net exchange flow
        # Negative = outflow from exchanges = accumulation = LONG
        # Positive = inflow to exchanges = distribution = SHORT
        if abs(net_flow) > 500:  # 500 ETH threshold
            if net_flow < -500:
                whale_direction = 'LONG'
                whale_strength = min(abs(net_flow) / 50000, 1.0)  # max at 50k ETH
            elif net_flow > 500:
                whale_direction = 'SHORT'
                whale_strength = min(abs(net_flow) / 50000, 1.0)

        # Secondary: recent whale signals consistency
        if whale_signals:
            long_signals = sum(1 for s in whale_signals if s.get("direction") == "LONG")
            short_signals = sum(1 for s in whale_signals if s.get("direction") == "SHORT")
            if long_signals > short_signals and long_signals >= 3:
                if whale_direction is None:
                    whale_direction = 'LONG'
                whale_strength = max(whale_strength, long_signals / len(whale_signals))
            elif short_signals > long_signals and short_signals >= 3:
                if whale_direction is None:
                    whale_direction = 'SHORT'
                whale_strength = max(whale_strength, short_signals / len(whale_signals))

        if not whale_direction:
            return None

        # ── CONTRARIAN L/S CONFIRMATION (new) ──
        # Whale flow + extreme L/S = stronger signal
        stats = _read_rolling_ls_stats()
        if stats and stats["std"] > 0.01:
            ls_zscore = (ls_ratio - stats["mean"]) / stats["std"]
            ls_mean = stats["mean"]
        else:
            ls_zscore = (ls_ratio - 2.15) / 0.3
            ls_mean = 2.15

        # Contrarian: if whales are accumulating AND crowd is short → strong LONG
        ls_confirm = 0
        if whale_direction == 'LONG' and ls_zscore < -0.5:
            ls_confirm = 0.15  # crowd is short, whales buying
        elif whale_direction == 'SHORT' and ls_zscore > 0.5:
            ls_confirm = 0.15  # crowd is long, whales selling

        # ── TIME-IN-POSITION FILTER (new) ──
        # How long has the whale signal been active?
        if stats:
            threshold = ls_mean + ls_zscore * stats["std"] * 0.5  # approximate
            duration = _read_ls_duration(ls_ratio, threshold=ls_mean)
        else:
            duration = _read_ls_duration(ls_ratio, threshold=2.15)

        # Need at least 30 minutes of sustained whale activity
        if duration < 30 and abs(net_flow) < 5000:
            return None  # too recent or too small

        # ── EMA200 FILTER ──
        ema_200 = data.get('ema_200', 0)
        if ema_200 and ema_200 > 0:
            dist = (price - ema_200) / ema_200
            if whale_direction == 'LONG' and dist < -0.03:
                return None
            if whale_direction == 'SHORT' and dist > 0.03:
                return None

        # ── CONVICTION ──
        base = 0.40
        whale_bonus = whale_strength * 0.25
        ls_bonus = ls_confirm
        duration_bonus = min(duration / 480, 0.10)  # max at 8 hours
        transfer_bonus = min(total_transfers / 5000, 0.05)  # more data = more reliable

        conviction = min(base + whale_bonus + ls_bonus + duration_bonus + transfer_bonus, 0.85)
        if conviction < 0.45:
            return None

        # ── TP/SL ──
        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, whale_direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.2)

        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=whale_direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.7,
            reason=f"Whale v2 {whale_direction}: net_flow={net_flow:.0f}ETH "
                   f"LS={ls_ratio:.2f} z={ls_zscore:.2f} dur={duration}m",
            bypass_gates=False,
            details={
                'net_exchange_flow_24h': net_flow, 'whale_strength': whale_strength,
                'ls_ratio': ls_ratio, 'ls_zscore': float(ls_zscore),
                'duration_min': duration, 'total_transfers': total_transfers,
                'recent_signals': len(whale_signals),
                'version': 'v2',
            },
        )
