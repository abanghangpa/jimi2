import sys
sys.path.insert(0, '.')
from scripts.scanner import compute_indicators
from src.utils.data_handler import fetch_recent
print('Fetching data...')
df = fetch_recent(bars=100, timeframe='15m')
print('DF shape:', df.shape)
if df is not None and len(df) > 0:
    print('Computing indicators...')
    df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df, config=None)
    print('DF_15M shape:', df_15m.shape)
    print('Columns:', df_15m.columns.tolist())
else:
    print('No data')
