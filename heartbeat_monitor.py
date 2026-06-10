import subprocess
import time
import os
from datetime import datetime

LOG_FILE = "/root/.openclaw/workspace/gateway_heartbeat.log"

def check_latency():
    start = time.time()
    try:
        # Use a lightweight command to check gateway responsiveness
        # 'openclaw gateway status' is a good probe
        result = subprocess.run(
            ["openclaw", "gateway", "status"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        elapsed = time.time() - start
        return elapsed, result.returncode
    except subprocess.TimeoutExpired:
        return 5.0, -1
    except Exception as e:
        return time.time() - start, -2

def monitor():
    print(f"💓 Heartbeat Monitor active. Logging to {LOG_FILE}...")
    
    with open(LOG_FILE, "a") as f:
        f.write(f"--- Monitoring Started: {datetime.now()} ---\n")
        
        while True:
            latency, code = check_latency()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Log the result
            log_line = f"[{timestamp}] Latency: {latency:.3f}s | Code: {code}\n"
            f.write(log_line)
            f.flush()
            
            # Alert to console if latency is high (> 1s)
            if latency > 1.0:
                print(f"⚠️ LATENCY SPIKE: {latency:.3f}s at {timestamp}")
            
            time.sleep(5) # Check every 5 seconds

if __name__ == "__main__":
    monitor()
