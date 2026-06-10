"""Mxx: USDT Dominance — risk-on/risk-off gauge for ETH-specific confidence adjustment."""

import numpy as np

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def fetch_usdt_dominance():
    """Fetch USDT dominance from CoinGecko API (free, no key needed).

    Returns:
        float: USDT dominance percentage (USDT market cap / total crypto market cap * 100),
               or None if fetch fails
    """
    if not HAS_REQUESTS:
        return None
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global",
                         timeout=10, headers={'Accept': 'application/json'})
        r.raise_for_status()
        data = r.json()
        usdt_dominance = data['data']['market_cap_percentage']['usdt']
        return float(usdt_dominance)
    except Exception:
        return None


def score_mxx_usdt_d(usdt_dominance, direction, config=None):
    """Score USDT dominance regime for ETH-specific adjustment.

    USDT.D rising = capital flowing into stablecoins = risk-off sentiment.
    USDT.D falling = capital flowing out of stablecoins = risk-on sentiment.

    For ETH:
        - Risk-off (USDT.D rising) = bearish ETH pressure
        - Risk-on (USDT.D falling) = bullish ETH support

    Thresholds (can be tuned):
        > 4.0%: HIGH_USDT_D (strong risk-off) — reduce ETH long confidence by 25%
        < 2.5%: LOW_USDT_D (strong risk-on) — amplify ETH long confidence by 20%
        2.5-4.0%: NEUTRAL_USDT_D

    Args:
        usdt_dominance: float, USDT dominance percentage
        direction: 'LONG' or 'SHORT'
        config: dict with Mxx_USDT_D_* keys

    Returns:
        (status, score, details)
    """
    cfg = config or {}

    if usdt_dominance is None:
        return 'SKIP', 0.5, {'error': 'no USDT.D data'}

    high_thresh = cfg.get('MXX_USDT_D_HIGH_THRESH', 4.0)
    low_thresh = cfg.get('MXX_USDT_D_LOW_THRESH', 2.5)

    if usdt_dominance > high_thresh:
        classification = 'HIGH_USDT_D'  # Risk-off
        long_score = 0.35  # ETH underperforms in risk-off
    elif usdt_dominance < low_thresh:
        classification = 'LOW_USDT_D'   # Risk-on
        long_score = 0.60   # ETH outperforms in risk-on
    else:
        classification = 'NEUTRAL_USDT_D'
        long_score = 0.50

    if direction == 'LONG':
        score = long_score
    elif direction == 'SHORT':
        score = 1.0 - long_score
    else:
        score = 0.5

    details = {
        'classification': classification,
        'usdt_dominance': round(usdt_dominance, 4),
    }

    status = 'PASS' if classification != 'NEUTRAL_USDT_D' else 'NEUTRAL'
    return status, score, details