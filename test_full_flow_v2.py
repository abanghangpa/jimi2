import subprocess
import time
import requests
import os
import threading

# Configuration
PROXY_SCRIPT = "/root/.openclaw/workspace/fallback_proxy.py"
PROD_KEY = "AIzaSyAuIVbQI46Yuu4DBl6_n2ern9BKG_HVkv4"
FREE_KEY = "sk-fake-key"
PORT = 8000
URL = f"http://localhost:{PORT}/v1/chat/completions"

def proxy_output_reader(pipe):
    for line in iter(pipe.readline, ''):
        print(f"[PROXY LOG] {line.strip()}")

def run_test():
    # 1. Start the proxy
    print("[*] Starting Fallback Proxy...")
    env = os.environ.copy()
    env["PROD_API_KEY"] = PROD_KEY
    
    process = subprocess.Popen(
        ["python3", PROXY_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    # Start a thread to print proxy output in real-time
    threading.Thread(target=proxy_output_reader, args=(process.stdout,), daemon=True).start()
    
    # Wait for it to start
    time.sleep(3)

    # 2. Test the Fallback (using a fake key)
    print("[*] Testing Fallback (Fake Free Key -> Real Google Key)...")
    try:
        response = requests.post(
            URL,
            headers={"Authorization": f"Bearer {FREE_KEY}", "Content-Type": "application/json"},
            json={"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "ping"}]},
            timeout=10
        )
        print(f"\n[RESULT] Status Code: {response.status_code}")
        print(f"[RESULT] Response: {response.text}")
    except Exception as e:
        print(f"\n[RESULT] Request failed: {e}")

    # 3. Clean up
    print("\n[*] Shutting down proxy...")
    process.terminate()
    process.wait()
    print("[*] Done.")

if __name__ == "__main__":
    run_test()
