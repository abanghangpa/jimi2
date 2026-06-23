#!/usr/bin/env python3
"""Run scanner and output compact JSON with only report-relevant fields."""
import subprocess, sys, json, os

SCANNER = os.path.join(os.path.dirname(__file__), "scanner.py")
PYTHON = "/root/.openclaw/workspace/jimi_venv/bin/python"
SCAN_FILE = "/root/.openclaw/workspace/latest_scan.json"

def main():
    # Run scanner
    subprocess.run([PYTHON, SCANNER, "--json"], capture_output=True, text=True, timeout=120)
    
    # Read from file (scanner always writes here)
    if not os.path.exists(SCAN_FILE):
        print(json.dumps({"error": "Scanner did not produce output"}))
        sys.exit(1)
    
    with open(SCAN_FILE) as f:
        d = json.load(f)
    
    # exchange_activity: extract dominant exchange summary
    ea = d.get("exchange_activity", {})
    ea_snaps = ea.get("snapshots", {})
    dominant = None
    max_oi = 0
    for name, snap in ea_snaps.items():
        oi = snap.get("oi", 0) or 0
        if oi > max_oi:
            max_oi = oi
            dominant = {"exchange": name, "funding_rate": snap.get("funding_rate"), "oi": oi, "ls_ratio": snap.get("ls_ratio")}
    
    # derivatives summary
    deriv = d.get("derivatives", {})
    
    # cascade summary
    cascade = d.get("cascade", {})
    
    # direction_resolver
    dr = d.get("direction_resolver", {})
    
    # dual_strategy
    ds = d.get("dual_strategy", {})
    base = ds.get("base", {})
    strat_a = ds.get("strategy_a", {})
    strat_b = ds.get("strategy_b", {})
    
    # sr_levels: list of [price, volume, type, ...]
    sr_raw = d.get("sr_levels", [])
    supports = [x for x in sr_raw if len(x) >= 3 and x[2] == "SUPPORT"]
    resistances = [x for x in sr_raw if len(x) >= 3 and x[2] == "RESISTANCE"]
    
    # magnets: list of [price, vol, type]
    magnets = d.get("magnets", [])[:3]
    
    # m75
    m75 = d.get("m75", {})
    
    # macro
    macro_ind = d.get("macro_indicators", {})
    macro_alert = d.get("macro_alert_active", False)
    
    brief = {
        "timestamp": d.get("timestamp"),
        "price": d.get("price"),
        "status": d.get("status"),
        "reason": d.get("reason"),
        "timeframe": d.get("timeframe"),
        "ics": d.get("ics"),
        "swing_bias": d.get("swing_bias"),
        "direction": d.get("direction"),
        "rsi": d.get("rsi"),
        "atr": d.get("atr"),
        "squeeze": d.get("squeeze"),
        "direction_resolver": {
            "direction": dr.get("direction"),
            "action": dr.get("action"),
            "reason": dr.get("reason"),
            "size_mult": dr.get("size_mult"),
        },
        "dual_strategy": {
            "base_price": base.get("price"),
            "base_regime": base.get("regime"),
            "base_direction": base.get("direction"),
            "base_swing_bias": base.get("swing_bias"),
            "strategy_a_status": strat_a.get("status"),
            "strategy_a_reason": strat_a.get("reason"),
            "strategy_a_mode": strat_a.get("mode"),
            "strategy_b_status": strat_b.get("status"),
            "strategy_b_reason": strat_b.get("reason"),
            "strategy_b_mode": strat_b.get("mode"),
        },
        "m9_regime": d.get("m9", {}).get("regime"),
        "cascade": {
            "combined_score": cascade.get("combined_score"),
            "combined_signal": cascade.get("combined_signal"),
            "active_cascades": cascade.get("active_cascades", []),
        },
        "exchange_activity": {
            "dominant": dominant,
        },
        "derivatives": {
            "oi": deriv.get("oi"),
            "oi_usd": deriv.get("oi_usd"),
            "oi_roc_1h": deriv.get("oi_roc_1h"),
            "ls_ratio": deriv.get("ls_ratio"),
            "long_pct": deriv.get("long_pct"),
            "short_pct": deriv.get("short_pct"),
            "positioning": deriv.get("positioning"),
            "whale_signal": deriv.get("whale_signal"),
            "funding_rate": deriv.get("funding_rate"),
            "futures_flow": deriv.get("futures_flow"),
        },
        "magnets": magnets,
        "sr_levels": {
            "top_resistance": resistances[:3] if resistances else [],
            "top_support": supports[:3] if supports else [],
        },
        "macro_indicators": macro_ind,
        "macro_alert_active": macro_alert,
        "m75": {
            "score": m75.get("score"),
            "status": m75.get("status"),
        },
    }
    
    print(json.dumps(brief, indent=2, default=str))

if __name__ == "__main__":
    main()
