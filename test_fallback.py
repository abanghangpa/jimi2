import os
import time
import subprocess
import sys
import json
import urllib.request
import urllib.error

def kill_processes():
    subprocess.run(["pkill", "-f", "master_tiered_proxy.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    # Start Ollama in the background
    time.sleep(3)  # let it start
    return proc

def start_proxy(env):
    # Start the proxy in the background
    proc = subprocess.Popen(
        ["python3", "master_tiered_proxy.py"],
        stdout=open("master_proxy.log", "w"),
        stderr=subprocess.STDOUT,
        env=env
    )
    time.sleep(3)  # let it start
    return proc

def make_request():
    data = json.dumps({
        "model": "default",
        "messages": [{"role": "user", "content": "Say hello in one word"}]
    }).encode('utf-8')
    req = urllib.request.Request(
        'http://localhost:8000/v1/chat/completions',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        return f"Error: {e}"

def main():
    kill_processes()

    # Start Ollama (so the service is running, but we'll use a non-existent model)
    print("Ollama started")

    # Environment: empty PROD_API_KEY to make Tier 1 fail, keep NVIDIA_API_KEY, and empty free_keys.json
    env = os.environ.copy()
    env["PROD_API_KEY"] = ""  # invalidate Google key
    # NVIDIA_API_KEY and FREE_PROXY_KEY are already in the environment from .env, but we'll keep them

    # Backup and empty free_keys.json
    if os.path.exists("free_keys.json"):
        os.rename("free_keys.json", "free_keys.json.backup")
    with open("free_keys.json", "w") as f:
        json.dump({}, f)

    proxy_proc = start_proxy(env)
    print("Proxy started")

    try:
        response = make_request()
        print("\n=== Response ===")
        print(response)
        print("================\n")

        # Check the log to see which tier was used
        print("=== Proxy Log (last 20 lines) ===")
        if os.path.exists("master_proxy.log"):
            with open("master_proxy.log", "r") as f:
                lines = f.readlines()
                for line in lines[-20:]:
                    print(line.rstrip())
        print("=================================\n")

    finally:
        # Cleanup
        kill_processes()
        # Restore free_keys.json if we backed it up
        if os.path.exists("free_keys.json.backup"):
            os.rename("free_keys.json.backup", "free_keys.json")

if __name__ == "__main__":
    main()
