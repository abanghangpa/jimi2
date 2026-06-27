"""
Order Flow & Liquidation Data Fetcher
Fetches real-time order book, recent trades, and liquidation data from exchanges.
"""
import time
import ccxt
import numpy as np

_cache = {}
CACHE_TTL = 30  # seconds


def _get_exchange(name='binance'):
    """Get ccxt exchange instance."""
    exchanges = {
        'binance': ccxt.binance,
        'okx': ccxt.okx,
        'bybit': ccxt.bybit,
    }
    cls = exchanges.get(name, ccxt.binance)
    return cls({'enableRateLimit': True})


def fetch_order_book_imbalance(symbol='ETH/USDT', exchange_name='binance', depth=20):
    """Fetch order book and calculate buy/sell imbalance.
    
    Returns:
        dict with bid_volume, ask_volume, imbalance_ratio, spread, etc.
    """
    cache_key = f'ob_{exchange_name}_{symbol}'
    if cache_key in _cache and time.time() - _cache[cache_key]['ts'] < CACHE_TTL:
        return _cache[cache_key]['data']
    
    try:
        ex = _get_exchange(exchange_name)
        ob = ex.fetch_order_book(symbol, limit=depth)
        
        bids = ob.get('bids', [])
        asks = ob.get('asks', [])
        
        if not bids or not asks:
            return None
        
        bid_vol = sum(b[1] for b in bids[:depth])
        ask_vol = sum(a[1] for a in asks[:depth])
        bid_price = bids[0][0]
        ask_price = asks[0][0]
        spread = (ask_price - bid_price) / bid_price * 100
        mid_price = (bid_price + ask_price) / 2
        
        # Imbalance ratio: >1 = more bids (bullish), <1 = more asks (bearish)
        imbalance = bid_vol / ask_vol if ask_vol > 0 else 1.0
        
        # Price impact: how much would a market order move the price?
        # Simulate $100k market buy and sell
        usd_depth = 100000
        buy_impact = 0
        remaining = usd_depth
        for price, vol in asks:
            vol_usd = price * vol
            if remaining <= 0:
                break
            consumed = min(remaining, vol_usd)
            buy_impact += consumed / usd_depth * ((price - mid_price) / mid_price * 100)
            remaining -= consumed
        
        sell_impact = 0
        remaining = usd_depth
        for price, vol in bids:
            vol_usd = price * vol
            if remaining <= 0:
                break
            consumed = min(remaining, vol_usd)
            sell_impact += consumed / usd_depth * ((mid_price - price) / mid_price * 100)
            remaining -= consumed
        
        # Wall detection: find large orders (>5x average)
        avg_bid = bid_vol / len(bids) if bids else 0
        avg_ask = ask_vol / len(asks) if asks else 0
        bid_walls = [{'price': b[0], 'size': b[1], 'ratio': b[1]/avg_bid} 
                     for b in bids[:depth] if b[1] > avg_bid * 5]
        ask_walls = [{'price': a[0], 'size': a[1], 'ratio': a[1]/avg_ask} 
                     for a in asks[:depth] if a[1] > avg_ask * 5]
        
        result = {
            'exchange': exchange_name,
            'symbol': symbol,
            'mid_price': mid_price,
            'bid_price': bid_price,
            'ask_price': ask_price,
            'spread': spread,
            'bid_volume': bid_vol,
            'ask_volume': ask_vol,
            'imbalance': round(imbalance, 4),
            'buy_impact': round(buy_impact, 4),
            'sell_impact': round(sell_impact, 4),
            'bid_walls': bid_walls[:5],
            'ask_walls': ask_walls[:5],
            'bid_wall_count': len(bid_walls),
            'ask_wall_count': len(ask_walls),
            'timestamp': time.time(),
        }
        
        _cache[cache_key] = {'ts': time.time(), 'data': result}
        return result
    except Exception as e:
        return None


def fetch_recent_trades(symbol='ETH/USDT', exchange_name='binance', limit=100):
    """Fetch recent trades and analyze buy/sell pressure.
    
    Returns:
        dict with buy_volume, sell_volume, net_flow, taker_ratio, etc.
    """
    cache_key = f'trades_{exchange_name}_{symbol}'
    if cache_key in _cache and time.time() - _cache[cache_key]['ts'] < CACHE_TTL:
        return _cache[cache_key]['data']
    
    try:
        ex = _get_exchange(exchange_name)
        trades = ex.fetch_trades(symbol, limit=limit)
        
        if not trades:
            return None
        
        buy_vol = 0
        sell_vol = 0
        buy_count = 0
        sell_count = 0
        large_trades = []
        
        for t in trades:
            vol = t.get('amount', 0) * t.get('price', 0)
            side = t.get('side', '')
            
            if side == 'buy':
                buy_vol += vol
                buy_count += 1
            else:
                sell_vol += vol
                sell_count += 1
            
            # Track large trades (>$50k)
            if vol > 50000:
                large_trades.append({
                    'side': side,
                    'price': t.get('price'),
                    'amount': t.get('amount'),
                    'usd': vol,
                    'timestamp': t.get('timestamp'),
                })
        
        total_vol = buy_vol + sell_vol
        taker_ratio = buy_vol / total_vol if total_vol > 0 else 0.5
        net_flow = buy_vol - sell_vol  # positive = net buying
        
        result = {
            'exchange': exchange_name,
            'symbol': symbol,
            'buy_volume': buy_vol,
            'sell_volume': sell_vol,
            'net_flow': net_flow,
            'taker_ratio': round(taker_ratio, 4),
            'buy_count': buy_count,
            'sell_count': sell_count,
            'large_trades': large_trades[:10],
            'large_buy_count': sum(1 for t in large_trades if t['side'] == 'buy'),
            'large_sell_count': sum(1 for t in large_trades if t['side'] == 'sell'),
            'timestamp': time.time(),
        }
        
        _cache[cache_key] = {'ts': time.time(), 'data': result}
        return result
    except Exception as e:
        return None


def fetch_funding_rates(symbol='ETH/USDT:USDT'):
    """Fetch funding rates from multiple exchanges.
    
    Returns:
        dict with funding rates, changes, and extremes.
    """
    cache_key = f'funding_{symbol}'
    if cache_key in _cache and time.time() - _cache[cache_key]['ts'] < 60:
        return _cache[cache_key]['data']
    
    rates = {}
    for ex_name in ['binance', 'okx', 'bybit']:
        try:
            ex = _get_exchange(ex_name)
            fr = ex.fetch_funding_rate(symbol)
            rates[ex_name] = {
                'rate': fr.get('fundingRate', 0),
                'next': fr.get('fundingDatetime'),
                'previous': fr.get('previousFundingRate'),
            }
        except:
            pass
    
    if not rates:
        return None
    
    avg_rate = np.mean([r['rate'] for r in rates.values()])
    max_rate = max(r['rate'] for r in rates.values())
    min_rate = min(r['rate'] for r in rates.values())
    
    result = {
        'rates': rates,
        'avg_rate': round(avg_rate, 6),
        'max_rate': round(max_rate, 6),
        'min_rate': round(min_rate, 6),
        'spread': round(max_rate - min_rate, 6),
        'extreme_positive': avg_rate > 0.001,
        'extreme_negative': avg_rate < -0.001,
        'timestamp': time.time(),
    }
    
    _cache[cache_key] = {'ts': time.time(), 'data': result}
    return result


def fetch_liquidations(symbol='ETHUSDT'):
    """Fetch recent liquidation data from Binance.
    
    Returns:
        dict with liquidation volume, direction, and extremes.
    """
    cache_key = f'liq_{symbol}'
    if cache_key in _cache and time.time() - _cache[cache_key]['ts'] < CACHE_TTL:
        return _cache[cache_key]['data']
    
    try:
        ex = ccxt.binance({'enableRateLimit': True})
        # Binance provides forced orders endpoint
        liqs = ex.fetch_liquidations(symbol, limit=100)
        
        if not liqs:
            return None
        
        long_liq_vol = 0
        short_liq_vol = 0
        for liq in liqs:
            vol = liq.get('amount', 0) * liq.get('price', 0)
            side = liq.get('side', '')
            if side == 'sell':  # long liquidation
                long_liq_vol += vol
            else:  # short liquidation
                short_liq_vol += vol
        
        total = long_liq_vol + short_liq_vol
        result = {
            'long_liq_volume': long_liq_vol,
            'short_liq_volume': short_liq_vol,
            'total_liq_volume': total,
            'long_liq_pct': long_liq_vol / total if total > 0 else 0.5,
            'short_liq_pct': short_liq_vol / total if total > 0 else 0.5,
            'liq_imbalance': (long_liq_vol - short_liq_vol) / total if total > 0 else 0,
            'timestamp': time.time(),
        }
        
        _cache[cache_key] = {'ts': time.time(), 'data': result}
        return result
    except:
        return None


def fetch_multi_exchange_ob(symbol='ETH/USDT', depth=20):
    """Fetch order book from multiple exchanges and aggregate.
    
    Returns:
        dict with aggregated imbalance, exchange-specific data.
    """
    results = {}
    for ex_name in ['binance', 'okx', 'bybit']:
        ob = fetch_order_book_imbalance(symbol, ex_name, depth)
        if ob:
            results[ex_name] = ob
    
    if not results:
        return None
    
    # Aggregate
    total_bid = sum(r['bid_volume'] for r in results.values())
    total_ask = sum(r['ask_volume'] for r in results.values())
    avg_imbalance = np.mean([r['imbalance'] for r in results.values()])
    
    # Find consensus direction
    bullish_ex = sum(1 for r in results.values() if r['imbalance'] > 1.1)
    bearish_ex = sum(1 for r in results.values() if r['imbalance'] < 0.9)
    
    return {
        'exchanges': results,
        'total_bid_volume': total_bid,
        'total_ask_volume': total_ask,
        'avg_imbalance': round(avg_imbalance, 4),
        'bullish_exchanges': bullish_ex,
        'bearish_exchanges': bearish_ex,
        'consensus': 'BULLISH' if bullish_ex >= 2 else ('BEARISH' if bearish_ex >= 2 else 'NEUTRAL'),
    }
