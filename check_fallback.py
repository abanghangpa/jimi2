import requests
import json

# Configuration
FREE_PROXY_URL = "https://aiapiv2.pekpik.com/v1/chat/completions"
# We need the key from the config file
CONFIG_PATH = "/root/.openclaw/openclaw.json"
PRODUCTION_MODELS = ["mistral/mistral-large-latest", "google/gemini-2.5-flash"]

def get_free_key():
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
    return config['auth']['profiles']['free-proxy:default']['key']

def test_free_proxy(api_key):
    print(f"[*] Testing Free Proxy (gpt-5.5)...")
    try:
        response = requests.post(
            FREE_PROXY_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "gpt-5.5", "messages": [{"role": "user", "content": "ping"}]},
            timeout=5
        )
        if response.status_code == 200:
            print("[✅ SUCCESS] Free Proxy is active.")
            return True
        else:
            print(f"[❌ FAILED] Free Proxy returned: {response.text}")
            return False
    except Exception as e:
        print(f"[❌ FAILED] Connection error: {e}")
        return False

def main():
    api_key = get_free_key()
    if test_free_proxy(api_key):
        print("\n[STATUS] System is running on FREE TIER.")
    else:
        print("\n[⚠️ ALERT] Free keys exhausted/failed!")
        print(f"[ACTION] Switching to PRODUCTION fallback: {PRODUCTION_MODELS[0]}")

if __name__ == "__main__":
    main()
