import sys
sys.path.insert(0, '.')
from src.utils.data_handler import fetch_recent, resample_ohlcv
from src.config import CONFIG
print('Fetching recent 15m data...')
df = fetch_recent(bars=100, timeframe='15m')
print('DF shape:', df.shape)
print('DF head:')
print(df.head())
print('DF columns:', df.columns.tolist())
if df is not None and len(df) > 0:
    print('Computing indicators...')
    df_15m, df_1h, df_2h, df_4h, df_1d = __import__('scripts.scanner').compute_indicators(df, config=CONFIG)
    print('Done')
else:
    print('No data')
