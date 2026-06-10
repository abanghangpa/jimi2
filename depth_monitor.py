import requests
import time

def get_binance_depth():
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": "ETHUSDT", "limit": 100}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    bids = [(float(p), float(q)) for p, q in data['bids']]
    asks = [(float(p), float(q)) for p, q in data['asks']]
    return bids, asks

def get_kraken_ticker():
    url = "https://api.kraken.com/0/public/Ticker"
    params = {"pair": "ETHUSD"}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    # data['result']['XETHZUSD']
    for v in data['result'].values():
        bid = float(v['b'][0])
        ask = float(v['a'][0])
        return bid, ask
    return None, None

def get_coinbase_ticker():
    url = "https://api.pro.coinbase.com/products/ETH-USD/book"
    params = {"level": "1"}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    bid = float(data['bids'][0][0])
    ask = float(data['asks'][0][0])
    return bid, ask

def compute_fuel(bids, asks, target_move=20.0):
    # mid price from best bid/ask
    if not bids or not asks:
        return 0.0
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / 2.0
    target_ask = mid + target_move
    vol = 0.0
    for price, qty in asks:
        if price > target_ask:
            break
        vol += qty
    return vol, mid, best_bid, best_ask

def main():
    while True:
        try:
            binance_bids, binance_asks = get_binance_depth()
            kraken_bid, kraken_ask = get_kraken_ticker()
            coinbase_bid, coinbase_ask = get_coinbase_ticker()
            
            # Binance top
            if binance_bids and binance_asks:
                bb, bq = binance_bids[0]
                ba, aq = binance_asks[0]
                print(f"Binance: bid={bb:.2f} ({bq:.4f})  ask={ba:.2f} ({aq:.4f})")
                # compute fuel for $20 move
                vol, mid, bb2, ba2 = compute_fuel(binance_bids, binance_asks, 20.0)
                print(f"  Mid={mid:.2f}, to reach +$20 need ask volume up to {mid+20:.2f}: {vol:.2f} ETH")
            else:
                print("Binance: data unavailable")
            
            if kraken_bid and kraken_ask:
                print(f"Kraken:  bid={kraken_bid:.2f}  ask={kraken_ask:.2f}")
            else:
                print("Kraken:  data unavailable")
                
            if coinbase_bid and coinbase_ask:
                print(f"Coinbase:bid={coinbase_bid:.2f}  ask={coinbase_ask:.2f}")
            else:
                print("Coinbase:data unavailable")
            print("-"*50)
        except Exception as e:
            print("Error:", e)
        time.sleep(5)

if __name__ == "__main__":
    main()
