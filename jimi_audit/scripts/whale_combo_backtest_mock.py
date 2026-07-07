#!/usr/bin/env python3
"""
Whale Watch Combo Backtest — MOCK VERSION
==========================================
Same as whale_combo_backtest.py but uses a mock scan_signal()
with precomputed dummy data covering all scenarios.
No network calls = runs in seconds, not hours.

10 Scenario Sets:
  1. Strong bull — whale long, low funding
  2. Strong bear — whale short, high funding
  3. Ranging/neutral — mixed signals, low conviction
  4. Squeeze building — high OI, neutral LS
  5. Cascade/crash — extreme bear, negative funding
  6. Recovery — whale shifting long, low OI
  7. High volatility — extreme LS both ways
  8. Accumulation — whale quietly long
  9. Distribution — whale quietly short
  10. Mixed — some bullish, some bearish
"""
import sys, os, json, time, random, math
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, "/root/.openclaw/workspace/jimi_audit")
os.chdir("/root/.openclaw/workspace/jimi_audit")

from src.config import CONFIG
from src.utils.data_handler import load_data
from src.utils.indicators import calc_atr, calc_vol_ratio, calc_ema, calc_rsi, calc_macd

# ============================================================
# CONFIG
# ============================================================
START_DATE = "2026-05-13"
END_DATE = "2026-07-06"
INITIAL_CAPITAL = 200.0
LEVERAGE = 25
RISK_PCT = 0.10
FEE_RATE = 0.0005
STEP = 4  # every 1h

EVENT_STRATEGIES = [
    "failed_breakout", "structural_break", "squeeze_breakout",
    "positioning_fade", "orderbook_imbalance", "trade_flow",
    "funding_arb", "regime_switch", "liquidity_grab",
    "judas_sweep", "taker_flow", "vol_rotation",
    "scalp_v2", "momentum_v3", "cross_asset",
    "mtf_confluence", "power_of_3", "bb_mom6",
]

# ============================================================
# 10 PRECOMPUTED SCENARIO SETS
# ============================================================
SCENARIO_SETS = [
    # 1: Strong bull
    {"ls_ratio": 1.65, "funding_rate": 0.0001, "oi_usd": 8.5e9,
     "bias": "LONG", "conviction_base": 0.72, "fire_rate": 0.45},
    # 2: Strong bear
    {"ls_ratio": 2.35, "funding_rate": 0.0008, "oi_usd": 9.2e9,
     "bias": "SHORT", "conviction_base": 0.68, "fire_rate": 0.40},
    # 3: Ranging/neutral
    {"ls_ratio": 1.02, "funding_rate": 0.0003, "oi_usd": 7.1e9,
     "bias": "NEUTRAL", "conviction_base": 0.45, "fire_rate": 0.25},
    # 4: Squeeze building
    {"ls_ratio": 1.08, "funding_rate": 0.0006, "oi_usd": 11.3e9,
     "bias": "LONG", "conviction_base": 0.55, "fire_rate": 0.35},
    # 5: Cascade/crash
    {"ls_ratio": 2.80, "funding_rate": -0.0012, "oi_usd": 12.0e9,
     "bias": "SHORT", "conviction_base": 0.80, "fire_rate": 0.55},
    # 6: Recovery
    {"ls_ratio": 1.45, "funding_rate": -0.0003, "oi_usd": 6.0e9,
     "bias": "LONG", "conviction_base": 0.60, "fire_rate": 0.30},
    # 7: High volatility
    {"ls_ratio": 0.75, "funding_rate": 0.0010, "oi_usd": 10.5e9,
     "bias": "SHORT", "conviction_base": 0.58, "fire_rate": 0.38},
    # 8: Accumulation
    {"ls_ratio": 1.55, "funding_rate": 0.00005, "oi_usd": 7.8e9,
     "bias": "LONG", "conviction_base": 0.65, "fire_rate": 0.28},
    # 9: Distribution
    {"ls_ratio": 1.95, "funding_rate": 0.0004, "oi_usd": 8.8e9,
     "bias": "SHORT", "conviction_base": 0.62, "fire_rate": 0.32},
    # 10: Mixed
    {"ls_ratio": 1.15, "funding_rate": 0.0002, "oi_usd": 7.5e9,
     "bias": "NEUTRAL", "conviction_base": 0.50, "fire_rate": 0.20},
]

def mock_scan_signal(df_15m, df_1h, df_2h, df_4h, df_1d, config=None,
                     btc_15m_df=None, btc_corr_series=None):
    """Mock scan_signal — returns realistic data, no network calls."""
    idx = len(df_15m) - 1
    row = df_15m.iloc[idx]
    ts = row['Open time']
    price = float(row['Close'])

    # Cycle through 10 scenarios
    scenario_idx = (idx // 50) % len(SCENARIO_SETS)
    scenario = SCENARIO_SETS[scenario_idx]
    
    noise = random.gauss(0, 0.05)
    fire_rate = max(0.05, min(0.80, scenario['fire_rate'] + noise))
    
    strategies = {}
    for strat_name in EVENT_STRATEGIES:
        if random.random() < fire_rate:
            if scenario['bias'] == 'NEUTRAL':
                direction = random.choice(['LONG', 'SHORT'])
            else:
                direction = scenario['bias'] if random.random() < 0.75 else ('SHORT' if scenario['bias'] == 'LONG' else 'LONG')
            
            conv = max(0.1, min(0.95, scenario['conviction_base'] + random.gauss(0, 0.12)))
            strategies[strat_name] = {
                'direction': direction,
                'conviction': round(conv, 3),
                'status': 'FIRE',
                'details': f'mock_{direction.lower()}_{conv:.2f}',
            }
        else:
            strategies[strat_name] = {'direction': None, 'conviction': 0, 'status': 'NO_FIRE'}

    ls_noise = scenario['ls_ratio'] + random.gauss(0, 0.05)
    fr_noise = scenario['funding_rate'] + random.gauss(0, 0.0001)
    long_pct = round(50 + (1.0 / max(ls_noise, 0.1) - 1) * 50, 1)
    
    derivatives = {
        'ls_ratio': round(max(0.5, ls_noise), 4),
        'funding_rate': round(fr_noise, 6),
        'oi_usd': scenario['oi_usd'] * (1 + random.gauss(0, 0.02)),
        'long_pct': long_pct,
        'short_pct': round(100 - long_pct, 1),
        'top_ls_ratio': round(ls_noise * 0.95, 4),
        'oi_roc_1h': round(random.gauss(0, 0.5), 2),
        'whale_signal': 'WHALE_BULLISH' if ls_noise < 1.8 else ('WHALE_BEARISH' if ls_noise > 2.2 else 'NEUTRAL'),
        'ls_zscore': round((ls_noise - 1.0) / 0.3, 2),
    }

    idx_1h = len(df_1h) - 1
    
    result = {
        'timestamp': str(ts),
        'price': price,
        'swing_bias': scenario['bias'] if scenario['bias'] != 'NEUTRAL' else 'NEUTRAL',
        'phase0': round(random.uniform(-1, 1), 3),
        'trend_dir': scenario['bias'] if scenario['bias'] != 'NEUTRAL' else 'SIDEWAYS',
        'trend_val': round(random.uniform(-2, 2), 3),
        'ema_200': float(df_1h['ema_200'].iloc[idx_1h]) if 'ema_200' in df_1h.columns else price,
        'ensemble_passes': scenario['conviction_base'] > 0.55,
        'sweep_blocked': False,
        'm20_blocked': False,
        'strategies': strategies,
        'derivatives': derivatives,
        'direction': scenario['bias'] if scenario['bias'] != 'NEUTRAL' else random.choice(['LONG', 'SHORT']),
        'm9': {'regime': 'NORMAL', 'raw': round(random.uniform(-1, 1), 3)},
        'm13': {'bias': scenario['bias'] if scenario['bias'] != 'NEUTRAL' else 'NEUTRAL',
                'score': round(random.uniform(0, 1), 3), 'status': 'ACTIVE'},
        'liquidity_levels': {
            'below': [{'price': price * 0.995, 'type': 'BID_WALL', 'strength': 0.6},
                       {'price': price * 0.990, 'type': 'ASK_WALL', 'strength': 0.4}],
            'above': [{'price': price * 1.005, 'type': 'ASK_WALL', 'strength': 0.7},
                       {'price': price * 1.010, 'type': 'BID_WALL', 'strength': 0.3}],
        },
    }
    return result


# ============================================================
# LOAD DATA & COMPUTE INDICATORS
# ============================================================
print("=" * 70)
print("WHALE WATCH COMBO BACKTEST (MOCK — 10 scenario sets)")
print(f"Period: {START_DATE} → {END_DATE}")
print("=" * 70)

print("\n[1/3] Loading data...")
df_raw = load_data("eth_15m_merged.csv")
df_raw['Open time'] = pd.to_datetime(df_raw['Open time'])

cfg = CONFIG
from scripts.scanner import compute_indicators

print("[2/3] Computing indicators...")
t0 = time.time()
df_15m, df_1h, df_2h, df_4h, df_1d = compute_indicators(df_raw.copy(), config=cfg)
print(f"  Indicators done in {time.time()-t0:.0f}s")

mask = (df_15m['Open time'] >= START_DATE) & (df_15m['Open time'] <= END_DATE)
indices = df_15m[mask].index.tolist()
start_idx = max(indices[0], 500) if indices else 500
end_idx = indices[-1] if indices else len(df_15m) - 1

print(f"  Period: {df_15m['Open time'].iloc[start_idx]} to {df_15m['Open time'].iloc[end_idx]}")
print(f"  Bars: {end_idx - start_idx + 1} | Step: {STEP}")
print(f"  Scenarios: {len(SCENARIO_SETS)} sets")

# ============================================================
# BACKTEST ENGINE
# ============================================================
def run_combo_backtest(event_strategy, use_whale=True, use_fr_filter=False, fr_threshold=0.0):
    trades = []
    capital = INITIAL_CAPITAL
    peak = capital
    max_dd = 0
    open_positions = []
    total_signals = 0
    cooldown_until = {}

    for i in range(start_idx, end_idx + 1, STEP):
        row = df_15m.iloc[i]
        ts = row['Open time']
        price = float(row['Close'])
        high = float(row['High'])
        low = float(row['Low'])

        closed = []
        for pos in open_positions:
            bars_held = i - pos['entry_idx']
            max_bars = pos['hold_hours'] * 4
            
            hit_tp = hit_sl = timeout = False
            if pos['direction'] == 'LONG':
                if high >= pos['tp']: hit_tp = True
                elif low <= pos['sl']: hit_sl = True
            else:
                if low <= pos['tp']: hit_tp = True
                elif high >= pos['sl']: hit_sl = True
            
            if bars_held >= max_bars:
                timeout = True
            
            if hit_tp or hit_sl or timeout:
                if hit_tp:
                    exit_price = pos['tp']
                    outcome = 'WIN'
                elif hit_sl:
                    exit_price = pos['sl']
                    outcome = 'LOSS'
                else:
                    exit_price = price
                    outcome = 'WIN' if ((pos['direction'] == 'LONG' and price > pos['entry']) or 
                                        (pos['direction'] == 'SHORT' and price < pos['entry'])) else 'LOSS'
                
                pnl_pct = ((exit_price - pos['entry']) / pos['entry'] * 100) if pos['direction'] == 'LONG' \
                          else ((pos['entry'] - exit_price) / pos['entry'] * 100)
                pnl_dollar = pos['size'] * pnl_pct / 100
                fee = pos['size'] * FEE_RATE * 2
                net_pnl = pnl_dollar - fee
                capital += net_pnl
                
                if capital > peak: peak = capital
                dd = (peak - capital) / peak * 100 if peak > 0 else 0
                if dd > max_dd: max_dd = dd
                
                trades.append({
                    'time': str(ts), 'direction': pos['direction'],
                    'entry': pos['entry'], 'exit': exit_price,
                    'pnl_pct': pnl_pct, 'pnl_dollar': net_pnl,
                    'outcome': outcome, 'bars': bars_held,
                    'strategy': event_strategy,
                })
                closed.append(pos)
        
        for c in closed:
            open_positions.remove(c)
        
        if capital <= 0:
            break
        
        if event_strategy in cooldown_until and i < cooldown_until[event_strategy]:
            continue
        
        if any(p['strategy'] == event_strategy for p in open_positions):
            continue
        
        try:
            result = mock_scan_signal(df_15m.iloc[:i+1], df_1h, df_2h, df_4h, df_1d, config=cfg)
        except Exception as e:
            continue
        
        strategies = result.get('strategies', {})
        
        event_sig = strategies.get(event_strategy)
        if not event_sig or not event_sig.get('direction'):
            continue
        
        direction = event_sig['direction']
        
        if use_whale:
            deriv = result.get('derivatives', {})
            ls_ratio = deriv.get('ls_ratio', 1.0) if deriv else 1.0
            if direction == 'SHORT' and ls_ratio <= 1.0:
                continue
            if direction == 'LONG' and ls_ratio >= 1.0:
                continue
        
        if use_fr_filter:
            deriv = result.get('derivatives', {})
            fr = deriv.get('funding_rate', 0) if deriv else 0
            if direction == 'SHORT' and fr < fr_threshold:
                continue
            if direction == 'LONG' and fr > -fr_threshold:
                continue
        
        total_signals += 1
        
        entry = price
        atr = float(row.get('atr', 0)) if 'atr' in row else 0
        if atr <= 0:
            atr = abs(float(row['High']) - float(row['Low']))
        if atr <= 0:
            continue
        
        tp_mult = 2.0
        sl_mult = 1.0
        hold_hours = 8
        
        if direction == 'LONG':
            tp = entry + tp_mult * atr
            sl = entry - sl_mult * atr
        else:
            tp = entry - tp_mult * atr
            sl = entry + sl_mult * atr
        
        size = capital * RISK_PCT * LEVERAGE
        
        open_positions.append({
            'entry_idx': i, 'entry': entry, 'direction': direction,
            'tp': tp, 'sl': sl, 'size': size, 'hold_hours': hold_hours,
            'strategy': event_strategy,
        })
        
        cooldown_until[event_strategy] = i + 6
    
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0, 'signals': total_signals}
    
    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']
    total_win = sum(t['pnl_dollar'] for t in wins)
    total_loss = sum(abs(t['pnl_dollar']) for t in losses)
    pf = total_win / total_loss if total_loss > 0 else float('inf')
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(len(wins) / len(trades) * 100, 1) if trades else 0,
        'pf': round(pf, 2),
        'pnl': round(sum(t['pnl_dollar'] for t in trades), 2),
        'pnl_pct': round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'final_capital': round(capital, 2),
        'max_dd': round(max_dd, 2),
        'signals': total_signals,
    }

# ============================================================
# RUN ALL COMBOS
# ============================================================
print("\n[3/3] Running backtests (mock — no network calls)...")
print(f"  Testing {len(EVENT_STRATEGIES)} event strategies × 3 configs each\n")

results = []

for strat in EVENT_STRATEGIES:
    print(f"  Testing {strat}...", end="", flush=True)
    
    m1 = run_combo_backtest(strat, use_whale=False)
    m2 = run_combo_backtest(strat, use_whale=True)
    m3 = run_combo_backtest(strat, use_whale=True, use_fr_filter=True, fr_threshold=0.00005)
    
    results.append({'strategy': strat, 'config': 'event_only', **m1})
    results.append({'strategy': strat, 'config': 'event+whale', **m2})
    results.append({'strategy': strat, 'config': 'event+whale+FR', **m3})
    
    if m2['trades'] > 0:
        hit = " ***" if m2['pf'] >= 2.0 and m2['wr'] >= 75 else ""
        print(f"  event={m1['trades']:>3d}t {m1['wr']:>5.1f}% PF={m1['pf']:>5.2f} | "
              f"+whale={m2['trades']:>3d}t {m2['wr']:>5.1f}% PF={m2['pf']:>5.2f} | "
              f"+FR={m3['trades']:>3d}t {m3['wr']:>5.1f}% PF={m3['pf']:>5.2f}{hit}")
    else:
        print(f"  event={m1['trades']:>3d}t | +whale=0t | +FR=0t  (no signals)")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY — Best Combos with Whale Watch (MOCK DATA)")
print("=" * 70)

valid = [r for r in results if r['trades'] >= 3 and r['config'] == 'event+whale']
valid.sort(key=lambda x: (-x['pf'], -x['wr']))

print(f"\n  {'Strategy':>20s} | {'Config':>15s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s} | {'MaxDD':>6s}")
print("  " + "-" * 90)
for r in valid[:20]:
    hit = " ***" if r['pf'] >= 2.0 and r['wr'] >= 75 else ""
    print(f"  {r['strategy']:>20s} | {r['config']:>15s} | {r['trades']:>6d} | {r['wr']:>5.1f}% | {r['pf']:>6.2f} | ${r['pnl']:>+7.2f} | {r['pnl_pct']:>+6.2f}% | {r['max_dd']:>5.2f}%{hit}")

valid_fr = [r for r in results if r['trades'] >= 3 and r['config'] == 'event+whale+FR']
valid_fr.sort(key=lambda x: (-x['pf'], -x['wr']))

if valid_fr:
    print(f"\n  With FR >= 0.00005 filter:")
    print(f"  {'Strategy':>20s} | {'Config':>15s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | {'PnL$':>8s} | {'PnL%':>7s}")
    print("  " + "-" * 75)
    for r in valid_fr[:10]:
        print(f"  {r['strategy']:>20s} | {r['config']:>15s} | {r['trades']:>6d} | {r['wr']:>5.1f}% | {r['pf']:>6.2f} | ${r['pnl']:>+7.2f} | {r['pnl_pct']:>+6.2f}%")

targets = [r for r in results if r['pf'] >= 2.0 and r['wr'] >= 75 and r['trades'] >= 3]
if targets:
    print(f"\n  *** TARGET HIT (PF>=2.0, WR>=75%, trades>=3): ***")
    for r in targets:
        print(f"    {r['strategy']} ({r['config']}): {r['trades']} trades, WR={r['wr']}%, PF={r['pf']}")
else:
    print(f"\n  No combo hit PF>=2.0 AND WR>=75% with >= 3 trades")

report_path = "/root/.openclaw/workspace/jimi_audit/reports/whale_combo_backtest_mock.json"
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {report_path}")
print(f"  NOTE: This used MOCK data (10 scenario sets). Results are directional only.")
