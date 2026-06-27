"""
Base class for all JIMI strategies.
Every strategy must implement check() and returns a SignalResult or None.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class SignalResult:
    """Standardized signal output from any strategy."""
    strategy_name: str
    strategy_type: str          # 'event', 'flow', 'structure', 'regime', 'session'
    direction: str              # 'LONG' or 'SHORT'
    conviction: float           # 0.0-1.0 — how strong the signal is
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    sl_pct: float
    tp1_pct: float
    size_mult: float = 1.0      # position size multiplier
    reason: str = ''
    details: Dict[str, Any] = field(default_factory=dict)
    bypass_gates: bool = False   # if True, skip normal ICS/sweep gates
    timestamp: str = ''

    @property
    def rr1(self) -> float:
        """Risk:reward to TP1."""
        if self.sl_pct == 0:
            return 0
        return abs(self.tp1_pct / self.sl_pct)

    def to_dict(self) -> dict:
        return {
            'strategy': self.strategy_name,
            'type': self.strategy_type,
            'direction': self.direction,
            'conviction': round(self.conviction, 4),
            'entry': round(self.entry, 2),
            'sl': round(self.sl, 2),
            'tp1': round(self.tp1, 2),
            'tp2': round(self.tp2, 2),
            'tp3': round(self.tp3, 2),
            'sl_pct': round(self.sl_pct, 3),
            'tp1_pct': round(self.tp1_pct, 3),
            'rr1': round(self.rr1, 2),
            'size_mult': round(self.size_mult, 2),
            'reason': self.reason,
            'bypass_gates': self.bypass_gates,
            'details': self.details,
        }


class BaseStrategy:
    """Base class for all strategies."""
    name = 'base'
    strategy_type = 'unknown'
    description = ''

    def __init__(self, config=None):
        self.cfg = config or {}

    def check(self, data: dict, df_15m=None, idx=None, **kwargs) -> Optional[SignalResult]:
        """Check if this strategy has a valid signal.

        Args:
            data: Full scan result dict (all modules, derivatives, etc.)
            df_15m: 15m OHLCV DataFrame (optional, for bar-level analysis)
            idx: Current bar index (optional)

        Returns:
            SignalResult if signal found, None otherwise.
        """
        raise NotImplementedError

    def _calc_levels(self, price, direction, atr, tp_mults=(1.5, 2.5, 4.0), sl_mult=1.0):
        """Calculate SL/TP levels from ATR."""
        if direction == 'LONG':
            sl = price - sl_mult * atr
            tp1 = price + tp_mults[0] * atr
            tp2 = price + tp_mults[1] * atr
            tp3 = price + tp_mults[2] * atr
        else:
            sl = price + sl_mult * atr
            tp1 = price - tp_mults[0] * atr
            tp2 = price - tp_mults[1] * atr
            tp3 = price - tp_mults[2] * atr

        sl_pct = abs(price - sl) / price * 100
        tp1_pct = abs(tp1 - price) / price * 100
        return sl, tp1, tp2, tp3, sl_pct, tp1_pct
