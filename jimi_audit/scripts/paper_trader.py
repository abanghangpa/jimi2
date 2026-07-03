#!/usr/bin/env python3
"""
Paper Trading Engine - Mom12 Momentum Strategy with DD Circuit Breaker
Backtested on 8 years of ETH data: $200 -> $1M+
Signal: 12h momentum > 3% -> LONG, < -3% -> SHORT
Params: TP 0.30%, SL 0.20%, 20x leverage, 5% risk, 8h hold
DD Circuit Breaker: stop trading for 24h when drawdown hits 50%
"""
import json, os, requests
from datetime import datetime, timezone, timedelta

BASE = "/root/.openclaw/workspace/jimi_audit"
POSITIONS_FILE = os.path.join(BASE, "data", "paper_positions.json")
TRADE_LOG = os.path.join(BASE, "data", "paper_trades.json")

# === BACKTESTED PARAMETERS (8yr data) ===
TP_PCT = 0.003       # 0.30%
SL_PCT = 0.002       # 0.20%
RISK_PCT = 0.05      # 5% of capital per trade
LEVERAGE = 20        # 20x
HOLD_HOURS = 8       # 8 hour hold
MOM_PERIOD = 12      # 12-hour momentum lookback
MOM_THRESHOLD = 0.03 # 3% momentum threshold
FEE_RATE = 0.0002    # HTX maker fee 0.02% per side
SLIPPAGE = 0.001     # 0.1% slippage assumption
INITIAL_CAPITAL = 200.0

# === DRAWDOWN CIRCUIT BREAKER ===
DD_STOP = 0.50       # Stop trading at 50% drawdown
DD_COOLDOWN_HOURS = 24  # Wait 24h after DD trigger

def load_state():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {
        "capital": INITIAL_CAPITAL,
        "peak_capital": INITIAL_CAPITAL,
        "positions": [],
        "closed": [],
        "total_pnl": 0,
        "fees_paid": 0,
        "trades_count": 0,
        "wins": 0,
        "losses": 0,
        "dd_cooldown_until": None,
        "dd_triggered_count": 0,
    }

def save_state(state):
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

def log_trade(trade):
    os.makedirs(os.path.dirname(TRADE_LOG), exist_ok=True)
    trades = []
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG) as f:
            trades = json.load(f)
    trades.append(trade)
    with open(TRADE_LOG, "w") as f:
        json.dump(trades, f, indent=2, default=str)

def get_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=5)
        return float(r.json()["price"])
    except:
        return None

def get_recent_candles(limit=15):
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit={limit}",
            timeout=10
        )
        return r.json()
    except:
        return None

def get_momentum():
    candles = get_recent_candles(limit=MOM_PERIOD + 2)
    if not candles or len(candles) < MOM_PERIOD + 1:
        return None, "insufficient_data"

    current_price = float(candles[-1][4])
    past_price = float(candles[-(MOM_PERIOD + 1)][4])

    if past_price == 0:
        return None, "zero_price"

    momentum = (current_price - past_price) / past_price

    if momentum > MOM_THRESHOLD:
        return "LONG", f"mom={momentum*100:+.2f}% > +{MOM_THRESHOLD*100}%"
    elif momentum < -MOM_THRESHOLD:
        return "SHORT", f"mom={momentum*100:+.2f}% < -{MOM_THRESHOLD*100}%"
    return None, f"mom={momentum*100:+.2f}% (neutral)"

def check_dd_circuit_breaker(state):
    """Check if drawdown circuit breaker should trigger."""
    capital = state["capital"]
    peak = state.get("peak_capital", INITIAL_CAPITAL)

    # Update peak
    if capital > peak:
        state["peak_capital"] = capital
        peak = capital

    # Check if in cooldown
    cooldown_until = state.get("dd_cooldown_until")
    if cooldown_until:
        cooldown_dt = datetime.fromisoformat(cooldown_until)
        if datetime.now(timezone.utc) < cooldown_dt:
            return True, f"DD cooldown until {cooldown_until[:16]}"
        else:
            # Cooldown expired, reset
            state["dd_cooldown_until"] = None

    # Check drawdown
    if peak > 0:
        dd = (peak - capital) / peak
        if dd >= DD_STOP:
            # Trigger circuit breaker
            cooldown = datetime.now(timezone.utc) + timedelta(hours=DD_COOLDOWN_HOURS)
            state["dd_cooldown_until"] = cooldown.isoformat()
            state["dd_triggered_count"] = state.get("dd_triggered_count", 0) + 1
            return True, f"DD={dd*100:.1f}% >= {DD_STOP*100:.0f}%! Cooling down {DD_COOLDOWN_HOURS}h"

    return False, f"DD={((peak-capital)/peak*100) if peak>0 else 0:.1f}%"

def check_tp_sl(position, current_price):
    entry = position["entry"]
    direction = position["direction"]
    tp = position["tp"]
    sl = position["sl"]

    if direction == "LONG":
        if current_price >= tp:
            return "WIN", tp
        elif current_price <= sl:
            return "LOSS", sl
    else:
        if current_price <= tp:
            return "WIN", tp
        elif current_price >= sl:
            return "LOSS", sl
    return None, None

def close_position(state, position, exit_price, outcome):
    entry = position["entry"]
    size = position["size"]
    direction = position["direction"]

    if direction == "LONG":
        pnl_raw = (exit_price - entry) * size
    else:
        pnl_raw = (entry - exit_price) * size

    fee_cost = entry * size * FEE_RATE * 2
    pnl = pnl_raw - fee_cost

    state["capital"] += pnl
    state["total_pnl"] += pnl
    state["fees_paid"] += fee_cost
    state["trades_count"] += 1
    if outcome == "WIN":
        state["wins"] += 1
    else:
        state["losses"] += 1

    closed = {
        **position,
        "exit": round(exit_price, 2),
        "pnl": round(pnl, 4),
        "pnl_raw": round(pnl_raw, 4),
        "fee": round(fee_cost, 4),
        "outcome": outcome,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }
    state["closed"].append(closed)
    log_trade(closed)
    return state

def format_status(state, signal_info, current_price, dd_blocked, dd_reason):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    capital = state["capital"]
    peak = state.get("peak_capital", INITIAL_CAPITAL)
    ret = capital / INITIAL_CAPITAL
    dd_pct = ((peak - capital) / peak * 100) if peak > 0 else 0

    msg = "MOMENTUM PAPER TRADER\n"
    msg += f"Time: {now}\n"
    msg += f"ETH: ${current_price:,.2f}\n"
    msg += f"Signal: {signal_info}\n"
    msg += f"\nParams: TP {TP_PCT*100:.2f}% | SL {SL_PCT*100:.2f}% | {HOLD_HOURS}h hold | {LEVERAGE}x | {RISK_PCT*100:.0f}% risk\n"
    msg += f"Momentum: {MOM_PERIOD}h lookback, {MOM_THRESHOLD*100}% threshold\n"
    msg += f"DD Breaker: {DD_STOP*100:.0f}% stop, {DD_COOLDOWN_HOURS}h cooldown\n"
    msg += f"Capital: ${capital:,.2f} ({ret:.1f}x from ${INITIAL_CAPITAL}) | Peak: ${peak:,.2f} | DD: {dd_pct:.1f}%\n"
    msg += f"P&L: ${state['total_pnl']:,.2f} | Fees: ${state['fees_paid']:.4f}\n"

    t = state["trades_count"]
    w = state["wins"]
    wr = (w / t * 100) if t > 0 else 0
    msg += f"Trades: {t} ({w}W/{t-w}L) WR {wr:.0f}% | DD triggers: {state.get('dd_triggered_count', 0)}\n"

    if dd_blocked:
        msg += f"\n!! CIRCUIT BREAKER: {dd_reason}\n"

    if state["positions"]:
        msg += f"\nOpen Positions:\n"
        for pos in state["positions"]:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(pos["opened_at"])
            age_h = age.total_seconds() / 3600
            if pos["direction"] == "LONG":
                unrealized = (current_price - pos["entry"]) / pos["entry"] * 100
            else:
                unrealized = (pos["ertry"] - current_price) / pos["entry"] * 100
            icon = "+" if unrealized >= 0 else "-"
            msg += f"  {icon} {pos['direction']} @ ${pos['entry']:.2f} | "
            msg += f"TP ${pos['tp']:.2f} SL ${pos['sl']:.2f} | "
            msg += f"P&L {unrealized:+.2f}% | Age {age_h:.1f}h\n"
    else:
        msg += "\nNo open positions.\n"

    if state["closed"]:
        msg += f"\nRecent Trades:\n"
        for trade in state["closed"][-5:]:
            icon = "+" if trade["outcome"] == "WIN" else "-"
            msg += f"  {icon} {trade['direction']} ${trade['entry']:.2f} -> ${trade['exit']:.2f} | "
            msg += f"PnL: {'+' if trade['pnl'] > 0 else ''}{trade['pnl']:.2f}\n"

    return msg

def main():
    state = load_state()
    current_price = get_price()
    if not current_price:
        print("Failed to get price")
        return

    signal, signal_info = get_momentum()

    # === DRAWDOWN CIRCUIT BREAKER CHECK ===
    dd_blocked, dd_reason = check_dd_circuit_breaker(state)

    # === CHECK EXISTING POSITIONS (even during DD cooldown) ===
    positions_to_close = []
    positions_to_keep = []

    for pos in state["positions"]:
        outcome, exit_price = check_tp_sl(pos, current_price)
        if outcome:
            positions_to_close.append((pos, exit_price, outcome))
            continue

        opened = datetime.fromisoformat(pos["opened_at"])
        age = datetime.now(timezone.utc) - opened
        if age >= timedelta(hours=HOLD_HOURS):
            if pos["direction"] == "LONG":
                outcome = "WIN" if current_price > pos["entry"] else "LOSS"
            else:
                outcome = "WIN" if current_price < pos["entry"] else "LOSS"
            positions_to_close.append((pos, current_price, outcome))
            continue

        positions_to_keep.append(pos)

    for pos, exit_price, outcome in positions_to_close:
        state = close_position(state, pos, exit_price, outcome)

    state["positions"] = positions_to_keep

    # === CHECK FOR NEW ENTRY (blocked during DD cooldown) ===
    if not state["positions"] and signal and not dd_blocked:
        entry = current_price * (1 + SLIPPAGE) if signal == "LONG" else current_price * (1 - SLIPPAGE)

        if signal == "LONG":
            tp = entry * (1 + TP_PCT)
            sl = entry * (1 - SL_PCT)
        else:
            tp = entry * (1 - TP_PCT)
            sl = entry * (1 + SL_PCT)

        risk_amount = state["capital"] * RISK_PCT
        sl_dist = abs(entry - sl)
        size = risk_amount / sl_dist if sl_dist > 0 else 0
        size = min(size, (state["capital"] * LEVERAGE) / entry)

        if size > 0:
            now = datetime.now(timezone.utc)
            pos = {
                "id": f"{signal[0]}_{now.strftime('%Y%m%d_%H%M%S')}",
                "direction": signal,
                "entry": round(entry, 2),
                "tp": round(tp, 2),
                "sl": round(sl, 2),
                "size": round(size, 6),
                "capital_at_entry": round(state["capital"], 2),
                "opened_at": now.isoformat(),
                "reason": signal_info,
            }
            state["positions"].append(pos)

    save_state(state)
    print(format_status(state, signal_info, current_price, dd_blocked, dd_reason))

if __name__ == "__main__":
    main()
