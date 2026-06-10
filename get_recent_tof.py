import requests
import sys
sys.path.insert(0, '/root/.openclaw/workspace/jimi_audit')
from src.modules.m75_tof import TOFState
from datetime import datetime, timezone

# Fetch recent 15m klines for ETHUSDT futures
url_klines = 'https://fapi.binance.com/fapi/v1/klines'
params = {
    'symbol': 'ETHUSDT',
    'interval': '15m',
    'limit': 100  # Get last 100 bars for warm-up
}
resp = requests.get(url_klines, params=params, timeout=10)
if resp.status_code != 200:
    print('Error fetching klines:', resp.status_code)
    exit(1)
klines = resp.json()

# We'll need OI and funding for each bar - fetch latest values and assume constant for simplicity
# In reality, these change per bar, but for demo we'll use latest
url_oi = 'https://fapi.binance.com/fapi/v1/openInterest'
params_oi = {'symbol': 'ETHUSDT'}
resp_oi = requests.get(url_oi, params=params_oi, timeout=10)
oi = float(resp_oi.json()['openInterest']) if resp_oi.status_code == 200 else 0.0

url_funding = 'https://fapi.binance.com/fapi/v1/fundingRate'
params_funding = {'symbol': 'ETHUSDT', 'limit': 1}
resp_funding = requests.get(url_funding, params=params_funding, timeout=10)
funding_rate = float(resp_funding.json()[0]['fundingRate']) if resp_funding.status_code == 200 else 0.0

# Process bars through TOF state
state = TOFState()
results = []
for i, kline in enumerate(klines):
    open_time = int(kline[0])
    open_price = float(kline[1])
    high_price = float(kline[2])
    low_price = float(kline[3])
    close_price = float(kline[4])
    volume = float(kline[5])
    taker_buy_base_asset_volume = float(kline[9])
    buy_vol = taker_buy_base_asset_volume
    sell_vol = volume - buy_vol
    
    bar = {
        'close': close_price,
        'high': high_price,
        'low': low_price,
        'volume': volume,
        'buy_vol': buy_vol,
        'sell_vol': sell_vol,
        'oi': oi,
        'funding': funding_rate,
    }
    res = state.push(bar)
    results.append((open_time, res))

# Get latest result
latest_time, latest_result = results[-1] if results else (None, None)

print('TOF Analysis for ETH/USDT 15m Futures')
print('=' * 50)
if latest_time:
    print('Latest bar time:', datetime.fromtimestamp(latest_time/1000, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
else:
    print('No bars processed')
    
if latest_result:
    print('TOF Score: {:.4f}'.format(latest_result['tof_score']))
    print('TOF Signal: {}'.format(latest_result['tof_signal']))
    print('Components:')
    for k, v in latest_result['tof_components'].items():
        print('  {}: {:.4f}'.format(k, v))
else:
    print('No result')

# Show if we have enough bars for warm-up
min_bars_needed = 20  # max of cvd_window(20), taker_window(8), oi_window(10), funding_window(3) + 5
print()
print('Warm-up status: {:d}/{:d} bars processed'.format(len(klines), min_bars_needed))
if len(klines) >= min_bars_needed:
    print('✓ Sufficient data for TOF calculation')
else:
    print('✗ Awaiting more bars for warm-up')
