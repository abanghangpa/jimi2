#!/usr/bin/env python3
"""
Cross-Asset Backtest — validates S11 cross_asset strategy using ETH + BTC data.

Fetches BTC 15m OHLCV from Bybit, computes ETH/BTC ratio divergence,
runs the cross_asset strategy logic, and validates via isolation gate.

Usage:
    python3 backtest_cross_asset.py [--bars 5000]
"""

import os, sys, json, time
import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "cross_asset")
os.makedirs(DATA_DIR, exist_ok=True)

ETH_CSV = os.path.join(DATA_DIR, "eth_15m.csv")
BTC_CSV = os.path.join(DATA_DIR, "btc_15m.csv")
RESULTS_FILE = os.path.join(DATA_DIR, "cross_asset_backtest.json")


def fetch_bybit_klines(symbol="ETHUSDT", interval="15", limit=200):
    """Fetch klines from Bybit (free, no key)."""
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json().get("result", {}).get("list", [])
    # Bybit returns newest first, reverse to chronological
    data.reverse()
    return data


def fetch_all_klines(symbol="ETHUSDT", interval="15", total_bars=5000):
    """Fetch multiple pages of klines."""
    all_data = []
    end_ts = None
    remaining = total_bars

    while remaining > 0:
        batch = min(remaining, 200)
        params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": str(batch)}
        if end_ts:
            params["end"] = str(end_ts)

        try:
            r = requests.get("https://api.bybit.com/v5/market/kline", params=params, timeout=15)
            r.raise_for_status()
            data = r.json().get("result", {}).get("list", [])
        except Exception as e:
            print(f"  Fetch error: {e}")
            break

        if not data:
            break

        data.reverse()
        all_data = data + all_data
        end_ts = int(data[0][0]) - 1  # before earliest bar
        remaining -= len(data)

        if len(data) < batch:
            break

        time.sleep(0.2)  # rate limit

    return all_data


def klines_to_arrays(klines):
    """Convert Bybit klines to numpy arrays."""
    opens = np.array([float(k[1]) for k in klines])
    highs = np.array([float(k[2]) for k in klines])
    lows = np.array([float(k[3]) for k in klines])
    closes = np.array([float(k[4]) for k in klines])
    volumes = np.array([float(k[5]) for k in klines])
    timestamps = np.array([int(k[0]) for k in klines])
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes, "ts": timestamps}


def compute_cross_asset_scores(eth, btc, idx, lookback=96):
    """
    Compute cross-asset divergence scores.
    M10-like: ETH/BTC ratio divergence
    M7-like: momentum alignment
    Exchange-like: volume alignment
    """
    if idx < lookback:
        return None

    # ETH/BTC ratio
    ratio = eth["close"][idx] / btc["close"][idx] if btc["close"][idx] > 0 else 0
    ratio_window = eth["close"][idx-lookback:idx+1] / np.maximum(btc["close"][idx-lookback:idx+1], 1)
    ratio_mean = np.mean(ratio_window)
    ratio_std = np.std(ratio_window)
    if ratio_std < 0.0001:
        return None
    ratio_zscore = (ratio - ratio_mean) / ratio_std

    # ETH momentum vs BTC momentum (5-bar)
    eth_mom_5 = (eth["close"][idx] - eth["close"][idx-5]) / eth["close"][idx-5]
    btc_mom_5 = (btc["close"][idx] - btc["close"][idx-5]) / btc["close"][idx-5]
    mom_divergence = eth_mom_5 - btc_mom_5

    # Volume alignment
    eth_vol_ratio = eth["volume"][idx] / np.mean(eth["volume"][max(0,idx-20):idx+1])
    btc_vol_ratio = btc["volume"][idx] / np.mean(btc["volume"][max(0,idx-20):idx+1])

    # M10 score: ratio divergence (0-1 scale)
    # If ratio_zscore > 0.5, ETH is outperforming BTC → LONG ETH
    # If ratio_zscore < -0.5, ETH is underperforming → SHORT ETH
    m10_score = 0.5 + min(ratio_zscore / 4, 0.3)  # centered at 0.5
    m10_score = max(0.2, min(0.8, m10_score))

    # M7 score: momentum alignment
    if mom_divergence > 0:
        m7_score = 0.5 + min(mom_divergence * 10, 0.3)
    else:
        m7_score = 0.5 + max(mom_divergence * 10, -0.3)
    m7_score = max(0.2, min(0.8, m7_score))

    # Exchange score: volume alignment
    if eth_vol_ratio > 1.0 and btc_vol_ratio > 1.0:
        ex_score = 0.6  # both active
    elif eth_vol_ratio > 1.0 or btc_vol_ratio > 1.0:
        ex_score = 0.5  # one active
    else:
        ex_score = 0.4  # both quiet

    return {
        "m10_score": float(m10_score),
        "m7_score": float(m7_score),
        "ex_score": float(ex_score),
        "ratio_zscore": float(ratio_zscore),
        "mom_divergence": float(mom_divergence),
        "eth_vol_ratio": float(eth_vol_ratio),
        "btc_vol_ratio": float(btc_vol_ratio),
    }


def run_cross_asset_signal(scores, price, atr):
    """
    Run cross_asset strategy logic on computed scores.
    Returns signal dict or None.
    """
    if not scores:
        return None

    m10 = scores["m10_score"]
    m7 = scores["m7_score"]
    ex = scores["ex_score"]

    # Check both directions
    long_alignment = (m10 + m7 + ex) / 3
    short_alignment = (1 - m10 + 1 - m7 + 1 - ex) / 3

    if long_alignment >= short_alignment and long_alignment >= 0.55:
        direction = 'LONG'
        alignment = long_alignment
    elif short_alignment > long_alignment and short_alignment >= 0.55:
        direction = 'SHORT'
        alignment = short_alignment
    else:
        return None

    conviction = min(alignment * 0.8 + 0.1, 0.80)
    if conviction < 0.50:
        return None

    # TP/SL
    if direction == 'LONG':
        tp1 = price + 1.5 * atr
        sl = price - 1.0 * atr
    else:
        tp1 = price - 1.5 * atr
        sl = price + 1.0 * atr

    return {
        "direction": direction,
        "conviction": conviction,
        "entry": price,
        "tp1": tp1,
        "sl": sl,
        "alignment": alignment,
        "m10": m10, "m7": m7, "ex": ex,
    }


def compute_forward_returns(eth, idx, horizons=[1, 4, 16, 24]):
    """Compute forward returns at fixed horizons."""
    returns = {}
    for h in horizons:
        if idx + h < len(eth["close"]):
            ret = (eth["close"][idx + h] - eth["close"][idx]) / eth["close"][idx] * 100
            returns[f"ret_{h}bar"] = float(ret)
        else:
            returns[f"ret_{h}bar"] = None
    return returns


def isolation_gate(signals):
    """
    Run isolation gate on signals.
    Split on direction, compute forward returns, t-test.
    """
    from scipy import stats

    long_rets = []
    short_rets = []

    for sig in signals:
        if sig["signal"] is None:
            continue
        direction = sig["signal"]["direction"]
        ret_4 = sig["forward_returns"].get("ret_4bar")
        if ret_4 is None:
            continue

        if direction == "LONG":
            long_rets.append(ret_4)
        else:
            short_rets.append(-ret_4)  # flip for short

    if not long_rets and not short_rets:
        return {"passed": False, "reason": "no signals"}

    # Combine: all returns should be positive if strategy works
    all_rets = long_rets + short_rets

    if len(all_rets) < 20:
        return {"passed": False, "reason": f"too few signals ({len(all_rets)})"}

    mean_ret = float(np.mean(all_rets))
    std_ret = float(np.std(all_rets))
    n = len(all_rets)

    # t-test: is mean significantly different from 0?
    t_stat, p_value = stats.ttest_1samp(all_rets, 0)

    # Direction check
    direction_correct = mean_ret > 0

    # Effect size check (must exceed round-trip costs ~0.10%)
    effect_size_ok = abs(mean_ret) > 0.10

    passed = p_value < 0.1 and direction_correct and effect_size_ok

    return {
        "passed": passed,
        "events": n,
        "mean_return_pct": round(mean_ret, 4),
        "std_return_pct": round(std_ret, 4),
        "p_value": round(float(p_value), 6),
        "t_stat": round(float(t_stat), 4),
        "direction_correct": direction_correct,
        "effect_size_ok": effect_size_ok,
        "long_signals": len(long_rets),
        "short_signals": len(short_rets),
        "long_mean": round(float(np.mean(long_rets)), 4) if long_rets else 0,
        "short_mean": round(float(np.mean(short_rets)), 4) if short_rets else 0,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=5000)
    args = parser.parse_args()

    print(f"=== Cross-Asset Backtest ({args.bars} bars) ===")

    # Fetch ETH data
    print("\nFetching ETH 15m data...")
    eth_klines = fetch_all_klines("ETHUSDT", "15", args.bars)
    eth = klines_to_arrays(eth_klines)
    print(f"  ETH: {len(eth['close'])} bars, ${eth['close'][-1]:.2f}")

    # Fetch BTC data
    print("Fetching BTC 15m data...")
    btc_klines = fetch_all_klines("BTCUSDT", "15", args.bars)
    btc = klines_to_arrays(btc_klines)
    print(f"  BTC: {len(btc['close'])} bars, ${btc['close'][-1]:.2f}")

    # Align lengths
    min_len = min(len(eth["close"]), len(btc["close"]))
    for key in eth:
        eth[key] = eth[key][-min_len:]
    for key in btc:
        btc[key] = btc[key][-min_len:]
    print(f"  Aligned: {min_len} bars")

    # Save data
    np.savez(os.path.join(DATA_DIR, "eth_btc_aligned.npz"), eth=eth, btc=btc)
    print(f"  Saved to {DATA_DIR}/eth_btc_aligned.npz")

    # Run strategy
    print("\nRunning cross_asset strategy...")
    signals = []
    atr_period = 14
    lookback = 96

    for idx in range(lookback, min_len - 24):  # leave room for forward returns
        # Compute ATR
        highs = eth["high"][max(0,idx-atr_period):idx+1]
        lows = eth["low"][max(0,idx-atr_period):idx+1]
        closes = eth["close"][max(0,idx-atr_period):idx+1]
        tr = np.maximum(highs[1:] - lows[1:],
                       np.maximum(np.abs(highs[1:] - closes[:-1]),
                                 np.abs(lows[1:] - closes[:-1])))
        atr = float(np.mean(tr)) if len(tr) > 0 else 0
        price = float(eth["close"][idx])

        if atr <= 0 or price <= 0:
            continue

        # Compute scores
        scores = compute_cross_asset_scores(eth, btc, idx, lookback)

        # Run strategy
        signal = run_cross_asset_signal(scores, price, atr)

        # Compute forward returns
        fwd = compute_forward_returns(eth, idx)

        signals.append({
            "idx": idx,
            "price": price,
            "atr": atr,
            "signal": signal,
            "scores": scores,
            "forward_returns": fwd,
        })

    print(f"  Total bars analyzed: {len(signals)}")

    # Count signals
    fired = [s for s in signals if s["signal"] is not None]
    print(f"  Signals fired: {len(fired)}")

    if fired:
        longs = [s for s in fired if s["signal"]["direction"] == "LONG"]
        shorts = [s for s in fired if s["signal"]["direction"] == "SHORT"]
        print(f"  LONG: {len(longs)}, SHORT: {len(shorts)}")
        avg_conv = np.mean([s["signal"]["conviction"] for s in fired])
        print(f"  Avg conviction: {avg_conv:.3f}")

    # Run isolation gate
    print("\n=== Isolation Gate ===")
    gate = isolation_gate(signals)
    print(f"  Passed: {gate['passed']}")
    print(f"  Events: {gate.get('events', 0)}")
    print(f"  Mean return: {gate.get('mean_return_pct', 0):.4f}%")
    print(f"  p-value: {gate.get('p_value', 1):.6f}")
    print(f"  Direction correct: {gate.get('direction_correct', False)}")
    print(f"  Effect size OK: {gate.get('effect_size_ok', False)}")
    print(f"  Long signals: {gate.get('long_signals', 0)} (mean: {gate.get('long_mean', 0):.4f}%)")
    print(f"  Short signals: {gate.get('short_signals', 0)} (mean: {gate.get('short_mean', 0):.4f}%)")

    # Save results
    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bars_analyzed": len(signals),
        "signals_fired": len(fired),
        "gate": gate,
        "config": {
            "alignment_threshold": 0.55,
            "conviction_min": 0.50,
            "tp_mult": 1.5,
            "sl_mult": 1.0,
            "lookback": lookback,
        },
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {RESULTS_FILE}")

    # Print sample signals
    if fired:
        print("\n=== Sample Signals (last 5) ===")
        for s in fired[-5:]:
            sig = s["signal"]
            fwd = s["forward_returns"]
            print(f"  {sig['direction']} @ ${s['price']:.2f} "
                  f"conv={sig['conviction']:.2f} "
                  f"M10={sig['m10']:.2f} M7={sig['m7']:.2f} EX={sig['ex']:.2f} "
                  f"→ 4bar={fwd.get('ret_4bar', 'N/A'):.3f}%" if fwd.get('ret_4bar') is not None else "")


if __name__ == "__main__":
    main()
