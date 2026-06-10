from topbid.orderbook import OrderBook
import time

ob = OrderBook()
ob.add("binance", "ETH/USDT")
ob.add("kraken",  "ETH/USD")
ob.add("coinbase","ETH/USD")
ob.start(update_every=2)

def get_top(ex, pair):
    for _ in range(10):  # try up to 10 times
        bid = ob.get_orderbook_top_bid(ex, pair)
        ask = ob.get_orderbook_top_ask(ex, pair)
        if bid is not None and ask is not None:
            return bid, ask
        time.sleep(0.5)
    return None, None

try:
    for i in range(5):
        for ex in ["binance","kraken","coinbase"]:
            pair = "ETH/USDT" if ex != "kraken" else "ETH/USD"
            bid_ask = get_top(ex, pair)
            if bid_ask[0] is None:
                print(f"{ex:10}  data not ready")
                continue
            (bid, bsize), (ask, asize) = bid_ask
            print(f"{ex:10}  bid={bid:>8.2f} ({bsize:>6.4f})  ask={ask:>8.2f} ({asize:>6.4f})")
        print("-"*40)
        time.sleep(1)
finally:
    ob.stop()
