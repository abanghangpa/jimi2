import requests
import json
from datetime import datetime, timezone

# Fetch latest 15m kline for ETHUSDT futures
url_klines = 'https://fapi.binance.com/fapi/v1/klines'
params = {
    'symbol': 'ETHUSDT',
    'interval': '15m',
    'limit': 1
}
resp = requests.get(url_klines, params=params, timeout=10)
if resp.status_code != 200:
    print('Error fetching klines:', resp.status_code)
    exit(1)
kline = resp.json()[0]
# kline format: [open_time, open, high, low, close, volume, close_time, quote_asset_volume, number_of_trades, taker_buy_base_asset_volume, taker_buy_quote_asset_volume, ignore]
open_time = int(kline[0])
open_price = float(kline[1])
high_price = float(kline[2])
low_price = float(kline[3])
close_price = float(kline[4])
volume = float(kline[5])  # base asset volume
close_time = int(kline[6])
taker_buy_base_asset_volume = float(kline[9])
taker_buy_quote_asset_volume = float(kline[10])
# taker sell volume = volume - taker_buy_base_asset_volume
buy_vol = taker_buy_base_asset_volume
sell_vol = volume - buy_vol

# Fetch open interest
url_oi = 'https://fapi.binance.com/fapi/v1/openInterest'
params = {'symbol': 'ETHUSDT'}
resp = requests.get(url_oi, params=params, timeout=10)
if resp.status_code != 200:
    print('Error fetching OI:', resp.status_code)
    print('Response text:', resp.text[:200])
    exit(1)
oi_data = resp.json()
oi = float(oi_data['openInterest'])  # in base asset (ETH)

# Fetch funding rate (last funding rate)
url_funding = 'https://fapi.binance.com/fapi/v1/fundingRate'
params = {'symbol': 'ETHUSDT', 'limit': 1}
resp = requests.get(url_funding, params=params, timeout=10)
if resp.status_code != 200:
    print('Error fetching funding rate:', resp.status_code)
    exit(1)
funding_data = resp.json()
funding_rate = float(funding_data[0]['fundingRate'])  # e.g., 0.0001 for 0.01%

# Prepare bar dict for TOF module
bar = {
    'close': close_price,
    'high': high_price,
    'low': low_price,
    'volume': volume,
    'buy_vol': buy_vol,
    'sell_vol': sell_vol,
    'oi': oi,
    'funding': funding_rate,
    # Note: the TOF module also expects 'volume' for default buy/sell vol calculation, but we provided buy_vol/sell_vol directly.
}

# Import and use the M75 TOF module
import sys
sys.path.insert(0, '/root/.openclaw/workspace/jimi_audit')
from src.modules.m75_tof import TOFState

state = TOFState()
result = state.push(bar)

print('Latest 15m bar (closed at):', datetime.fromtimestamp(close_time/1000, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
print('Close: ${:,.2f}'.format(close_price))
print('Volume (ETH): {:,.4f}'.format(volume))
print('Buy Vol (ETH): {:,.4f} ({:.1f}%)'.format(buy_vol, buy_vol/volume*100 if volume>0 else 0))
print('Sell Vol (ETH): {:,.4f} ({:.1f}%)'.format(sell_vol, sell_vol/volume*100 if volume>0 else 0))
print('Open Interest (ETH): {:,.2f}'.format(oi))
print('Funding Rate (per 8h): {:.6%}'.format(funding_rate))
print()
print('TOF Score: {:.4f}'.format(result['tof_score']))
print('TOF Signal: {}'.format(result['tof_signal']))
print('TOF Components:')
for k, v in result['tof_components'].items():
    print('  {}: {:.4f}'.format(k, v))
