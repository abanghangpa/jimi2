from topbid.orderbook import OrderBook
import time
ob = OrderBook()
ob.add("binance", "ETH/USDT")
ob.start(update_every=2)
time.sleep(2)
print("Binance bid:", ob.get_orderbook_top_bid("binance", "ETH/USDT"))
print("Binance ask:", ob.get_orderbook_top_ask("binance", "ETH/USDT"))
ob.stop()
