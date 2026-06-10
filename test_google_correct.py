import os
import json
import urllib.request
import urllib.error

# Load environment variables from .env file
def load_env():
    env_vars = {}
    try:
        with open('/root/.openclaw/workspace/.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key] = value
    except FileNotFoundError:
        pass
    return env_vars

env_vars = load_env()
API_KEY = env_vars.get('PROD_API_KEY', '')
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# Use the model names we saw from the list endpoint
MODELS_TO_TEST = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-2.0-flash",
    "models/gemini-2.0-flash-001",
    "models/gemini-2.0-flash-lite-001"
]

def test_model(model_name):
    print(f"\nTesting model: {model_name}")
    
    data = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}]
    }).encode('utf-8')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}'
    }
    
    req = urllib.request.Request(BASE_URL, data=data, headers=headers, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = response.read().decode('utf-8')
            print(f"✅ SUCCESS: {result[:200]}...")
            return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"❌ HTTP {e.code}: {error_body[:200]}...")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: PROD_API_KEY not set in .env file")
        exit(1)
        
    print(f"Testing with API key: {API_KEY[:10]}...")
    
    success_count = 0
    for model in MODELS_TO_TEST:
        if test_model(model):
            success_count += 1
            
    print(f"\n\nSummary: {success_count}/{len(MODELS_TO_TEST)} models worked")