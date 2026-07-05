import json, glob, os, statistics
from datetime import datetime

scan_dir = "/root/.openclaw/workspace/jimi_audit/data/scans/"
files = sorted(glob.glob(os.path.join(scan_dir, "*.json")))
print(f"Total scan files: {len(files)}")

ics_scores = []
directions = {"LONG": 0, "SHORT": 0, "NEUTRAL": 0}
signals = []
regimes = {}
modules = {}  # module_name -> {"agree":0, "disagree":0, "total":0}
daily_stats = {}

for f in files:
    try:
        with open(f) as fp:
            d = json.load(fp)
        ts = d.get("timestamp", os.path.basename(f).replace(".json",""))
        
        ics = d.get("ics")
        if ics is not None:
            ics_scores.append(float(ics))
        
        sig = d.get("direction", "UNKNOWN")
        directions[sig] = directions.get(sig, 0) + 1
        
        # regime from m9.regime if available
        regime = None
        m9 = d.get("m9")
        if isinstance(m9, dict):
            regime = m9.get("regime")
        if regime is None:
            regime = "unknown"
        regimes[regime] = regimes.get(regime, 0) + 1
        
        # modules: keys that start with 'm' followed by digits
        for key, val in d.items():
            if isinstance(key, str) and key.startswith('m') and len(key) > 1 and key[1:].isdigit():
                # it's a module key like m1, m2, etc.
                if key not in modules:
                    modules[key] = {"agree": 0, "disagree": 0, "total": 0}
                modules[key]["total"] += 1
                if isinstance(val, dict):
                    # try to get signal from the module
                    mod_sig = val.get("signal")
                    if mod_sig is not None:
                        if mod_sig == sig:
                            modules[key]["agree"] += 1
                        else:
                            modules[key]["disagree"] += 1
                    # else: no signal, skip for agreement
        # end for modules
        
        day = str(ts)[:10]
        if day not in daily_stats:
            daily_stats[day] = {"ics": [], "signals": []}
        if ics is not None:
            daily_stats[day]["ics"].append(float(ics))
        daily_stats[day]["signals"].append(sig)
    except Exception as e:
        # print(f"Error processing {f}: {e}")
        continue

print("\n=== ICS Score Stats ===")
if ics_scores:
    print(f"Mean: {statistics.mean(ics_scores):.4f}")
    print(f"Median: {statistics.median(ics_scores):.4f}")
    print(f"Stdev: {statistics.stdev(ics_scores):.4f}")
    print(f"Min: {min(ics_scores):.4f}")
    print(f"Max: {max(ics_scores):.4f}")
    
    buckets = {"<0.40": 0, "0.40-0.50": 0, "0.50-0.55": 0, "0.55-0.60": 0, "0.60-0.65": 0, "0.65+": 0}
    for s in ics_scores:
        if s < 0.40: buckets["<0.40"] += 1
        elif s < 0.50: buckets["0.40-0.50"] += 1
        elif s < 0.55: buckets["0.50-0.55"] += 1
        elif s < 0.60: buckets["0.55-0.60"] += 1
        elif s < 0.65: buckets["0.60-0.65"] += 1
        else: buckets["0.65+"] += 1
    print(f"\nICS Buckets: {json.dumps(buckets)}")

print("\n=== Direction Distribution ===")
total = sum(directions.values())
for d, c in sorted(directions.items(), key=lambda x: -x[1]):
    pct = (c/total*100) if total else 0
    print(f"  {d}: {c} ({pct:.1f}%)")

print("\n=== Regime Distribution ===")
for r, c in sorted(regimes.items(), key=lambda x: -x[1]):
    print(f"  {r}: {c}")

print("\n=== Module Agreement ===")
for m, v in sorted(modules.items(), key=lambda x: -x[1]["agree"]/max(x[1]["total"],1)):
    rate = (v["agree"]/v["total"]*100) if v["total"] else 0
    print(f"  {m}: {rate:.1f}% agree ({v['agree']}/{v['total']})")

print("\n=== Daily Trends (last 7 days) ===")
for day in sorted(daily_stats.keys())[-7:]:
    ds = daily_stats[day]
    avg_ics = statistics.mean(ds["ics"]) if ds["ics"] else 0
    longs = ds["signals"].count("LONG")
    shorts = ds["signals"].count("SHORT")
    print(f"  {day}: avg_ics={avg_ics:.4f}, LONG={longs}, SHORT={shorts}")
