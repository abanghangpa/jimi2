#!/usr/bin/env python3
"""
Compounding Simulation — $200 on HTX
Uses actual 17 trades from liquidity_grab + whale_watch
Models: leverage, HTX fees, funding rates, compounding
"""
import json, os

BASE = "/root/.openclaw/workspace/jimi_audit"
TRADES_FILE = os.path.join(BASE, "reports", "whale_pair_analysis.json")

# ============================================================
# HTX PARAMETERS
# ============================================================
INITIAL_CAPITAL = 200.0
LEVERAGE = 25          # from scanner_executor.py
RISK_PCT = 0.10        # 10% of capital per trade
MAKER_FEE = 0.0002     # 0.02% maker
TAKER_FEE = 0.0005     # 0.05% taker
FUNDING_RATE = 0.0001  # 0.01% per 8h (average, paid 3x daily)
FUNDING_HOURS = 8      # funding interval

# ============================================================
# LOAD TRADES
# ============================================================
with open(TRADES_FILE) as f:
    data = json.load(f)

trades = data['results']['liquidity_grab']['trades']
config = data['results']['liquidity_grab']['config']

# ============================================================
# SIMULATE COMPOUNDING
# ============================================================

print("=" * 70)
print("$200 COMPOUNDING SIMULATION — HTX Perpetuals")
print("=" * 70)
print(f"\nStrategy: liquidity_grab + whale_watch")
print(f"Config: ls_hi={config['ls_hi']}, ls_lo={config['ls_lo']}, "
      f"tp={config['tp']}x ATR, sl={config['slm']}x ATR, hold={config['hb']} bars")
print(f"Capital: ${INITIAL_CAPITAL}")
print(f"Leverage: {LEVERAGE}x")
print(f"Risk per trade: {RISK_PCT*100}% of capital")
print(f"HTX Fees: maker={MAKER_FEE*100}%, taker={TAKER_FEE*100}%")
print(f"Funding rate: ~{FUNDING_RATE*100}% per {FUNDING_HOURS}h")

capital = INITIAL_CAPITAL
trade_log = []
peak = capital
max_dd = 0

print(f"\n{'#':>3s} {'Time':<20s} {'Dir':>5s} {'Outcome':>3s} {'Entry':>9s} {'Exit':>9s} "
      f"{'PnL%':>7s} {'Pos$':>8s} {'Fee$':>6s} {'Fund$':>6s} {'NetPnL$':>8s} {'Capital':>10s}")
print("-" * 110)

for i, t in enumerate(trades):
    entry = t['entry']
    exit_price = t['exit']
    direction = t['dir']
    bars_held = t['bars']
    raw_pnl_pct = t['pnl']  # This is the raw price move %
    outcome = t['outcome']
    
    # Position size = risk_pct * capital (before leverage)
    position_notional = capital * RISK_PCT * LEVERAGE
    
    # Fee: entry (taker) + exit (taker for TP/SL hits)
    entry_fee = position_notional * TAKER_FEE
    exit_fee = position_notional * TAKER_FEE
    total_fee = entry_fee + exit_fee
    
    # Funding: paid every 8h, for duration of trade
    hours_held = bars_held * 0.25  # 15m bars
    funding_payments = hours_held / FUNDING_HOURS
    funding_cost = position_notional * FUNDING_RATE * funding_payments
    
    # PnL from price movement (leveraged)
    # raw_pnl_pct is the % move of the underlying
    # With leverage, PnL = position_notional * raw_pnl_pct / 100
    gross_pnl = position_notional * raw_pnl_pct / 100
    
    # Net PnL
    net_pnl = gross_pnl - total_fee - funding_cost
    
    # Update capital
    capital += net_pnl
    if capital > peak:
        peak = capital
    dd = (peak - capital) / peak * 100 if peak > 0 else 0
    if dd > max_dd:
        max_dd = dd
    
    trade_log.append({
        'trade': i + 1,
        'time': t['time'],
        'dir': direction,
        'outcome': outcome,
        'entry': entry,
        'exit': exit_price,
        'raw_pnl_pct': raw_pnl_pct,
        'position': position_notional,
        'fee': total_fee,
        'funding': funding_cost,
        'net_pnl': net_pnl,
        'capital': capital,
        'dd': dd,
    })
    
    print(f"{i+1:>3d} {t['time']:<20s} {direction:>5s} {outcome:>3s} {entry:>9.2f} {exit_price:>9.2f} "
          f"{raw_pnl_pct:>+6.2f}% ${position_notional:>7.0f} ${total_fee:>5.2f} ${funding_cost:>5.2f} "
          f"${net_pnl:>+7.2f} ${capital:>9.2f}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)

total_return = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
total_fees = sum(t['fee'] for t in trade_log)
total_funding = sum(t['funding'] for t in trade_log)
total_costs = total_fees + total_funding
wins = sum(1 for t in trade_log if t['net_pnl'] > 0)
losses = sum(1 for t in trade_log if t['net_pnl'] <= 0)

# Annualize (17 trades in 35 days)
days = 35
trades_per_year = 365 / days * len(trades)

print(f"\n  Starting Capital:    ${INITIAL_CAPITAL:.2f}")
print(f"  Final Capital:       ${capital:.2f}")
print(f"  Net Profit:          ${capital - INITIAL_CAPITAL:.2f}")
print(f"  Total Return:        {total_return:+.2f}%")
print(f"  Max Drawdown:        {max_dd:.2f}%")
print(f"  Trades:              {len(trades)} ({wins}W / {losses}L)")
print(f"  Period:              {days} days")
print(f"  Total Fees:          ${total_fees:.2f}")
print(f"  Total Funding:       ${total_funding:.2f}")
print(f"  Total Costs:         ${total_costs:.2f}")

print(f"\n  --- Projected Annual (if pace holds) ---")
print(f"  Trades/Year:         ~{trades_per_year:.0f}")
annual_return = ((1 + total_return / 100) ** (365 / days) - 1) * 100
print(f"  Annualized Return:   {annual_return:+.1f}%")
print(f"  Capital after 1yr:   ${INITIAL_CAPITAL * (1 + annual_return / 100):.2f}")

# ============================================================
# SCENARIO PROJECTIONS
# ============================================================
print(f"\n  --- Growth Milestones ---")
milestones = [250, 300, 500, 1000, 2000, 5000, 10000, 1000000]
cap = INITIAL_CAPITAL
trade_idx = 0
for target in milestones:
    if target <= INITIAL_CAPITAL:
        continue
    # How many more trades to reach target?
    # Average PnL per trade
    avg_pnl = sum(t['net_pnl'] for t in trade_log) / len(trade_log)
    # But we need compounding, so simulate
    sim_cap = capital  # start from current
    extra_trades = 0
    while sim_cap < target and extra_trades < 10000:
        # Use average trade PnL as % of capital
        avg_pnl_pct = sum(t['net_pnl'] / t['capital'] * 100 for t in trade_log) / len(trade_log)
        sim_cap *= (1 + avg_pnl_pct / 100)
        extra_trades += 1
    
    total_trades = len(trades) + extra_trades
    total_days = days + extra_trades * (days / len(trades))
    
    if sim_cap >= target:
        if total_days < 365:
            print(f"  ${target:>10,.0f}  →  ~{total_trades} trades (~{total_days:.0f} days)")
        else:
            print(f"  ${target:>10,.0f}  →  ~{total_trades} trades (~{total_days/365:.1f} years)")
    else:
        print(f"  ${target:>10,.0f}  →  not reached within 10,000 trades")

# ============================================================
# WITH FILTERED CONFIG (sweep >= 0.08)
# ============================================================
print(f"\n  --- With Sweep >= 0.08 Filter (5 trades, 80% WR) ---")
# These 5 trades had higher quality
filtered_trades = []
sweep_thresholds = [0.08]
# We don't have sweep data here, so use the known 5 trades
# From the validation: trades with sweep >= 0.08 had WR=80%, avg PnL = 1.7642/5 = 0.353%
# But fewer trades (5 vs 17 in same period)
filtered_cap = INITIAL_CAPITAL
for t in trade_log:
    # Only take trades where raw_pnl was positive (proxy for sweep-filtered)
    # Actually, let's just model the 5 filtered trades
    pass

# Better: use the actual filtered stats
# 5 trades, WR=80%, total PnL = +1.7642% on capital
# Per trade: avg +0.353% on capital
# But with compounding over 35 days:
# 5 trades / 35 days = 1 trade per 7 days
# Annual: ~52 trades
# With 80% WR and PF=14.46:
# avg_win = very large, avg_loss = very small
# Expected per-trade return: 0.80 * big_win - 0.20 * small_loss

# Let's estimate from the 5 actual filtered trade PnLs
# We know total PnL = +1.7642% on 5 trades
# With compounding and leverage:
filtered_return_pct = 1.7642  # % over 35 days on 5 trades
filtered_annual = ((1 + filtered_return_pct / 100) ** (365 / 35) - 1) * 100
print(f"  5 trades in 35 days")
print(f"  Return: {filtered_return_pct:.2f}%")
print(f"  Annualized: {filtered_annual:.1f}%")
print(f"  Capital after 1yr: ${INITIAL_CAPITAL * (1 + filtered_annual / 100):.2f}")
print(f"  Trades/year: ~52 (1 per week)")
print(f"  Note: fewer trades but each trade is higher quality")

print()
