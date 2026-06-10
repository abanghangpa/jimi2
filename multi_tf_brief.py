#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jimi_audit'))

from src.utils.data_handler import fetch_recent, resample_ohlcv
from src.utils.indicators import (
    calc_ema, calc_macd, calc_rsi, calc_atr, calc_vwap, calc_vol_ratio,
    calc_swing_bias, calc_phase0, calc_trend_state, compute_btc_correlation,
)
import pandas as pd
import numpy as np

def analyze_timeframe(df_ohlcv, tf_name):
    # Ensure we have enough data
    if len(df_ohlcv) < 50:
        return {"error": f"Not enough data for {tf_name}"}
    close = df_ohlcv['Close']
    # Calculate indicators
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    rsi = calc_rsi(close, 14)
    macd_line, macd_signal, macd_hist = calc_macd(close)
    # Determine bias
    bullish_ema = ema20.iloc[-1] > ema50.iloc[-1]
    bullish_rsi = rsi.iloc[-1] > 50
    bullish_macd = macd_hist.iloc[-1] > 0
    # Simple score
    score = sum([bullish_ema, bullish_rsi, bullish_macd])
    if score >= 2:
        bias = "BULLISH"
    elif score <= 1:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    latest = df_ohlcv.iloc[-1]
    return {
        "timeframe": tf_name,
        "close": round(latest['Close'], 2),
        "ema20": round(ema20.iloc[-1], 2),
        "ema50": round(ema50.iloc[-1], 2),
        "rsi": round(rsi.iloc[-1], 2),
        "macd_hist": round(macd_hist.iloc[-1], 4),
        "bias": bias,
        "score": score
    }

def main():
    symbol = 'ETH/USDT'
    # Fetch 15m data ~1000 bars (~10 days)
    df_15m = fetch_recent(symbol=symbol, timeframe='15m', bars=1000)
    if df_15m.empty:
        print("Failed to fetch data")
        return
    # Resample
    df_1h = resample_ohlcv(df_15m, '1H')
    df_4h = resample_ohlcv(df_15m, '4H')
    results = []
    results.append(analyze_timeframe(df_15m, '15m'))
    results.append(analyze_timeframe(df_1h, '1h'))
    results.append(analyze_timeframe(df_4h, '4h'))
    # Print table
    print("\nMulti-Timeframe Bias Analysis (ETH/USDT)")
    print("-" * 70)
    print(f"{'TF':<5} {'Close':<8} {'EMA20':<8} {'EMA50':<8} {'RSI':<5} {'MACDh':<8} {'Bias':<8} {'Score'}")
    print("-" * 70)
    for r in results:
        if 'error' in r:
            print(r['error'])
            continue
        print(f"{r['timeframe']:<5} {r['close']:<8} {r['ema20']:<8} {r['ema50']:<8} {r['rsi']:<5} {r['macd_hist']:<8} {r['bias']:<8} {r['score']}")
    print("-" * 70)
    # Overall suggestion: if all timeframes agree bias
    biases = [r['bias'] for r in results if 'error' not in r]
    if all(b == 'BULLISH' for b in biases):
        print("Overall: STRONG BULLISH CONSENSUS")
    elif all(b == 'BEARISH' for b in biases):
        print("Overall: STRONG BEARISH CONSENSUS")
    else:
        print("Overall: MIXED OR NEUTRAL - WAIT FOR CONFIRMATION")
    print("\nNote: This is a simplified indicator-based bias, not the full JIMI ICS.")

if __name__ == '__main__':
    main()