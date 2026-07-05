#!/usr/bin/env python3
"""
Paper Trading Engine - BB Mean Rev + Volatility Gate
Signal: Price < lower BB (LONG), Price > upper BB (SHORT)
Gate: 48h avg abs 12h momentum >= 2% (skip dead markets)
Params: TP 0.30%, SL 0.20%, 20x leverage, 5% risk, 8h hold
DD Circuit Breaker: stop trading for 24h when drawdown hits 45%
"""
import json, os, requests, glob
from datetime import datetime, timezone, timedelta

BASE = "/root/.openclaw/workspace/jimi_audit"
POSITIONS_FILE = os.path.join(BASE, "data", "paper_positions.json")
TRADE_LOG = os.path.join(BASE, "data", "paper_trades.json")
SCAN_DIR = os.path.join(BASE, "data", "scans")

# === BACKTESTED PARAMETERS ===
TP_PCT = 0.003       # 0.30%
SL_PCT = 0.002       # 0.20%
RISK_PCT = 0.05      # 5% of capital per trade
LEVERAGE = 20        # 20x
HOLD_HOURS = 8       # 8 hour hold
FEE_RATE = 0.0002    # HTX maker fee 0.02% per side
SLIPPAGE = 0.001     # 0.1% slippage
INITIAL_CAPITAL = 200.0

# === BOLLINGER BANDS ===
BB_PERIOD = 20       # 20-period SMA
BB_STD_MULT = 2.0    # 2 standard deviations

# === VOLATILITY GATE (48h avg abs 12h momentum) ===
MOM_PERIOD = 12      # 12-hour momentum lookback
MOM_GATE_PERIOD = 48 # 48h rolling window
MOM_GATE_THRESHOLD = 0.02  # Skip when avg abs momentum < 2.0%

# === DRAWDOWN CIRCUIT BREAKER ===
DD_STOP = 0.45
DD_COOLDOWN_HOURS = 24

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

def get_recent_candles(limit=70):
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit={limit}",
            timeout=10
        )
        return r.json()
    except:
        return None

def compute_bb(candles, period=BB_PERIOD, mult=BB_STD_MULT):
    closes = [float(c[4]) for c in candles]
    if len(closes) < period:
        return None, None, None
    seg = closes[-period:]
    mid = sum(seg) / period
    std = (sum((x - mid) ** 2 for x in seg) / period) ** 0.5
    upper = mid + mult * std
    lower = mid - mult * std
    return upper, lower, mid

def get_vol_gate(candles):
    closes = [float(c[4]) for c in candles]
    if len(closes) < MOM_GATE_PERIOD + MOM_PERIOD + 1:
        return None, "insufficient_data"
    moms = []
    for i in range(MOM_PERIOD, len(closes)):
        p_now = closes[i]
        p_past = closes[i - MOM_PERIOD]
        if p_past > 0:
            moms.append(abs((p_now - p_past) / p_past))
    if len(moms) < MOM_GATE_PERIOD:
        return None, "insufficient_data"
    avg_mom = sum(moms[-MOM_GATE_PERIOD:]) / MOM_GATE_PERIOD
    return avg_mom, f"vol_gate={avg_mom*100:.2f}%"

def get_signal():
    candles = get_recent_candles(limit=MOM_GATE_PERIOD + MOM_PERIOD + 5)
    if not candles or len(candles) < BB_PERIOD + 1:
        return None, "insufficient_data"

    current_price = float(candles[-1][4])
    bb_upper, bb_lower, bb_mid = compute_bb(candles)
    if bb_upper is None:
        return None, "bb_insufficient_data"

    avg_mom, gate_info = get_vol_gate(candles)

    if avg_mom is not None and avg_mom < MOM_GATE_THRESHOLD:
        bb_info = f"BB[{bb_lower:.2f}-{bb_upper:.2f}]"
        reason = f"LOW_VOL: {gate_info} < {MOM_GATE_THRESHOLD*100:.1f}% | {bb_info} | price={current_price:.2f}"
        return None, reason

    bb_width = (bb_upper - bb_lower) / bb_mid * 100 if bb_mid > 0 else 0
    bb_info = f"BB[{bb_lower:.2f}-{bb_upper:.2f}] w={bb_width:.1f}%"

    if current_price < bb_lower:
        return "LONG", f"BELOW_LOWER: {bb_info} | {gate_info} | price={current_price:.2f}"
    elif current_price > bb_upper:
        return "SHORT", f"ABOVE_UPPER: {bb_info} | {gate_info} | price={current_price:.2f}"
    else:
        return None, f"INSIDE_BB: {bb_info} | {gate_info} | price={current_price:.2f}"

def check_dd_circuit_breaker(state):
    capital = state["capital"]
    peak = state.get("peak_capital", INITIAL_CAPITAL)

    if capital > peak:
        state["peak_capital"] = capital
        peak = capital

    cooldown_until = state.get("dd_cooldown_until")
    if cooldown_until:
        cooldown_dt = datetime.fromisoformat(cooldown_until)
        if datetime.now(timezone.utc) < cooldown_dt:
            return True, f"DD cooldown until {cooldown_until[:16]}"
        else:
            state["dd_cooldown_until"] = None

    if peak > 0:
        dd = (peak - capital) / peak
        if dd >= DD_STOP:
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

    msg = "BB MEAN REV + GATE\n"
    msg += f"Time: {now}\n"
    msg += f"ETH: ${current_price:,.2f}\n"
    msg += f"Signal: {signal_info}\n"
    msg += f"\nParams: TP {TP_PCT*100:.2f}% | SL {SL_PCT*100:.2f}% | {HOLD_HOURS}h hold | {LEVERAGE}x | {RISK_PCT*100:.0f}% risk\n"
    msg += f"BB: {BB_PERIOD} period, {BB_STD_MULT}σ | Gate: {MOM_GATE_PERIOD}h mom >= {MOM_GATE_THRESHOLD*100:.0f}%\n"
    msg += f"DD Breaker: {DD_STOP*100:.0f}% stop, {DD_COOLDOWN_HOURS}h cooldown\n"
    msg += f"Capital: ${capital:,.2f} ({ret:.1f}x) | Peak: ${peak:,.2f} | DD: {dd_pct:.1f}%\n"
    msg += f"P&L: ${state['total_pnl']:,.2f} | Fees: ${state['fees_paid']:.4f}\n"

    t = state["trades_count"]
    w = state["wins"]
    wr = (w / t * 100) if t > 0 else 0
    msg += f"Trades: {t} ({w}W/{t-w}L) WR {wr:.0f}% | DD triggers: {state.get('dd_triggered_count', 0)}\n"

    if dd_blocked:
        msg += f"\n!! CIRCUIT BREAKER: {dd_reason}\n"

    if state["positions"]:
        msg += f"\nOpen:\n"
        for pos in state["positions"]:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(pos["opened_at"])
            age_h = age.total_seconds() / 3600
            if pos["direction"] == "LONG":
                unrealized = (current_price - pos["entry"]) / pos["entry"] * 100
            else:
                unrealized = (pos["entry"] - current_price) / pos["entry"] * 100
            icon = "+" if unrealized >= 0 else "-"
            msg += f"  {icon} {pos['direction']} @ ${pos['entry']:.2f} | "
            msg += f"TP ${pos['tp']:.2f} SL ${pos['sl']:.2f} | "
            msg += f"P&L {unrealized:+.2f}% | {age_h:.1f}h\n"
    else:
        msg += "\nNo open positions.\n"

    if state["closed"]:
        msg += f"\nRecent:\n"
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

    signal, signal_info = get_signal()

    dd_blocked, dd_reason = check_dd_circuit_breaker(state)

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
