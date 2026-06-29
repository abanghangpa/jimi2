
"""
M20 Filter — repurposes failed breakout data for signal quality.

Instead of using M20 as a directional signal (anti-predictive at 46% WR),
use its data for:
  1. Level export: breakout levels as S/R (60.1% WR near support)
  2. Staleness filter: signals near stale M20 levels get blocked
  3. Contrarian blocker: signals matching M20 contrarian direction get blocked (46% WR)

Data proof from 1386 scans:
  - M20 contrarian direction: 46-47% WR (anti-predictive)
  - Price near M20 support level: 60.1% WR (n=263)
  - Very stale M20 (>20 bars): 49.8% WR (degraded)
  - Signal matches M20 contrarian: 46.2% WR (toxic)
"""


def apply_m20_filter(m20_data, signal_direction, signal_price):
    """
    Apply M20-based quality filters to a signal.
    
    Args:
        m20_data: dict from scan result m20 field
        signal_direction: 'LONG' or 'SHORT'
        signal_price: current price
    
    Returns:
        {
            'blocked': bool,
            'reason': str,
            'level': float or None,  # M20 breakout level (for entry optimization)
            'level_type': str,       # 'support' | 'resistance' | 'none'
            'staleness': str,        # 'fresh' | 'stale' | 'very_stale'
            'quality': str,          # 'high' | 'mid' | 'low'
        }
    """
    result = {
        'blocked': False,
        'reason': '',
        'level': None,
        'level_type': 'none',
        'staleness': 'unknown',
        'quality': 'unknown',
    }
    
    if not m20_data or m20_data.get('status') != 'PASS':
        return result
    
    contra = m20_data.get('contrarian_direction', '')
    breakout_dir = m20_data.get('breakout_direction', '')
    level = m20_data.get('level', 0)
    quality = m20_data.get('breakout_quality', 0)
    failure = m20_data.get('failure', {})
    bars_since = failure.get('bars_since', 0) if failure else 0
    
    # 1. Export level for entry optimization
    if level and level > 0:
        result['level'] = float(level)
        if breakout_dir == 'DOWNSIDE' and signal_price > level:
            result['level_type'] = 'support'
        elif breakout_dir == 'UPSIDE' and signal_price < level:
            result['level_type'] = 'resistance'
    
    # 2. Staleness classification
    if bars_since <= 8:
        result['staleness'] = 'fresh'
    elif bars_since <= 20:
        result['staleness'] = 'stale'
    else:
        result['staleness'] = 'very_stale'
    
    # 3. Quality classification
    if quality >= 0.7:
        result['quality'] = 'high'
    elif quality >= 0.4:
        result['quality'] = 'mid'
    else:
        result['quality'] = 'low'
    
    # 4. Contrarian direction block
    # Data proof: signals matching M20 contrarian = 46% WR (toxic)
    if contra and signal_direction == contra:
        result['blocked'] = True
        result['reason'] = 'M20 contrarian block: signal matches M20 contrarian %s (%.1f%% WR expected)' % (
            contra, 46.0)
        return result
    
    # 5. Very stale block
    # Data proof: very stale M20 signals (>20 bars) = 49.8% WR
    if result['staleness'] == 'very_stale':
        result['blocked'] = True
        result['reason'] = 'M20 stale block: breakout failure is %d bars old (very stale)' % bars_since
        return result
    
    return result


def format_m20_filter(filter_result):
    """Format M20 filter result for report output."""
    if not filter_result.get('blocked'):
        level = filter_result.get('level')
        ltype = filter_result.get('level_type', 'none')
        if level and ltype != 'none':
            return "  M20 level: $%.2f (%s) | quality=%s | freshness=%s" % (
                level, ltype, filter_result.get('quality','?'), filter_result.get('staleness','?'))
        return ""
    
    return "  !! M20 BLOCKED: %s" % filter_result.get('reason', '')
