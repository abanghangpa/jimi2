#!/usr/bin/env python3
"""
Scanner Live Executor — Places trades via HTX API based on scanner signals.
Handles: signal freshness, fill-based TP/SL, position management, fees.

Usage:
    python scripts/scanner_executor.py              # Live mode
    python scripts/scanner_executor.py --dry-run    # Simulate without placing orders
    python scripts/scanner_executor.py --once       # Run once and exit

Env vars:
    HTX_API_KEY / HTX_API_SECRET  — or set in config/exchange_keys.json
"""
import json, os, sys, time, math, argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# =====================================================================
# CONFIGURATION
# =====================================================================
SCAN_DIR = os.path.join(BASE, "data", "scans")
SIGNALS_FILE = os.path.join(BASE, "data", "strategy_signals.jsonl")
STATE_FILE = os.path.join(BASE, "live", "data", "executor_state.json")
TRADE_LOG = os.path.join(BASE, "live", "data", "executor_trades.json")
LOG_FILE = os.path.join(BASE, "live", "logs", "executor.log")
KEYS_FILE = os.path.join(BASE, "config", "exchange_keys.json")

SYMBOL = "ETH/USDT:USDT"
INITIAL_CAPITAL = 200.0

# === OPTIMIZED STRATEGY CONFIGS (from fee-adjusted backtest) ===
STRATEGY_CONFIGS = {
    "trade_flow": {
        "tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12,
        "direction": "LONG", "enabled": True,
    },
    "funding_arb": {
        "tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12,
        "direction": None, "enabled": True,  # Both directions
    },
    "orderbook_imbalance": {
        "tp_pct": 2.0, "sl_pct": 1.5, "hold_hours": 12,
        "direction": "LONG", "enabled": True,
    },
    "failed_breakout": {
        "tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12,
        "direction": "LONG", "enabled": True,
        "min_conviction": 0.7,
    },
    "cross_asset": {
        "tp_pct": 1.0, "sl_pct": 1.5, "hold_hours": 4,
        "direction": None, "enabled": True,
        "min_conviction": 0.6,
    },
    "structural_break": {
        "tp_pct": 0.5, "sl_pct": 0.5, "hold_hours": 8,
        "direction": "SHORT", "enabled": True,
    },
    "mtf_confluence": {
        "tp_pct": 2.0, "sl_pct": 3.0, "hold_hours": 8,
        "direction": None, "enabled": True,
    },
    "regime_switch": {
        "tp_pct": 2.0, "sl_pct": 3.0, "hold_hours": 12,
        "direction": None, "enabled": True,
    },
    "scalp_v2": {
        "tp_pct": 2.0, "sl_pct": 2.0, "hold_hours": 12,
        "direction": "LONG", "enabled": True,
    },
    "bb_mom6": {
        "tp_pct": 0.5, "sl_pct": 1.0, "hold_hours": 8,
        "direction": "SHORT", "enabled": True,
        "min_conviction": 0.5,
    },
}

# === EXECUTION PARAMS ===
RISK_PCT = 0.02          # 2% risk per trade (conservative)
LEVERAGE = 10            # 10x (conservative, backtest used 10x)
MAX_SLIPPAGE_PCT = 0.30
BLOCKED_HOURS = {19, 20, 21}  # US afternoon - consistent losers
BLOCKED_DAYS = {"Sat"}  # Universally bad day  # Skip if price moved >0.30% from signal (avg slip ~0.15%)
MAX_POSITIONS = 3        # Max concurrent positions
SIGNAL_MAX_AGE_SEC = 1200 # 20 min buffer (scanner runs at bar close, executor may lag)
FEE_PCT = 0.001          # 0.10% round trip (taker both sides)
MIN_CONVICTION = 0.5     # Minimum conviction to trade
ORDER_TYPE = "limit"     # "limit" or "market"
LIMIT_OFFSET_PCT = 0.02  # Place limit 0.02% above/below signal price

# =====================================================================
# LOGGING
# =====================================================================
def log(msg, level="INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# =====================================================================
# STATE MANAGEMENT
# =====================================================================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "capital": INITIAL_CAPITAL,
        "peak_capital": INITIAL_CAPITAL,
        "open_positions": [],
        "closed_trades": [],
        "total_pnl": 0,
        "total_fees": 0,
        "trades_count": 0,
        "wins": 0,
        "losses": 0,
        "timeouts": 0,
        "last_signal_ts": None,
        "dd_cooldown_until": None,
    }

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
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

# =====================================================================
# EXCHANGE CONNECTION
# =====================================================================
def get_exchange(dry_run=False):
    import ccxt

    # Try env vars first, then file
    api_key = os.environ.get("HTX_API_KEY", "")
    api_secret = os.environ.get("HTX_API_SECRET", "")

    if not api_key and os.path.exists(KEYS_FILE):
        with open(KEYS_FILE) as f:
            keys = json.load(f)
            api_key = keys.get("api_key", "")
            api_secret = keys.get("api_secret", "")

    exchange = ccxt.htx({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",
            "defaultMarginMode": "isolated",
        },
    })

    if not dry_run and not api_key:
        log("NO API KEY CONFIGURED — switching to dry-run mode", "WARN")
        dry_run = True

    return exchange, dry_run

# =====================================================================
# SIGNAL LOADING
# =====================================================================
def get_latest_signals():
    """Load the most recent scan file and extract fired signals.
    Reads from multi_strategy.all_signals (list of all strategy signals).
    """
    scan_files = sorted(
        [f for f in os.listdir(SCAN_DIR) if f.startswith("scan_") and f.endswith(".json")],
        reverse=True
    )
    if not scan_files:
        return []

    latest = os.path.join(SCAN_DIR, scan_files[0])
    with open(latest) as f:
        data = json.load(f)

    ts = data.get("timestamp", "")
    price = data.get("price", 0)
    status = data.get("status", "")

    # Read from multi_strategy.all_signals
    multi = data.get("multi_strategy") or {}
    all_signals = multi.get("all_signals", [])

    # Also check single strategy_signal
    single = data.get("strategy_signal", {})
    if single and single.get("direction"):
        # Add single if not already in all_signals
        single_strat = single.get("strategy", "")
        if not any(s.get("strategy") == single_strat for s in all_signals):
            all_signals.append(single)

    signals = []
    for sig_data in all_signals:
        if not isinstance(sig_data, dict):
            continue

        strat_name = sig_data.get("strategy", "")
        cfg = STRATEGY_CONFIGS.get(strat_name)
        if not cfg or not cfg["enabled"]:
            continue

        direction = sig_data.get("direction")
        conviction = sig_data.get("conviction", 0) or 0
        entry = sig_data.get("entry", price)
        sl = sig_data.get("sl", 0)
        tp1 = sig_data.get("tp1", 0)

        min_conv = cfg.get("min_conviction", MIN_CONVICTION)
        if not direction or conviction < min_conv:
            continue

        # Filter by strategy direction config
        if cfg["direction"] and direction != cfg["direction"]:
            continue

        signals.append({
            "strategy": strat_name,
            "timestamp": ts,
            "direction": direction,
            "conviction": conviction,
            "entry": entry or price,
            "sl": sl,
            "tp1": tp1,
            "price": price,
            "cfg": cfg,
            "scan_status": status,
        })

    return signals

# =====================================================================
# SIGNAL FRESHNESS & SLIPPAGE CHECK
# =====================================================================
def is_signal_fresh(signal_ts):
    """Check if signal is less than 15 minutes old."""
    try:
        sig_dt = datetime.strptime(signal_ts, "%Y-%m-%d %H:%M:%S")
        sig_dt = sig_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            sig_dt = datetime.fromisoformat(signal_ts.replace("Z", "+00:00"))
        except:
            return False

    now = datetime.now(timezone.utc)
    age = (now - sig_dt).total_seconds()
    return age <= SIGNAL_MAX_AGE_SEC

def check_slippage(signal_entry, current_price, direction):
    """Check if price moved too far from signal entry."""
    if direction == "LONG":
        slip = (current_price - signal_entry) / signal_entry * 100
    else:
        slip = (signal_entry - current_price) / signal_entry * 100
    return abs(slip), slip

# =====================================================================
# TP/SL CALCULATION (from fill price, not signal entry)
# =====================================================================
def calc_tp_sl(fill_price, direction, tp_pct, sl_pct):
    """Calculate TP and SL based on ACTUAL fill price."""
    if direction == "LONG":
        tp = fill_price * (1 + tp_pct / 100)
        sl = fill_price * (1 - sl_pct / 100)
    else:
        tp = fill_price * (1 - tp_pct / 100)
        sl = fill_price * (1 + sl_pct / 100)
    return tp, sl

# =====================================================================
# POSITION SIZING
# =====================================================================
def calc_position_size(capital, risk_pct, sl_pct, leverage, fill_price):
    """Calculate position size in ETH.
    Risk = capital * risk_pct
    SL distance = sl_pct% of fill_price
    Position size = risk / (sl_distance * leverage)
    """
    risk_amount = capital * risk_pct
    sl_distance = fill_price * sl_pct / 100
    if sl_distance <= 0:
        return 0
    size_eth = risk_amount / (sl_distance * leverage)
    # HTX contract size = 0.01 ETH per contract
    contracts = round(size_eth / 0.01) * 0.01
    return max(contracts, 0.01)  # Min 0.01 ETH

# =====================================================================
# ORDER PLACEMENT
# =====================================================================
def place_order(exchange, direction, size_eth, fill_price, tp, sl, dry_run=False):
    """Place a leveraged order with TP/SL."""
    side = "buy" if direction == "LONG" else "sell"

    # Set leverage
    if not dry_run:
        try:
            exchange.set_leverage(LEVERAGE, SYMBOL, params={"mgnMode": "isolated"})
        except Exception as e:
            log(f"Leverage set warning: {e}", "WARN")

    # Place main order
    if ORDER_TYPE == "limit":
        if direction == "LONG":
            limit_price = fill_price * (1 + LIMIT_OFFSET_PCT / 100)
        else:
            limit_price = fill_price * (1 - LIMIT_OFFSET_PCT / 100)
        limit_price = round(limit_price, 2)

        if dry_run:
            order = {"id": f"dry_{int(time.time())}", "price": limit_price, "status": "closed", "filled": size_eth}
            log(f"DRY RUN: {side} {size_eth} ETH @ ${limit_price}")
        else:
            order = exchange.create_order(SYMBOL, "limit", side, size_eth, limit_price)
            log(f"ORDER PLACED: {side} {size_eth} ETH @ ${limit_price} (id={order['id']})")
    else:
        if dry_run:
            order = {"id": f"dry_{int(time.time())}", "price": fill_price, "status": "closed", "filled": size_eth}
            log(f"DRY RUN: {side} {size_eth} ETH market")
        else:
            order = exchange.create_order(SYMBOL, "market", side, size_eth)
            log(f"ORDER PLACED: {side} {size_eth} ETH market (id={order['id']})")

    # Place TP order (take profit)
    tp_side = "sell" if direction == "LONG" else "buy"
    tp_price = round(tp, 2)
    if not dry_run:
        try:
            tp_order = exchange.create_order(SYMBOL, "limit", tp_side, size_eth, tp_price,
                                              params={"reduceOnly": True, "stopLossPrice": round(sl, 2)})
            log(f"TP ORDER: {tp_side} {size_eth} ETH @ ${tp_price} (id={tp_order['id']})")
        except Exception as e:
            log(f"TP order failed: {e}. Using SL only.", "WARN")
            # Place SL as stop-market
            try:
                sl_order = exchange.create_order(SYMBOL, "market", tp_side, size_eth,
                                                  params={"reduceOnly": True, "stopLossPrice": round(sl, 2)})
                log(f"SL ORDER: stop @ ${round(sl, 2)} (id={sl_order['id']})")
            except Exception as e2:
                log(f"SL order also failed: {e2}", "ERROR")
    else:
        log(f"DRY RUN: TP @ ${tp_price}, SL @ ${round(sl, 2)}")

    actual_fill = order.get("price", fill_price)
    if actual_fill is None or actual_fill == 0:
        actual_fill = fill_price

    return {
        "order_id": order.get("id"),
        "fill_price": float(actual_fill),
        "size": size_eth,
        "tp": tp_price,
        "sl": round(sl, 2),
    }

# =====================================================================
# POSITION MONITORING
# =====================================================================
def check_position_status(exchange, position, current_price):
    """Check if TP/SL/timeout hit for an open position."""
    direction = position["direction"]
    fill_price = position["fill_price"]
    tp = position["tp"]
    sl = position["sl"]
    opened_at = datetime.fromisoformat(position["opened_at"])
    hold_hours = position["hold_hours"]
    now = datetime.now(timezone.utc)

    # Check timeout
    if (now - opened_at).total_seconds() > hold_hours * 3600:
        return "TIMEOUT", current_price

    # Check TP
    if direction == "LONG":
        if current_price >= tp:
            return "WIN", tp
        if current_price <= sl:
            return "LOSS", sl
    else:
        if current_price <= tp:
            return "WIN", tp
        if current_price >= sl:
            return "LOSS", sl

    return "OPEN", current_price

# =====================================================================
# MAIN LOOP
# =====================================================================
def run_once(exchange, state, dry_run=False):
    """Single iteration: check signals, manage positions, place orders."""
    now = datetime.now(timezone.utc)

    # === 1. Check drawdown cooldown ===
    if state.get("dd_cooldown_until"):
        cooldown_end = datetime.fromisoformat(state["dd_cooldown_until"])
        if now < cooldown_end:
            remaining = (cooldown_end - now).total_seconds() / 60
            log(f"DD cooldown active, {remaining:.0f}min remaining")
            return state
        else:
            state["dd_cooldown_until"] = None
            log("DD cooldown expired, resuming trading")

    # === 2. Monitor open positions ===
    try:
        ticker = exchange.fetch_ticker(SYMBOL)
        current_price = ticker["last"]
    except Exception as e:
        log(f"Failed to fetch ticker: {e}", "ERROR")
        current_price = None

    if current_price:
        positions_to_close = []
        for pos in state["open_positions"]:
            status, exit_price = check_position_status(exchange, pos, current_price)
            if status in ("WIN", "LOSS", "TIMEOUT"):
                positions_to_close.append((pos, status, exit_price))

        for pos, status, exit_price in positions_to_close:
            # Close position on exchange
            close_side = "sell" if pos["direction"] == "LONG" else "buy"
            if not dry_run:
                try:
                    close_order = exchange.create_order(SYMBOL, "market", close_side, pos["size"],
                                                         params={"reduceOnly": True})
                    exit_price = close_order.get("average", exit_price) or exit_price
                    log(f"CLOSED: {close_side} {pos['size']} ETH @ ${exit_price}")
                except Exception as e:
                    log(f"Close order failed: {e}", "ERROR")

            # Calculate PnL
            if pos["direction"] == "LONG":
                pnl_pct = (exit_price - pos["fill_price"]) / pos["fill_price"]
            else:
                pnl_pct = (pos["fill_price"] - exit_price) / pos["fill_price"]

            pnl_dollar = state["capital"] * RISK_PCT * pnl_pct / (pos["sl_pct"] / 100)
            fee = pos["size"] * exit_price * FEE_PCT
            net_pnl = pnl_dollar - fee

            state["capital"] += net_pnl
            state["total_pnl"] += net_pnl
            state["total_fees"] += fee
            state["trades_count"] += 1

            if status == "WIN":
                state["wins"] += 1
            elif status == "LOSS":
                state["losses"] += 1
            else:
                state["timeouts"] += 1

            if state["capital"] > state["peak_capital"]:
                state["peak_capital"] = state["capital"]

            # Drawdown check
            dd = (state["peak_capital"] - state["capital"]) / state["peak_capital"]
            if dd > 0.45:
                state["dd_cooldown_until"] = (now + timedelta(hours=24)).isoformat()
                log(f"DD BREAKER: {dd*100:.1f}% — pausing 24h", "WARN")

            # Log trade
            trade_record = {
                "strategy": pos["strategy"],
                "direction": pos["direction"],
                "entry": pos["fill_price"],
                "exit": exit_price,
                "tp": pos["tp"],
                "sl": pos["sl"],
                "size": pos["size"],
                "outcome": status,
                "pnl_dollar": round(net_pnl, 2),
                "fee": round(fee, 2),
                "opened_at": pos["opened_at"],
                "closed_at": now.isoformat(),
                "hold_hours": (now - datetime.fromisoformat(pos["opened_at"])).total_seconds() / 3600,
            }
            log_trade(trade_record)
            state["closed_trades"].append(trade_record)
            state["open_positions"].remove(pos)

            wr = state["wins"] / max(state["wins"] + state["losses"], 1) * 100
            log(f"TRADE CLOSED: {pos['strategy']} {status} | PnL=${net_pnl:+.2f} | "
                f"Cap=${state['capital']:.2f} | WR={wr:.1f}% | {state['wins']}W/{state['losses']}L/{state['timeouts']}T")

    # === 3. Check for new signals ===
    if len(state["open_positions"]) >= MAX_POSITIONS:
        log(f"Max positions ({MAX_POSITIONS}) reached, skipping signal check")
        return state

    signals = get_latest_signals()
    if not signals:
        return state

    for sig in signals:
        # Skip if already have position for this strategy
        if any(p["strategy"] == sig["strategy"] for p in state["open_positions"]):
            continue

        # Freshness check
        if not is_signal_fresh(sig["timestamp"]):
            log(f"STALE signal: {sig['strategy']} at {sig['timestamp']}")
            continue

        # Time/day filter
        try:
            sig_hour = int(sig["timestamp"][11:13])
            sig_wd = datetime.strptime(sig["timestamp"][:10], "%Y-%m-%d").strftime("%a")
        except:
            sig_hour = -1
            sig_wd = ""
        if sig_hour in BLOCKED_HOURS:
            log(f"SKIP {sig["strategy"]}: blocked hour {sig_hour}h")
            continue
        if sig_wd in BLOCKED_DAYS:
            log(f"SKIP {sig["strategy"]}: blocked day {sig_wd}")
            continue

        # Slippage check
        if current_price:
            slip_abs, slip_dir = check_slippage(sig["entry"], current_price, sig["direction"])
            if slip_abs > MAX_SLIPPAGE_PCT:
                log(f"SKIP {sig['strategy']}: slippage {slip_abs:.3f}% > {MAX_SLIPPAGE_PCT}%")
                continue
        else:
            current_price = sig["entry"]

        # Calculate TP/SL from FILL PRICE (not signal entry)
        cfg = sig["cfg"]
        tp, sl = calc_tp_sl(current_price, sig["direction"], cfg["tp_pct"], cfg["sl_pct"])

        # Position sizing
        size = calc_position_size(state["capital"], RISK_PCT, cfg["sl_pct"], LEVERAGE, current_price)
        if size <= 0:
            continue

        # Place order
        log(f"SIGNAL: {sig['strategy']} {sig['direction']} conv={sig['conviction']:.2f} "
            f"entry=${sig['entry']:.2f} fill~${current_price:.2f} TP=${tp:.2f} SL=${sl:.2f}")

        result = place_order(exchange, sig["direction"], size, current_price, tp, sl, dry_run)

        # Track position
        position = {
            "strategy": sig["strategy"],
            "direction": sig["direction"],
            "fill_price": result["fill_price"],
            "tp": result["tp"],
            "sl": result["sl"],
            "size": result["size"],
            "hold_hours": cfg["hold_hours"],
            "tp_pct": cfg["tp_pct"],
            "sl_pct": cfg["sl_pct"],
            "signal_ts": sig["timestamp"],
            "opened_at": now.isoformat(),
            "order_id": result["order_id"],
        }
        state["open_positions"].append(position)
        state["last_signal_ts"] = sig["timestamp"]

        log(f"POSITION OPENED: {sig['strategy']} {sig['direction']} {size} ETH "
            f"@ ${result['fill_price']:.2f} TP=${tp:.2f} SL=${sl:.2f}")

        if len(state["open_positions"]) >= MAX_POSITIONS:
            break

    return state

# =====================================================================
# MAIN
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="Scanner Live Executor")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without placing orders")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")
    args = parser.parse_args()

    dry_run = args.dry_run
    exchange, dry_run = get_exchange(dry_run)
    state = load_state()

    mode = "DRY RUN" if dry_run else "LIVE"
    log(f"=== Scanner Executor Starting ({mode}) ===")
    log(f"Capital: ${state['capital']:.2f} | Positions: {len(state['open_positions'])} | "
        f"Trades: {state['trades_count']} ({state['wins']}W/{state['losses']}L)")

    if args.once:
        state = run_once(exchange, state, dry_run)
        save_state(state)
        return

    while True:
        try:
            state = run_once(exchange, state, dry_run)
            save_state(state)
        except Exception as e:
            log(f"ERROR in main loop: {e}", "ERROR")
            import traceback
            traceback.print_exc()

        if args.once:
            break

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
