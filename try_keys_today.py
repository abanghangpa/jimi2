import json
import os
import sys
import urllib.request
import urllib.error

# Load today's keys (from free_keys.json)
KEYS_FILE = "/root/.openclaw/workspace/free_keys.json"
with open(KEYS_FILE, "r") as f:
    model_keys = json.load(f)

# Free proxy URL
FREE_PROXY_URL = "https://aiapiv2.pekpik.com/v1/chat/completions"

# NVIDIA and Google URLs and keys from environment
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# Load environment variables from .env
def load_env():
    env = {}
    with open("/root/.openclaw/workspace/.env", "r") as f:
        for line in f:
            if '=' in line:
                k, v = line.strip().split('=', 1)
                env[k] = v
    return env

env = load_env()
NVIDIA_KEY = env.get("NVIDIA_API_KEY")
GOOGLE_KEY = env.get("PROD_API_KEY")

def try_free_proxy(model, key):
    """Try the free proxy with a given model and key."""
    data = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "max_tokens": 5
    }
    req = urllib.request.Request(FREE_PROXY_URL, 
                                 data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': f"Bearer {key}"},
                                 method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8'), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

def try_nvidia():
    """Try NVIDIA API."""
    if not NVIDIA_KEY:
        return None, Exception("NVIDIA_API_KEY not set")
    data = {
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "max_tokens": 5
    }
    req = urllib.request.Request(NVIDIA_URL,
                                 data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': f"Bearer {NVIDIA_KEY}"},
                                 method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8'), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

def try_google():
    """Try Google Gemini API."""
    if not GOOGLE_KEY:
        return None, Exception("PROD_API_KEY not set")
    data = {
        "model": "gemini-2.5-flash",
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "max_tokens": 5
    }
    req = urllib.request.Request(GOOGLE_URL,
                                 data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': f"Bearer {GOOGLE_KEY}"},
                                 method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8'), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

def main():
    # Try each model and each key for that model
    for model, keys in model_keys.items():
        for key in keys:
            print(f"Trying free proxy: model={model}, key={key[:10]}...")
            resp, error = try_free_proxy(model, key)
            if resp is not None:
                print(f"[SUCCESS] Free proxy worked with model={model}")
                print(resp)
                return 0
            else:
                print(f"[FAILED] {error}")
    
    print("\nAll free keys failed. Trying NVIDIA...")
    resp, error = try_nvidia()
    if resp is not None:
        print("[SUCCESS] NVIDIA worked")
        print(resp)
        return 0
    else:
        print(f"[FAILED] NVIDIA: {error}")
    
    print("\nNVIDIA failed. Trying Google Gemini...")
    resp, error = try_google()
    if resp is not None:
        print("[SUCCESS] Google Gemini worked")
        print(resp)
        return 0
    else:
        print(f"[FAILED] Google Gemini: {error}")
    
    print("\nAll fallbacks failed.")
    return 1

if __name__ == "__main__":
    sys.exit(main())