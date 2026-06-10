import subprocess
import os
import time
import re
from datetime import datetime

LOG_FILE = "/tmp/openclaw/openclaw-2026-05-28.log" # Updated daily in production
AUDIT_LOG = "/root/.openclaw/workspace/stability_audit.log"
TARGET_ERRORS = [
    "previous run did not finish cleanly",
    "EmbeddedAttemptSessionTakeoverError",
    "timeout reached",
    "fetch timeout",
    "lane wait exceeded"
]

def take_snapshot(error_msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] 🚨 Stability Event Detected! Taking snapshot...")
    
    with open(AUDIT_LOG, "a") as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"🚨 STABILITY EVENT: {timestamp}\n")
        f.write(f"Error: {error_msg}\n")
        f.write(f"{'='*80}\n\n")
        
        # 1. Process Snapshot
        f.write("--- PROCESS LIST (ps aux) ---\n")
        f.write(subprocess.check_output(["ps", "aux"], text=True))
        f.write("\n\n")
        
        # 2. Lock File Snapshot
        f.write("--- SESSION LOCKS ---\n")
        try:
            locks = subprocess.check_output(["ls", "-la", "/root/.openclaw/agents/main/sessions/*.lock"], text=True)
            f.write(locks)
        except subprocess.CalledProcessError:
            f.write("No lock files found.\n")
        f.write("\n\n")
        
        # 3. Network Snapshot
        f.write("--- NETWORK STATE (netstat) ---\n")
        try:
            net = subprocess.check_output(["netstat", "-tulnp"], text=True)
            f.write(net)
        except Exception as e:
            f.write(f"Could not capture netstat: {e}\n")
        f.write("\n\n")
        
        # 4. Log Context
        f.write("--- GATEWAY LOG CONTEXT (Last 50 lines) ---\n")
        try:
            context = subprocess.check_output(["tail", "-n", "50", LOG_FILE], text=True)
            f.write(context)
        except Exception as e:
            f.write(f"Could not capture log context: {e}\n")
        f.write("\n\n")
        f.write(f"{'='*80}\n")

def monitor_logs():
    print(f"🔍 Stability Sentinel active. Monitoring {LOG_FILE} for run errors...")
    
    # Start at the end of the file
    with open(LOG_FILE, "r") as f:
        f.seek(0, os.SEEK_END)
        
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1) # Don't burn CPU
                continue
            
            for error in TARGET_ERRORS:
                if error in line:
                    take_snapshot(line.strip())
                    break

if __name__ == "__main__":
    # Ensure the log file exists before starting
    if not os.path.exists(LOG_FILE):
        print(f"Waiting for {LOG_FILE} to be created...")
        while not os.path.exists(LOG_FILE):
            time.sleep(1)
            
    monitor_logs()
