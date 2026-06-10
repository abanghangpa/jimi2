#!/usr/bin/env python3
"""
JIMI Intraday Trader's Brief
Transforms the raw signal scan into an actionable session-by-session brief.
"""

import sys
import os
import datetime
import numpy as np
import pandas as pd

# Ensure workspace root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config import CONFIG
from src.utils.data_handler import fetch_recent, resample_ohlcv
from src.modules.session import get_session, get_session_label
from src.modules.m7_market_regime import m7_prepare_data, m7_get_row, score_m7
from src.modules.m9_volatility import compute_vol_regime, score_vol_regime
from src.modules.m18_squeeze import detect_squeeze_v6 as detect_squeeze
from src.modules.m21_wyckoff import score_m21
from src.modules.taker_tracker import get_taker_summary
from src.engine import calc_ics, resolve_direction
from src.sl_tp import calc_trade_levels, calc_limit_entry

def generate_brief(results, session_info):
    """
    Transforms the raw module result dictionary into a structured Trader's Brief.
    """
    
    # 1. GLOBAL BIAS (Macro + TradFi + Multi-Timeframe)
    macro_score = results.get('m10', {}).get('score_adj', 0.5)
    tradfi_score = results.get('m67', {}).get('score_adj', 0.5) 
    
    # Multi-Timeframe Bias (weighted: 15m: 20%, 1h: 30%, 4h: 30%, 1d: 20%)
    tf_bias = results.get('tf_bias', {'15m': 0.5, '1h': 0.5, '4h': 0.5, '1d': 0.5})
    tf_bias_val = (tf_bias['15m'] * 0.2) + (tf_bias['1h'] * 0.3) + (tf_bias['4h'] * 0.3) + (tf_bias['1d'] * 0.2)
    
    # Combined bias: 40% Macro/TradFi, 60% TF bias
    bias_val = (macro_score + tradfi_score) * 0.4 / 2 + tf_bias_val * 0.6
    
    if bias_val > 0.6:
        bias = "🟢 BULLISH"
    elif bias_val < 0.4:
        bias = "🔴 BEARISH"
    else:
        bias = "⚪ NEUTRAL"

    # 2. SESSION ENVIRONMENT (Regime + Vol)
    regime = results.get('m7', {}).get('regime', 'UNKNOWN')
    vol_regime = results.get('m9', {}).get('regime', 'UNKNOWN')
    
    # 3. THE SETUP (The "Edge" - Structural)
    setup = "None Identified"
    setup_detail = ""
    
    squeeze_res = results.get('m18', {})
    if squeeze_res.get('status') == 'ACTIVE':
        setup = "⚡ VOLATILITY SQUEEZE"
        setup_detail = f"Type: {squeeze_res.get('type')} | Trigger: {squeeze_res.get('trigger_price')}"
    
    if setup == "None Identified":
        wyckoff_res = results.get('m21', {})
        if wyckoff_res.get('status') == 'ACTIVE':
            setup = "🏛️ WYCKOFF PHASE"
            setup_detail = f"Phase: {wyckoff_res.get('phase')} | Conf: {wyckoff_res.get('confidence')}"

    # 4. THE TRIGGER (Core Tech + Flow)
    taker_res = results.get('taker', {})
    flow_signal = "NEUTRAL"
    if taker_res.get('score', 0.5) < 0.3:
        flow_signal = "🔴 AGGRESSIVE SELLING"
    elif taker_res.get('score', 0.5) > 0.7:
        flow_signal = "🟢 AGGRESSIVE BUYING"
        
    # FINAL VERDICT
    verdict = "HOLD / WATCH"
    trade_dir = None
    if bias == "🔴 BEARISH" and flow_signal == "🔴 AGGRESSIVE SELLING":
        verdict = "🔥 HIGH CONVICTION SHORT"
        trade_dir = "SHORT"
    elif bias == "🟢 BULLISH" and flow_signal == "🟢 AGGRESSIVE BUYING":
        verdict = "🔥 HIGH CONVICTION LONG"
        trade_dir = "LONG"
    elif setup != "None Identified" and flow_signal != "NEUTRAL":
        verdict = "⚠️ SETUP TRIGGERING - WATCH CLOSELY"
        trade_dir = "SHORT" if "LONG_SQUEEZE" in setup_detail or bias == "🔴 BEARISH" else "LONG"

    # ── TRADE EXECUTION CALCULATIONS ──
    exec_plan = "No trade suggested."
    if trade_dir:
        current_price = results.get('current_price', 2100.0)
        atr = results.get('atr', 10.0)
        magnets = results.get('magnets', [])
        sr_levels = results.get('sr_levels', [])
        liq_levels = results.get('liq_levels', {})
        
        entry_res = calc_limit_entry(current_price, trade_dir, magnets, sr_levels, atr_1h=atr)
        entry_price = entry_res['entry_price']
        
        levels = calc_trade_levels(
            entry_price, trade_dir, atr, 1.0, 
            magnets, sr_levels, liq_levels
        )
        
        exec_plan = (
            f"Entry: ${entry_price:.2f} ({entry_res['entry_source']})\n"
            f"Stop Loss: ${levels['sl']:.2f} ({levels['sl_source']}) | Risk: {levels['sl_pct']:.2f}%\n"
            f"TP1: ${levels['tp1']:.2f} ({levels['tp1_source']}) | Target: {levels['tp1_pct']:.2f}%\n"
            f"TP2: ${levels['tp2']:.2f} | TP3: ${levels['tp3']:.2f}"
        )

    now = datetime.datetime.utcnow()
    session_name = results.get('session', 'UNKNOWN')
    session_strategy = results.get('session_strategy', 'NEUTRAL')
    
    brief = f"""
════════════════════════════════════════════════════════════
  🚀 JIMI INTRADAY TRADER'S BRIEF
  Time: {now.strftime('%Y-%m-%d %H:%M')} UTC | Session: {session_name}
════════════════════════════════════════════════════════════

  🎯 THE VERDICT: {verdict}
  --------------------------------------------------------
  
  🎯 EXECUTION PLAN:
     {exec_plan}
  
  🌍 GLOBAL BIAS: {bias}
     (Macro Score: {macro_score:.2f} | TradFi Score: {tradfi_score:.2f})
  
  🛡️ ENVIRONMENT: {regime} | {vol_regime}
     (Session Strategy: {session_strategy})
  
  🔭 THE SETUP: {setup}
     {setup_detail if setup_detail else "No major structural edge detected."}
  
  ⚡ TRIGGER STATUS: {flow_signal}
     Taker Score: {taker_res.get('score', 0.5):.2f}
  
  🌊 TAPE FLOW: {results.get('tape_flow', {}).get('state', 'UNKNOWN')}
     Conviction: {results.get('tape_flow', {}).get('conviction', 'NEUTRAL')} | CVD: {results.get('tape_flow', {}).get('cvd_div', 'N/A')}
  
  📍 KEY LEVELS:
     Resistance: {results.get('resistance', ['N/A'])[0]}
     Support:    {results.get('support', ['N/A'])[0]}
     Volume Magnets: {[f'${m:.2f}' for m in results.get('magnets', [])][:3]}
  
  💡 TRADER'S NOTE:
     {"Align flow with bias for high-conviction plays." if verdict == "HOLD / WATCH" else "Setup and flow are aligning. Check SL/TP."}
════════════════════════════════════════════════════════════
"""
    # Performance Telemetry Footer
    perf = results.get('perf_metrics', {})
    if perf:
        perf_footer = "\n⏱️ PERFORMANCE TELEMETRY:\n"
        for component, stats in perf.items():
            perf_footer += f"  • {component:.<25} Avg: {stats['avg']:.3f}s | Max: {stats['max']:.3f}s\n"
        brief += perf_footer
        
    return brief

def run_brief():
    """
    Executes the core logic and prints the brief using LIVE data.
    """
    print("📡 Fetching Live Market Data from JIMI Core...")
    
    try:
        from src.scanner_core import run_full_scan
        results = run_full_scan()
        
        if not results:
            print("❌ Engine returned no results.")
            return

        print(generate_brief(results, None))
        
    except Exception as e:
        print(f"❌ Error generating live brief: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_brief()
