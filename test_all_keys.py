import json
import urllib.request
import urllib.error
import sys

KEYS_FILE = "/root/.openclaw/workspace/free_keys.json"
FREE_PROXY_URL = "https://aiapiv2.pekpik.com/v1/chat/completions"

def try_key(model, key):
    data = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hi in one word"}],
        "max_tokens": 5
    }
    req = urllib.request.Request(FREE_PROXY_URL,
                                 data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': f"Bearer {key}"},
                                 method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode('utf-8'), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

def main():
    with open(KEYS_FILE, "r") as f:
        model_keys = json.load(f)
    for model, keys in model_keys.items():
        for key in keys:
            print(f"Trying model={model} key={key[:12]}...", flush=True)
            resp, err = try_key(model, key)
            if resp is not None:
                print(f"SUCCESS: model={model}")
                print(resp)
                return 0
            else:
                print(f"FAILED: {err}")
    print("All free keys failed.")
    return 1

if __name__ == "__main__":
    sys.exit(main())