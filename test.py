from topbid.orderbook import OrderBook
ob = OrderBook()
# try different formats
formats = ["ETH/USDT", "ETH-USDT", "ETHUSDT"]
for f in formats:
    ob.add("binance", f)
ob.start(update_every=2)
import time; time.sleep(3)
for f in formats:
    bid = ob.get_orderbook_top_bid("binance", f)
    ask = ob.get_orderbook_top_ask("binance", f)
    print(f"Format {f}: bid={bid}, ask={ask}")
ob.stop()
