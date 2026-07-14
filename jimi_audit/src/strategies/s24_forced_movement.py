"""S24: Forced Movement v2 — structural mechanics where participants have NO CHOICE.

v1 → v2 CHANGES:
1. Basis threshold lowered from -0.3% to -0.1% (3x more sensitive)
2. Added "basis widening" signal — basis moving from -0.02% to -0.05% is a signal
3. OI divergence uses OI CSV history (accumulating) + live OI from derivatives as fallback
4. Funding squeeze L/S threshold lowered from 2.0 to 1.8 (catches more squeezes)
5. Added OI-from-derivatives fallback when CSV has insufficient data
"""
from .base import BaseStrategy, SignalResult
import json, os
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FM_DATA = os.path.join(BASE_DIR, "data", "forced_movement")
LIQ_LOG = os.path.join(FM_DATA, "liquidation_events.jsonl")
OI_CSV = os.path.join(FM_DATA, "oi_history.csv")
FUNDING_CSV = os.path.join(FM_DATA, "funding_history.csv")
BASIS_CSV = os.path.join(FM_DATA, "basis_history.csv")


def _read_oi_roc(hours=1):
    """Compute OI rate of change from collected history."""
    if not os.path.exists(OI_CSV):
        return None
    lines = []
    try:
        with open(OI_CSV) as f:
            lines = f.readlines()
    except Exception:
        return None
    if len(lines) < 2:
        return None
    latest = lines[-1].strip().split(",")
    current_oi = float(latest[1])
    current_ts = int(latest[0])
    target_ts = current_ts - (hours * 3600 * 1000)
    prev_oi = current_oi
    for line in reversed(lines[:-1]):
        parts = line.strip().split(",")
        if len(parts) >= 2 and int(parts[0]) <= target_ts:
            prev_oi = float(parts[1])
            break
    if prev_oi == current_oi:
        return None  # no older data to compare
    roc = (current_oi - prev_oi) / prev_oi if prev_oi > 0 else 0
    return {"roc": roc, "current": current_oi, "prev": prev_oi}


def _read_cumulative_funding(hours=72):
    """Sum funding rates over N hours."""
    if not os.path.exists(FUNDING_CSV):
        return 0, 0
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    total = 0.0
    count = 0
    try:
        with open(FUNDING_CSV) as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    try:
                        ts = int(parts[1])
                        rate = float(parts[2])
                        if ts >= cutoff_ms:
                            total += rate
                            count += 1
                    except (ValueError, IndexError):
                        continue
    except Exception:
        pass
    return total, count


def _read_recent_liqs(minutes=15):
    """Count recent liquidation events."""
    if not os.path.exists(LIQ_LOG):
        return 0, 0, 0
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    long_vol = 0
    short_vol = 0
    count = 0
    try:
        with open(LIQ_LOG) as f:
            for line in f:
                try:
                    e = json.loads(line.strip())
                    if e.get("ts", 0) >= cutoff_ms:
                        count += 1
                        if e.get("side") == "Sell":
                            long_vol += e.get("qty", 0)
                        else:
                            short_vol += e.get("qty", 0)
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass
    return count, long_vol, short_vol


def _read_basis_history():
    """Read basis history and compute current + change over last 30 min."""
    if not os.path.exists(BASIS_CSV):
        return 0, 0
    try:
        lines = []
        with open(BASIS_CSV) as f:
            lines = f.readlines()
        if not lines:
            return 0, 0

        # Current basis
        current = float(lines[-1].strip().split(",")[3])

        # Basis 30 min ago (30 entries at 1/min)
        if len(lines) >= 30:
            prev = float(lines[-30].strip().split(",")[3])
        elif len(lines) >= 5:
            prev = float(lines[-5].strip().split(",")[3])
        else:
            prev = current

        change = current - prev  # positive = widening contango, negative = widening backwardation
        return current, change
    except Exception:
        return 0, 0


class ForcedMovementStrategy(BaseStrategy):
    name = 'forced_movement'
    strategy_type = 'event'
    description = 'v2: lower thresholds + basis widening + OI fallback + L/S 1.8'

    def check(self, data, df_15m=None, idx=None, **kwargs):
        price = data.get('price', 0)
        atr = data.get('atr', 0)
        if not price or not atr or df_15m is None or idx is None:
            return None
        if idx < 20:
            return None

        signals = []
        deriv = data.get('derivatives', {})
        ls_ratio = deriv.get('ls_ratio', 1.0)

        # ── Sub-signal 1: OI DIVERGENCE ──
        closes = df_15m['Close'].values.astype(float)
        high_20 = float(np.max(closes[max(0, idx-20):idx+1]))
        low_20 = float(np.min(closes[max(0, idx-20):idx+1]))

        # Try OI from CSV first
        oi_data = _read_oi_roc(hours=1)
        oi_roc = None

        if oi_data and oi_data["roc"] != 0:
            oi_roc = oi_data["roc"]
        else:
            # Fallback: OI from derivatives data (new)
            oi_roc_deriv = deriv.get('oi_roc_1h', None)
            if oi_roc_deriv is not None and oi_roc_deriv != 0:
                oi_roc = oi_roc_deriv

        if oi_roc is not None:
            if price >= high_20 * 0.995 and oi_roc < -0.003:
                # Price near high, OI dropping — short covering rally
                strength = min(abs(oi_roc) * 50, 1.0)
                signals.append({
                    "name": "oi_divergence",
                    "direction": "SHORT",
                    "strength": strength,
                    "detail": f"Price ${price:.2f} near 20h high ${high_20:.2f}, OI ROC={oi_roc:.4f}"
                })
            elif price <= low_20 * 1.005 and oi_roc < -0.003:
                # Price near low, OI dropping — long liquidation exhausted
                strength = min(abs(oi_roc) * 50, 1.0)
                signals.append({
                    "name": "oi_divergence",
                    "direction": "LONG",
                    "strength": strength,
                    "detail": f"Price ${price:.2f} near 20h low ${low_20:.2f}, OI ROC={oi_roc:.4f}"
                })

        # ── Sub-signal 2: FUNDING SQUEEZE ──
        cum_fr, fr_count = _read_cumulative_funding(hours=72)

        # L/S threshold lowered from 2.0 to 1.8
        if cum_fr > 0.003 and ls_ratio > 1.8:
            strength = min(cum_fr / 0.01, 1.0)
            signals.append({
                "name": "funding_squeeze",
                "direction": "SHORT",
                "strength": strength,
                "detail": f"72h cum FR={cum_fr:.5f}, L/S={ls_ratio:.2f} (longs squeezed)"
            })
        elif cum_fr < -0.003 and ls_ratio < 0.55:
            strength = min(abs(cum_fr) / 0.01, 1.0)
            signals.append({
                "name": "funding_squeeze",
                "direction": "LONG",
                "strength": strength,
                "detail": f"72h cum FR={cum_fr:.5f}, L/S={ls_ratio:.2f} (shorts squeezed)"
            })

        # ── Sub-signal 3: LIQUIDATION CASCADE ──
        liq_count, long_liq, short_liq = _read_recent_liqs(minutes=15)
        total_liq = long_liq + short_liq
        if liq_count >= 3 and total_liq > 5:
            if long_liq > short_liq * 2:
                strength = min(long_liq / 100, 1.0)
                signals.append({
                    "name": "liq_cascade",
                    "direction": "SHORT",
                    "strength": strength,
                    "detail": f"Long liq: {long_liq:.1f} ETH in 15m ({liq_count} events)"
                })
            elif short_liq > long_liq * 2:
                strength = min(short_liq / 100, 1.0)
                signals.append({
                    "name": "liq_cascade",
                    "direction": "LONG",
                    "strength": strength,
                    "detail": f"Short liq: {short_liq:.1f} ETH in 15m ({liq_count} events)"
                })

        # ── Sub-signal 4: BASIS CONVERGENCE / WIDENING ──
        basis, basis_change = _read_basis_history()

        # Static threshold (lowered from -0.3% to -0.1%)
        if basis < -0.001:
            strength = min(abs(basis) / 0.005, 1.0)
            signals.append({
                "name": "basis_convergence",
                "direction": "LONG",
                "strength": strength,
                "detail": f"Basis={basis*100:.3f}% (backwardation)"
            })
        elif basis > 0.001:
            strength = min(basis / 0.005, 1.0)
            signals.append({
                "name": "basis_convergence",
                "direction": "SHORT",
                "strength": strength,
                "detail": f"Basis={basis*100:.3f}% (contango)"
            })

        # Widening signal (new) — basis moving further from zero
        if abs(basis_change) > 0.0005:  # 0.05% change in 30 min
            if basis_change < -0.0005:
                # Backwardation widening → perps will bounce
                strength = min(abs(basis_change) / 0.002, 0.8)
                signals.append({
                    "name": "basis_widening",
                    "direction": "LONG",
                    "strength": strength,
                    "detail": f"Basis widening: {basis_change*100:.3f}% change in 30m"
                })
            elif basis_change > 0.0005:
                # Contango widening → perps will drop
                strength = min(basis_change / 0.002, 0.8)
                signals.append({
                    "name": "basis_widening",
                    "direction": "SHORT",
                    "strength": strength,
                    "detail": f"Basis widening: +{basis_change*100:.3f}% change in 30m"
                })

        # ── COMPOSITE DECISION ──
        if not signals:
            return None

        long_votes = sum(1 for s in signals if s["direction"] == "LONG")
        short_votes = sum(1 for s in signals if s["direction"] == "SHORT")

        if long_votes > short_votes:
            direction = "LONG"
        elif short_votes > long_votes:
            direction = "SHORT"
        else:
            direction = max(signals, key=lambda x: x["strength"])["direction"]

        avg_str = sum(s["strength"] for s in signals) / len(signals)
        multi_bonus = min((len(signals) - 1) * 0.15, 0.30)
        conviction = min(avg_str * 0.7 + multi_bonus + 0.20, 0.90)

        if conviction < 0.45:
            return None

        sl, tp1, tp2, tp3, sl_pct, tp1_pct = self._calc_levels(
            price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.5)

        reason_parts = [f"{s['name']}={s['direction']}" for s in signals]
        return SignalResult(
            strategy_name=self.name, strategy_type=self.strategy_type,
            direction=direction, conviction=conviction,
            entry=price, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            sl_pct=sl_pct, tp1_pct=tp1_pct,
            size_mult=0.8,
            reason=f"Forced v2 ({', '.join(reason_parts)}) conv={conviction:.2f}",
            bypass_gates=True,
            details={
                "signals": [s["name"] for s in signals],
                "signal_details": signals,
                "oi_roc": oi_roc,
                "cum_funding_72h": cum_fr,
                "ls_ratio": ls_ratio,
                "basis": basis,
                "basis_change": basis_change,
                "liq_count": liq_count,
                "version": "v2",
            },
        )
