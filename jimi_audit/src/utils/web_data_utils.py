import yfinance as yf
import threading
import time
import pandas as pd

# TEMPORARY MOCK to prevent yfinance hangs during debugging
def mocked_download(*args, **kwargs):
    print("  ⚠️  [DEBUG] yfinance download mocked to prevent hang")
    return pd.DataFrame()

yf.download = mocked_download

def fetch_tradfi_data():
    """Fetch current TradFi macro indicators using yfinance.
    
    Returns a dict with current prices for DXY, 10Y Yield, VIX, Gold, and WTI.
    """
    tickers = {
        "dxy": "DX-Y.NYB",
        "10y_yield": "^TNX",
        "vix": "^VIX",
        "gold": "GC=F",
        "wti": "CL=F"
    }
    
    results = {}
    try:
        # Fetch all in one go to be efficient
        data = yf.download(list(tickers.values()), period="1d", interval="1m", progress=False)
        
        # yfinance returns a MultiIndex if multiple tickers are requested
        if isinstance(data.columns, pd.MultiIndex):
            for key, ticker in tickers.items():
                if ticker in data['Close']:
                    # Get the last valid close price
                    series = data['Close'][ticker].dropna()
                    if not series.empty:
                        results[key] = float(series.iloc[-1])
        else:
            # Single ticker case (shouldn't happen here but for robustness)
            # This part is actually not needed given the current list
            pass
            
    except Exception as e:
        print(f"  ⚠️  Error fetching TradFi data via yfinance: {e}")
        
    return results

def search_web(query):
    """Placeholder for web search utility. 
    Currently unused by the scanner.
    """
    print(f"  🔍 Web search requested for: {query} (Not implemented)")
    return []

def get_intrabar_cvd_summary_with_timeout(symbol, target_tf='15min', hours=48, timeout=10):
    """Wrapper for get_intrabar_cvd_summary with a timeout."""
    result = [None]
    exception = [None]

    def target():
        try:
            from src.modules.intrabar_cvd import get_intrabar_cvd_summary
            data, details = get_intrabar_cvd_summary(symbol=symbol, target_tf=target_tf, hours=hours)
            result[0] = (data, details)
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        return None, ValueError(f"Timeout fetching intrabar CVD for {symbol}")
    if exception[0]:
        return None, exception[0]
    
    return result[0], None
