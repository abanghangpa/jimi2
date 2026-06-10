import yfinance as yf
import threading
import time
import sys
import os

# Add jimi_audit to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'jimi_audit')))

from src.modules.intrabar_cvd import get_intrabar_cvd_summary

def get_intrabar_cvd_summary_with_timeout(symbol, target_tf='15min', hours=48, timeout=10):
    """Wrapper for get_intrabar_cvd_summary with a timeout."""
    result = [None]
    exception = [None]

    def target():
        try:
            print(f"  [Thread] Starting get_intrabar_cvd_summary for {symbol}...")
            data, details = get_intrabar_cvd_summary(symbol=symbol, target_tf=target_tf, hours=hours)
            print(f"  [Thread] get_intrabar_cvd_summary finished.")
            result[0] = (data, details)
        except Exception as e:
            print(f"  [Thread] Exception in get_intrabar_cvd_summary: {e}")
            exception[0] = e

    thread = threading.Thread(target=target)
    thread.start()
    print(f"  [Main] Waiting {timeout}s for thread...")
    thread.join(timeout)

    if thread.is_alive():
        print(f"  [Main] TIMEOUT reached for {symbol}!")
        return None, ValueError(f"Timeout fetching intrabar CVD for {symbol}")
    if exception[0]:
        print(f"  [Main] Exception caught: {exception[0]}")
        return None, exception[0]
    
    return result[0], None

if __name__ == "__main__":
    print("Testing intrabar CVD fetcher with timeout...")
    # Test with a very short timeout to ensure it actually times out
    data, details = get_intrabar_cvd_summary_with_timeout(symbol='ETHUSDT', target_tf='1min', hours=1, timeout=2)
    if data is not None:
        print("Successfully fetched intrabar CVD data.")
    else:
        print(f"Failed to fetch intrabar CVD data: {details}")
    
    print("\nTesting with longer timeout...")
    data, details = get_intrabar_cvd_summary_with_timeout(symbol='ETHUSDT', target_tf='1min', hours=1, timeout=15)
    if data is not None:
        print("Successfully fetched intrabar CVD data.")
    else:
        print(f"Failed to fetch intrabar CVD data: {details}")
