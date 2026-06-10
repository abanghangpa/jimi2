import yfinance as yf
import threading
import time

def fetch_with_timeout(ticker_symbol, timeout=10):
    """Helper to fetch yfinance data with a strict timeout."""
    result = [None]
    exception = [None]

    def target():
        try:
            # print(f"  Fetching {ticker_symbol}...")
            ticker = yf.Ticker(ticker_symbol)
            # Use short period to speed up, we only need the latest data point
            hist = ticker.history(period="1d", interval="1m")
            # print(f"  Got history for {ticker_symbol}, shape: {hist.shape}")
            if not hist.empty:
                result[0] = hist["Close"].iloc[-1]
                # print(f"  Successfully fetched {ticker_symbol}: {result[0]}")
            else:
                exception[0] = ValueError(f"No data found for {ticker_symbol}")
                # print(f"  No data for {ticker_symbol}")
        except Exception as e:
            exception[0] = e
            # print(f"  Exception for {ticker_symbol}: {e}")

    thread = threading.Thread(target=target)
    thread.start()
    # print(f"  Started thread for {ticker_symbol}, waiting {timeout}s...")
    thread.join(timeout)
    # print(f"  Join completed for {ticker_symbol}, thread alive: {thread.is_alive()}")
    
    if thread.is_alive():
        # print(f"  TIMEOUT for {ticker_symbol}")
        return None, ValueError(f"Timeout fetching {ticker_symbol}")
    if exception[0]:
        # print(f"  Exception caught for {ticker_symbol}: {exception[0]}")
        return None, exception[0]
    # print(f"  Returning result for {ticker_symbol}: {result[0]}")
    return result[0], None

def get_intrabar_cvd_summary_with_timeout(symbol, target_tf='15min', hours=48, timeout=10):
    """Wrapper for get_intrabar_cvd_summary with a timeout."""
    result = [None]
    exception = [None]

    def target():
        try:
            # Make sure to import the original function correctly
            from src.modules.intrabar_cvd import get_intrabar_cvd_summary
            data, details = get_intrabar_cvd_summary(symbol=symbol, target_tf=target_tf, hours=hours)
            result[0] = (data, details)
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        # print(f"  TIMEOUT for get_intrabar_cvd_summary")
        return None, ValueError(f"Timeout fetching intrabar CVD for {symbol}")
    if exception[0]:
        # print(f"  Exception for get_intrabar_cvd_summary: {exception[0]}")
        return None, exception[0]
    
    return result[0], None

# Test the intrabar CVD fetcher
if __name__ == "__main__":
    print("Testing intrabar CVD fetcher with timeout...")
    data, details = get_intrabar_cvd_summary_with_timeout(symbol='ETHUSDT', target_tf='1min', hours=1, timeout=5)
    if data is not None:
        print("Successfully fetched intrabar CVD data.")
        # print("Data:", data.head())
        # print("Details:", details)
    else:
        print("Failed to fetch intrabar CVD data:", details)
    
    print("\nTesting yfinance fetcher with timeout...")
    val, err = fetch_with_timeout("DX-Y.NYB", timeout=5)
    print(f"yfinance result: val={val}, err={err}")
