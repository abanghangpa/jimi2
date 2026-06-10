import yfinance as yf
import threading
import time

def fetch_with_timeout(ticker_symbol, timeout=10):
    """Helper to fetch yfinance data with a strict timeout."""
    result = [None]
    exception = [None]

    def target():
        try:
            print(f"  Fetching {ticker_symbol}...")
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="1d")
            print(f"  Got history for {ticker_symbol}, shape: {hist.shape}")
            if not hist.empty:
                result[0] = hist["Close"].iloc[-1]
                print(f"  Successfully fetched {ticker_symbol}: {result[0]}")
            else:
                exception[0] = ValueError(f"No data found for {ticker_symbol}")
                print(f"  No data for {ticker_symbol}")
        except Exception as e:
            exception[0] = e
            print(f"  Exception for {ticker_symbol}: {e}")

    thread = threading.Thread(target=target)
    thread.start()
    print(f"  Started thread for {ticker_symbol}, waiting {timeout}s...")
    thread.join(timeout)
    print(f"  Join completed for {ticker_symbol}, thread alive: {thread.is_alive()}")
    
    if thread.is_alive():
        print(f"  TIMEOUT for {ticker_symbol}")
        return None, ValueError(f"Timeout fetching {ticker_symbol}")
    if exception[0]:
        print(f"  Exception caught for {ticker_symbol}: {exception[0]}")
        return None, exception[0]
    print(f"  Returning result for {ticker_symbol}: {result[0]}")
    return result[0], None

# Test with a problematic symbol
print("Testing DX-Y.NYB...")
val, err = fetch_with_timeout("DX-Y.NYB", timeout=5)
print(f"Result: val={val}, err={err}")
print(f"Active thread count: {threading.active_count()}")
time.sleep(2)  # Give time to see if threads linger
print(f"Active thread count after wait: {threading.active_count()}")