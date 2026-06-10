import pandas as pd
import numpy as np
from jimi_audit.src.modules.m75_tof import score_mxx_usdt_d

def test_tof():
    print("Testing TOF module with synthetic data...")
    
    # Create 120 bars of synthetic data
    data = {
        'close': np.linspace(2000, 2100, 120),
        'high': np.linspace(2010, 2110, 120),
        'low': np.linspace(1990, 2090, 120),
        'volume': np.random.uniform(100, 1000, 120),
        'buy_vol': np.random.uniform(600, 900, 120), # Bullish taker
        'sell_vol': np.random.uniform(100, 400, 120),
        'oi': np.linspace(50000, 60000, 120),
        'funding': np.random.uniform(-0.0001, 0.0001, 120),
    }
    df = pd.DataFrame(data)
    
    try:
        result = score_mxx_usdt_d(df=df)
        print("Result:", result)
        print("SUCCESS: TOF module returned a result.")
    except Exception as e:
        print("FAILED: TOF module raised an exception:", e)

if __name__ == "__main__":
    test_tof()
