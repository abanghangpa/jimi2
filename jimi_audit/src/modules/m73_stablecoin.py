"""M73: Stablecoin Mint Flows — on-chain liquidity signal from USDT/USDC mint/burn activity."""

import numpy as np
import json
import os

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'm73_supply_cache.json')


def _load_cache():
    """Load persistent supply cache from disk."""
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'usdt': None, 'usdc': None, 'total': None, 'timestamp': None}


def _save_cache(cache):
    """Save supply cache to disk."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception:
        pass


def fetch_stablecoin_mints():
    """Fetch stablecoin supply data from DeFiLlama (free, no key needed).

    Returns:
        dict with usdt_supply, usdc_supply, usdt_change_24h, usdc_change_24h
        or None if fetch fails
    """
    if not HAS_REQUESTS:
        return None
    try:
        # DeFiLlama stablecoins API
        r = requests.get("https://stablecoins.llama.fi/stablecoins?includePrices=true",
                         timeout=15, headers={'Accept': 'application/json'})
        r.raise_for_status()
        data = r.json()

        usdt_supply = 0
        usdc_supply = 0

        for coin in data.get('peggedAssets', []):
            symbol = coin.get('symbol', '').upper()
            if symbol == 'USDT':
                # Get total circulating
                chains = coin.get('chainCirculating', {})
                for chain_data in chains.values():
                    usdt_supply += chain_data.get('current', {}).get('peggedUSD', 0)
            elif symbol == 'USDC':
                chains = coin.get('chainCirculating', {})
                for chain_data in chains.values():
                    usdc_supply += chain_data.get('current', {}).get('peggedUSD', 0)

        return {
            'usdt_supply': usdt_supply,
            'usdc_supply': usdc_supply,
            'total_supply': usdt_supply + usdc_supply,
        }
    except Exception:
        return None


def score_m73_stablecoin(mint_data, direction, config=None):
    """Score stablecoin mint/burn activity.

    Large USDT/USDC mints signal institutional capital queuing to buy crypto.
    Often precedes major ETH pumps by 12-48h.

    Thresholds:
        > $1B single-day mint: MEGA_MINT -> bullish
        > $500M single-day mint: LARGE_MINT -> mildly bullish
        > $500M burn: LARGE_BURN -> mildly bearish

    Args:
        mint_data: dict from fetch_stablecoin_mints()
        direction: 'LONG' or 'SHORT'
        config: dict with M73_* keys

    Returns:
        (status, score, details)
    """
    import time

    cfg = config or {}

    if mint_data is None:
        return 'SKIP', 0.5, {'error': 'no stablecoin data'}

    large_mint = cfg.get('M73_LARGE_MINT_THRESH', 500_000_000)
    mega_mint = cfg.get('M73_MEGA_MINT_THRESH', 1_000_000_000)
    large_burn = cfg.get('M73_LARGE_BURN_THRESH', 500_000_000)

    current_supply = mint_data.get('total_supply', 0)
    now = time.time()

    # Load persistent cache (survives process restarts)
    _supply_cache = _load_cache()

    # Compute change from cached previous reading
    total_change = 0
    if _supply_cache.get('timestamp') is not None and _supply_cache.get('total') is not None:
        total_change = current_supply - _supply_cache['total']

    # Update cache and persist to disk
    _supply_cache['total'] = current_supply
    _supply_cache['timestamp'] = now
    _save_cache(_supply_cache)

    # Classification based on supply change
    if total_change > mega_mint:
        classification = 'MEGA_MINT'
        long_score = 0.62
    elif total_change > large_mint:
        classification = 'LARGE_MINT'
        long_score = 0.58
    elif total_change < -large_burn:
        classification = 'LARGE_BURN'
        long_score = 0.40
    else:
        classification = 'NORMAL'
        long_score = 0.50

    if direction == 'LONG':
        score = long_score
    elif direction == 'SHORT':
        score = 1.0 - long_score
    else:
        score = 0.5

    details = {
        'classification': classification,
        'usdt_supply': mint_data.get('usdt_supply', 0),
        'usdc_supply': mint_data.get('usdc_supply', 0),
        'total_supply': current_supply,
        'total_change': total_change,
    }

    status = 'PASS' if classification != 'NORMAL' else 'NEUTRAL'
    return status, score, details
