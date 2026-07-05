import json

with open('scanner_output.json', 'r') as f:
    content = f.read()
    start = content.find('{')
    end = content.rfind('}') + 1
    json_str = content[start:end]
    data = json.loads(json_str)

# Extracting based on the requested report format
report_data = {
    "price": data.get("price"),
    "swing_bias": data.get("swing_bias"),
    "trend_dir": data.get("trend_dir"),
    "ics_score": data.get("ics_score"),
    "direction": data.get("direction"),
    "direction_resolver": data.get("direction_resolver"),
    "magnets": data.get("magnets"),
    "sr_levels": data.get("sr_levels"),
    "derivatives": data.get("derivatives"),
    "taker_summary": data.get("taker_summary"),
    "target_scores": data.get("target_scores"),
    "conflict": data.get("conflict"),
    "m9_regime": data.get("m9", {}).get("regime"),
    "m23": data.get("m23"),
    "multi_strategy": data.get("multi_strategy"),
    "strategy_signal": data.get("strategy_signal"),
    "order_flow": data.get("order_flow"),
    "dual_strategy": data.get("dual_strategy"),
    "narrative": data.get("narrative"),
    "liquidity_levels": data.get("liquidity_levels")
}
print(json.dumps(report_data, indent=2))
