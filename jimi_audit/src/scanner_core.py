import os
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from src.config import CONFIG
from src.utils.data_handler import fetch_recent, resample_ohlcv
from src.utils.indicators import (
    calc_ema, calc_macd, calc_rsi, calc_atr, calc_vwap, calc_vol_ratio,
    calc_swing_bias, calc_phase0, calc_trend_state,
)
from src.modules.m9_volatility import compute_vol_regime
from src.modules.m13_structure import score_m13
from src.modules.direction_resolver import resolve_direction
from src.sl_tp import calc_trade_levels, calc_limit_entry
from src.modules.tape_flow import analyze_tape_flow
from src.utils.telemetry import perf_monitor

def get_current_session():
    """
    Determines the active trading session based on UTC time.
    Returns: (session_name, strategy_type)
    """
    hour = datetime.now(timezone.utc).hour
    
    # Define Boundaries
    # Asia: 00:00 - 08:00
    # London: 07:00 - 15:00
    # New York: 12:00 - 20:00
    
    sessions = []
    if 0 <= hour < 8: sessions.append("ASIA")
    if 7 <= hour < 15: sessions.append("LONDON")
    if 12 <= hour < 20: sessions.append("NY")
    
    if not sessions:
        return "OFF-HOURS", "CONSERVATIVE"
    
    # Strategy Mapping
    if "NY" in sessions or "LONDON" in sessions:
        strategy = "MOMENTUM/TREND"
    elif "ASIA" in sessions:
        strategy = "MEAN_REVERSION/RANGE"
    else:
        strategy = "NEUTRAL"
        
    return "/".join(sessions), strategy

def compute_tf_bias(df):

    """
    Computes a bias score from 0.0 (Bearish) to 1.0 (Bullish) 
    based on EMA, RSI, and MACD.
    """
    if df is None or len(df) < 50:
        return 0.5
    
    close = df['Close']
    # 1. EMA Bias (Trend)
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    ema_bull = 1.0 if ema20.iloc[-1] > ema50.iloc[-1] else 0.0
    
    # 2. RSI Bias (Momentum)
    rsi = calc_rsi(close, 14)
    rsi_bull = 1.0 if rsi.iloc[-1] > 50 else 0.0
    
    # 3. MACD Bias (Acceleration)
    macd, signal, hist = calc_macd(close)
    macd_bull = 1.0 if hist.iloc[-1] > 0 else 0.0
    
    return (ema_bull + rsi_bull + macd_bull) / 3.0

def find_swing_points(df, window=10):
    """Finds local maxima and minima as structural liquidity points."""
    highs = []
    lows = []
    for i in range(window, len(df) - window):
        if df['High'].iloc[i] == df['High'].iloc[i-window:i+window+1].max():
            highs.append(df['High'].iloc[i])
        if df['Low'].iloc[i] == df['Low'].iloc[i-window:i+window+1].min():
            lows.append(df['Low'].iloc[i])
    return highs, lows

def find_psychological_levels(current_price, range_pct=0.05, step=25.0):
    """Identifies round number magnets (e.g., 1975, 2000, 2025)."""
    lower_bound = current_price * (1 - range_pct)
    upper_bound = current_price * (1 + range_pct)
    
    # Start from the nearest multiple of 'step' below the lower bound
    start = (np.floor(lower_bound / step) * step)
    levels = np.arange(start, upper_bound + step, step)
    
    # Filter to keep only those within the bounds
    return [l for l in levels if lower_bound <= l <= upper_bound]

def get_liquidity_magnets(df):
    """
    Robustly extracts key price levels based on volume spikes, 
    structural swing points, and psychological round numbers.
    """
    if df is None or len(df) == 0:
        return []
    
    current_price = df['Close'].iloc[-1]
    magnets = set()
    
    # 1. Volume-Based Magnets (High Volume Nodes)
    top_vol = df.nlargest(5, 'Volume')
    for _, row in top_vol.iterrows():
        magnets.add(round((row['High'] + row['Low']) / 2, 2))
    
    # 2. Structural Magnets (Swing Highs/Lows)
    highs, lows = find_swing_points(df)
    for h in highs[-5:]: # Latest 5 swing highs
        magnets.add(round(h, 2))
    for l in lows[-5:]: # Latest 5 swing lows
        magnets.add(round(l, 2))
        
    # 3. Psychological Magnets (Round Numbers)
    psych_levels = find_psychological_levels(current_price)
    for p in psych_levels:
        magnets.add(round(p, 2))
    
    # Sort and return top 5 closest to current price
    sorted_magnets = sorted(list(magnets), key=lambda x: abs(x - current_price))
    return sorted_magnets[:5]

def compute_indicators_core(df_15m, config=None):
    """Core indicator computation used for live briefs."""
    cfg = config or CONFIG
    df_15m['vwap'] = calc_vwap(df_15m['High'], df_15m['Low'], df_15m['Close'], df_15m['Volume'], cfg['VWAP_LOOKBACK'])
    df_15m['atr'] = calc_atr(df_15m['High'], df_15m['Low'], df_15m['Close'], cfg['ATR_PERIOD'])
    
    df_1h = resample_ohlcv(df_15m, '1H')
    df_4h = resample_ohlcv(df_15m, '4H')
    df_1d = resample_ohlcv(df_15m, '1D')
    
    df_1h['atr'] = calc_atr(df_1h['High'], df_1h['Low'], df_1h['Close'], cfg['ATR_PERIOD'])
    df_1d['swing_bias'] = calc_swing_bias(df_1d)
    df_1d['trend'], _ = calc_trend_state(df_1d)
    
    return df_15m, df_1h, df_4h, df_1d

def run_full_scan(symbol='ETHUSDT'):
    """
    Enhanced live scan that returns a results dictionary for the Brief.
    Now includes multi-timeframe bias and liquidity magnets.
    """
    cfg = CONFIG
    
    # 1. Fetch Data
    perf_monitor.start()
    df_15m = fetch_recent(symbol=symbol, timeframe='15m', bars=1000)
    perf_monitor.stop("data_fetching")
    
    if df_15m is None or len(df_15m) == 0:
        return None

    # 2. Indicators & Resampling
    perf_monitor.start()
    df_15m, df_1h, df_4h, df_1d = compute_indicators_core(df_15m, cfg)
    perf_monitor.stop("indicator_computation")
    
    idx = len(df_15m) - 1
    idx_1h = len(df_1h) - 1
    idx_4h = len(df_4h) - 1
    idx_1d = len(df_1d) - 1
    row = df_15m.iloc[idx]
    current_price = float(row['Close'])

    # 3. Multi-Timeframe Bias Computation
    bias_15m = compute_tf_bias(df_15m)
    bias_1h = compute_tf_bias(df_1h)
    bias_4h = compute_tf_bias(df_4h)
    bias_1d = compute_tf_bias(df_1d)

    # 4. Environment (M9)
    vol_regime, m9_raw, m9_details = compute_vol_regime(df_15m, df_1h, idx, idx_1h)

    # 5. Structure (M13)
    m13_bias = df_1d['swing_bias'].iloc[idx_1d]
    m13_score = 0.5
    m13_details = {'m13_bias': m13_bias}

    # 5. Data Preparation for Indicators
    # Ensure CVD is calculated for Tape Flow analysis
    from src.modules.m4_cvd import calc_cvd_15m
    df_15m['cvd_15m'] = calc_cvd_15m(df_15m)

    # 6. Direction Resolution
    perf_monitor.start()
    direction, dir_size_mult, dir_details = resolve_direction(
        vol_regime, m9_raw, m13_bias, m13_score, m13_details,
        swing_bias_1d=df_1d['swing_bias'].iloc[idx_1d],
        trend_dir=df_1d['trend'].iloc[idx_1d],
        config=cfg
    )
    perf_monitor.stop("direction_resolution")

    # 7. Session Filtering
    session_name, session_strategy = get_current_session()
    
    # 8. SR and Liquidity
    perf_monitor.start()
    magnets = get_liquidity_magnets(df_15m)
    perf_monitor.stop("liquidity_analysis")

    # 9. Tape Flow Analysis (Moved up to inform Taker Score)
    perf_monitor.start()
    tape_results = analyze_tape_flow(df_15m, current_price, magnets, direction=direction)
    perf_monitor.stop("tape_flow_analysis")

    # --- Structural Breakdown Override ---
    # We trigger this if we see a strong directional alignment across MTF
    # OR if we see a massive "Price Flush" (Price > 1.5% below 24h high)
    # OR if we have breached the lowest liquidity magnet (Structural Slide).
    bearish_align = sum([bias_1h < 0.4, bias_4h < 0.4, bias_1d < 0.4]) >= 2
    bullish_align = sum([bias_1h > 0.6, bias_4h > 0.6, bias_1d > 0.6]) >= 2
    
    # Price Flush: Drop > 1.5% from 24h High
    day_high = df_1d['High'].iloc[-1]
    price_flush_bear = (day_high - current_price) / day_high > 0.015
    price_flush_bull = (current_price - df_1d['Low'].iloc[-1]) / df_1d['Low'].iloc[-1] > 0.015
    
    # Magnet Breach: Price is slicing through the lowest magnet (Bearish) or highest (Bullish)
    lowest_mag = min(magnets) if magnets else current_price
    highest_mag = max(magnets) if magnets else current_price
    magnet_breach_bear = (current_price < lowest_mag) and (bias_1h < 0.5)
    magnet_breach_bull = (current_price > highest_mag) and (bias_1h > 0.5)
    
    is_strong_trend = bearish_align or bullish_align or price_flush_bear or price_flush_bull or magnet_breach_bear or magnet_breach_bull
    is_not_chopping = vol_regime != "CHOP"
    
    structural_break = is_strong_trend and is_not_chopping
    
    # ABSORPTION NEUTRALIZER:
    # If the tape shows absorption, we neutralize the structural break immediately.
    # It means the "flush" has hit a wall of liquidity.
    if tape_results.get('absorption') == 'DETECTED':
        structural_break = False

    # DEBUG LOGGING
    print(f"DEBUG: Price={current_price:.2f} | DayHigh={day_high:.2f} | FlushBear={price_flush_bear}")
    print(f"DEBUG: BearAlign={bearish_align} | MagBreachBear={magnet_breach_bear} | StrongTrend={is_strong_trend}")
    print(f"DEBUG: VolRegime={vol_regime} | NotChopping={is_not_chopping} | StructBreak={structural_break}")
    print(f"DEBUG: Direction={direction} | SessionStrat={session_strategy} | TapeState={tape_results.get('state')}")
    # -------------------------------------

    # Adjust Taker Score based on session logic
    final_taker_score = 0.5 # Default
    if structural_break:
        # Override: High conviction for strong structural moves
        if direction == "LONG":
            final_taker_score = 0.8
        elif direction == "SHORT":
            final_taker_score = 0.2
        else:
            final_taker_score = 0.5
            
        # CONVICTION DECAY:
        # If the move is structural but the tape is "idling" (Low Volume Drift),
        # we pull the score closer to neutral (0.5).
        if tape_results.get('state') == "LOW VOLUME DRIFT":
            if direction == "LONG":
                final_taker_score = 0.65 # 0.8 -> 0.65
            elif direction == "SHORT":
                final_taker_score = 0.35 # 0.2 -> 0.35
    elif session_strategy == "MEAN_REVERSION/RANGE":
        # If bias is strongly bullish but in Asia, dampen the taker score
        if direction == "BULLISH" and bias_1h > 0.7:
            final_taker_score = 0.4 # Reduce conviction for trend-following in Asia
        elif direction == "BEARISH" and bias_1h < 0.3:
            final_taker_score = 0.4
    elif session_strategy == "MOMENTUM/TREND":
        # Boost conviction for strong bias during London/NY
        if (direction == "BULLISH" and bias_1h > 0.7) or (direction == "BEARISH" and bias_1h < 0.3):
            final_taker_score = 0.7

    # 9. Tape Flow Analysis
    # This is now handled above in the Taker Score logic
    pass
    
    # Results for generate_brief
    results = {
        'current_price': current_price,
        'atr': float(df_1h['atr'].iloc[idx_1h]),
        'm10': {'score_adj': 0.5}, # Macro simplified
        'm67': {'score_adj': 0.5}, 
        'm7': {'regime': vol_regime},
        'm9': {'regime': vol_regime},
        'm18': {'status': 'SKIP'}, 
        'm21': {'status': 'SKIP'},
        'taker': {'score': final_taker_score}, 
        'resistance': [f"${row['High']:.2f}"],
        'support': [f"${row['Low']:.2f}"],
        'magnets': magnets,
        'sr_levels': [],
        'liq_levels': {},
        'direction': direction,
        'dir_size_mult': dir_size_mult,
        'session': session_name,
        'session_strategy': session_strategy,
        'tape_flow': tape_results,
        # Enhanced Data
        'tf_bias': {
            '15m': bias_15m,
            '1h': bias_1h,
            '4h': bias_4h,
            '1d': bias_1d
        },
        'perf_metrics': perf_monitor.get_summary()
    }


    
    return results
