import requests, time

DEPTH_LEVELS = 5
SWEEP_THRESH = 5.0  # ETH
TARGET_MOVE = 20.0  # USD

def get_binance_depth():
    r = requests.get('https://api.binance.com/api/v3/depth',
                     params={'symbol':'ETHUSDT','limit':100}, timeout=5)
    d = r.json()
    bids = [(float(p), float(q)) for p,q in d['bids']]
    asks = [(float(p), float(q)) for p,q in d['asks']]
    return bids, asks

def micro_price_and_obi(bids, asks, levels=DEPTH_LEVELS):
    bids_top = bids[:levels]
    asks_top = asks[:levels]
    bid_vol = sum(sz for _, sz in bids_top)
    ask_vol = sum(sz for _, sz in asks_top)
    if bid_vol + ask_vol == 0:
        return None, None
    # volume-weighted avg price of each side
    bid_vwap = sum(p*sz for p,sz in bids_top) / bid_vol if bid_vol else 0
    ask_vwap = sum(p*sz for p,sz in asks_top) / ask_vol if ask_vol else 0
    micro_price = (ask_vwap*bid_vol + bid_vwap*ask_vol) / (bid_vol + ask_vol)
    obi = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    return micro_price, obi

def fuel_volume(bids, asks, target_price):
    vol = 0.0
    for p,q in asks:
        if p > target_price + 1e-9:
            break
        vol += q
    return vol

def main():
    prev_ask_size = None
    prev_bid_size = None
    for i in range(6):  # run a few cycles
        bids, asks = get_binance_depth()
        if not bids or not asks:
            print("No data")
            time.sleep(2)
            continue
        bb, bq = bids[0]
        ba, aq = asks[0]
        mid = (bb + ba) / 2.0
        micro_price, obi = micro_price_and_obi(bids, asks)
        # sweep detection
        ask_sweep = False
        bid_sweep = False
        if prev_ask_size is not None:
            if prev_ask_size - aq > SWEEP_THRESH:
                ask_sweep = True
        if prev_bid_size is not None:
            if prev_bid_size - bq > SWEEP_THRESH:
                bid_sweep = True
        prev_ask_size = aq
        prev_bid_size = bq
        # fuel for +$20 move
        target_up = mid + TARGET_MOVE
        fuel_up = fuel_volume(bids, asks, target_up)
        target_down = mid - TARGET_MOVE
        fuel_down = sum(q for p,q in bids if p >= target_down - 1e-9)
        # signal logic (simple)
        signal = ""
        if obi > 0.15 and micro_price > mid:
            signal = "LONG bias"
        elif obi < -0.15 and micro_price < mid:
            signal = "SHORT bias"
        else:
            signal = "Neutral"
        print(f"[{time.strftime('%H:%M:%S')}] "
              f"Bid {bb:.2f}({bq:.2f}) Ask {ba:.2f}({aq:.2f}) "
              f"Mid {mid:.2f} Micro {micro_price if micro_price else 0:.2f} "
              f"OBI {obi if obi else 0:+.2f} "
              f"AskSweep {ask_sweep} BidSweep {bid_sweep} "
              f"Fuel+20={fuel_up:.1f}ETH Fuel-20={fuel_down:.1f}ETH "
              f"=> {signal}")
        time.sleep(2)

if __name__ == "__main__":
    main()
