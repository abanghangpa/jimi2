
"""
Regime Selector — uses m10 sub-components to select which strategies are active.

Instead of using m10 as a directional signal (it's anti-predictive),
use it as a regime classifier that determines which strategies should fire.

Data proof (from 1378 scans):
  STRONG_DOWN regime: cross_asset=61.9%, structural_break=58.2%, mtf_confluence=58.0%
  (these strategies outperform in bearish macro conditions)

Architecture:
  m10 components -> regime classification -> strategy weight adjustment
"""
from typing import Dict, List, Optional


# Regime thresholds
BEARISH_THRESHOLD = 0.35   # m10 component below this = bearish
BULLISH_THRESHOLD = 0.65   # m10 component above this = bullish

# Strategy-regime affinity: which strategies work best in which regime
# Based on data analysis of 1378 scans
REGIME_STRATEGY_AFFINITY = {
    "BEARISH_MACRO": {
        # Proven performers in bearish macro (STRONG_DOWN trend)
        "cross_asset": 1.8,          # 61.9% WR
        "structural_break": 1.5,     # 58.2% WR
        "mtf_confluence": 1.5,       # 58.0% WR
        "orderbook_imbalance": 1.2,  # 54.8% WR
        "trade_flow": 1.1,           # 53.3% WR
        # Depressed in bearish macro
        "failed_breakout": 0.6,      # 42.9% WR
        "scalp_v2": 0.5,             # 43.0% WR
        "regime_switch": 0.7,        # 47.8% WR
    },
    "BULLISH_MACRO": {
        # Strategies that work in bullish conditions
        "orderbook_imbalance": 1.5,
        "funding_arb": 1.3,
        "trade_flow": 1.3,
        "mtf_confluence": 1.2,
        # Depressed in bullish macro
        "cross_asset": 0.7,
        "structural_break": 0.8,
    },
    "NEUTRAL_MACRO": {
        # Default weights — no adjustment
        "cross_asset": 1.0,
        "structural_break": 1.0,
        "mtf_confluence": 1.0,
        "orderbook_imbalance": 1.0,
        "trade_flow": 1.0,
        "funding_arb": 1.0,
        "failed_breakout": 1.0,
        "regime_switch": 1.0,
        "scalp_v2": 1.0,
    },
}


def classify_regime(m10_details: Dict) -> Dict:
    """
    Classify macro regime from m10 sub-component scores.
    
    Args:
        m10_details: dict from scan result m10.details
                     Contains: btc_trend, ethbtc_rel, btc_momentum, consensus
    
    Returns:
        {
            'regime': 'BEARISH_MACRO' | 'BULLISH_MACRO' | 'NEUTRAL_MACRO',
            'confidence': float (0-1),
            'components': dict,
            'reason': str,
        }
    """
    if not m10_details:
        return _neutral_regime("no m10 data")
    
    components = m10_details.get('m10_components', {})
    if not components:
        return _neutral_regime("no m10 components")
    
    btc_trend = components.get('btc_trend', 0.5)
    ethbtc_rel = components.get('ethbtc_rel', 0.5)
    btc_momentum = components.get('btc_momentum', 0.5)
    consensus = components.get('consensus', 0.5)
    
    # Count bearish and bullish signals
    bearish_count = sum(1 for v in [btc_trend, ethbtc_rel, btc_momentum] if v < BEARISH_THRESHOLD)
    bullish_count = sum(1 for v in [btc_trend, ethbtc_rel, btc_momentum] if v > BULLISH_THRESHOLD)
    
    # Regime classification
    if bearish_count >= 2:
        regime = "BEARISH_MACRO"
        confidence = min(bearish_count / 3.0, 1.0)
        reason = "BTC trend=%s, ETH/BTC=%s, momentum=%s — %d/3 bearish" % (
            _fmt(btc_trend), _fmt(ethbtc_rel), _fmt(btc_momentum), bearish_count)
    elif bullish_count >= 2:
        regime = "BULLISH_MACRO"
        confidence = min(bullish_count / 3.0, 1.0)
        reason = "BTC trend=%s, ETH/BTC=%s, momentum=%s — %d/3 bullish" % (
            _fmt(btc_trend), _fmt(ethbtc_rel), _fmt(btc_momentum), bullish_count)
    else:
        regime = "NEUTRAL_MACRO"
        confidence = 0.3
        reason = "Mixed signals: BTC trend=%s, ETH/BTC=%s, momentum=%s" % (
            _fmt(btc_trend), _fmt(ethbtc_rel), _fmt(btc_momentum))
    
    return {
        'regime': regime,
        'confidence': round(confidence, 2),
        'components': {
            'btc_trend': round(btc_trend, 3),
            'ethbtc_rel': round(ethbtc_rel, 3),
            'btc_momentum': round(btc_momentum, 3),
            'consensus': round(consensus, 3),
        },
        'reason': reason,
    }


def get_regime_weights(regime: str) -> Dict[str, float]:
    """Get strategy weight adjustments for a given regime."""
    return REGIME_STRATEGY_AFFINITY.get(regime, REGIME_STRATEGY_AFFINITY["NEUTRAL_MACRO"])


def apply_regime_weights(strategy_signals: List[Dict], m10_details: Dict) -> Dict:
    """
    Apply regime-based weight adjustments to strategy signals.
    
    Args:
        strategy_signals: list of signal dicts from multi_strategy.all_signals
        m10_details: dict from scan result m10.details
    
    Returns:
        {
            'regime': dict (from classify_regime),
            'adjusted_signals': list (signals with regime-adjusted conviction),
            'blocked': list (strategies blocked by regime),
            'boosted': list (strategies boosted by regime),
        }
    """
    regime_info = classify_regime(m10_details)
    regime = regime_info['regime']
    weights = get_regime_weights(regime)
    
    adjusted = []
    blocked = []
    boosted = []
    
    for sig in strategy_signals:
        strat = sig.get('strategy', '')
        original_conv = sig.get('conviction', 0)
        
        # Get regime weight for this strategy (default 1.0)
        regime_mult = weights.get(strat, 1.0)
        
        # Apply regime adjustment
        adjusted_conv = original_conv * regime_mult
        adjusted_conv = min(adjusted_conv, 1.0)  # cap at 1.0
        
        # Create adjusted signal copy
        adj_sig = dict(sig)
        adj_sig['original_conviction'] = original_conv
        adj_sig['regime_adjusted_conviction'] = round(adjusted_conv, 4)
        adj_sig['regime_multiplier'] = regime_mult
        adj_sig['conviction'] = round(adjusted_conv, 4)  # override for ensemble
        
        adjusted.append(adj_sig)
        
        if regime_mult < 0.8:
            blocked.append({'strategy': strat, 'multiplier': regime_mult, 'original': original_conv})
        elif regime_mult > 1.2:
            boosted.append({'strategy': strat, 'multiplier': regime_mult, 'original': original_conv})
    
    return {
        'regime': regime_info,
        'adjusted_signals': adjusted,
        'blocked': blocked,
        'boosted': boosted,
    }


def format_regime(regime_info: Dict) -> str:
    """Format regime info for report output."""
    if not regime_info:
        return "  Regime: UNKNOWN"
    regime = regime_info.get('regime', '?')
    conf = regime_info.get('confidence', 0)
    reason = regime_info.get('reason', '')
    comps = regime_info.get('components', {})
    
    lines = []
    lines.append("  Regime: %s (conf=%.2f)" % (regime, conf))
    lines.append("    %s" % reason)
    if comps:
        lines.append("    Components: btc_trend=%s ethbtc=%s momentum=%s consensus=%s" % (
            _fmt(comps.get('btc_trend',0)), _fmt(comps.get('ethbtc_rel',0)),
            _fmt(comps.get('btc_momentum',0)), _fmt(comps.get('consensus',0))))
    return chr(10).join(lines)


def _neutral_regime(reason):
    return {'regime': 'NEUTRAL_MACRO', 'confidence': 0.3, 'components': {}, 'reason': reason}

def _fmt(v):
    return "%.3f" % v
