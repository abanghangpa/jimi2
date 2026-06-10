import json

config_path = '/root/.openclaw/openclaw.json'
key = 'sk-ahXL4sXYXwlzxweIJg9Ryk4cC8j4OvHSkeGEQJ4uGyCl4z8R'

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
except Exception as e:
    print(f"Error reading config: {e}")
    exit(1)

# 1. Add Provider
new_provider = {
    "baseUrl": "https://aiapiv2.pekpik.com/v1",
    "api": "openai-completions",
    "models": [
        {
            "id": "gpt-5.5",
            "name": "GPT-5.5 (Free)",
            "reasoning": False,
            "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 128000,
            "maxTokens": 4096
        },
        {
            "id": "claude-opus-4-7",
            "name": "Claude Opus 4.7 (Free)",
            "reasoning": False,
            "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 200000,
            "maxTokens": 4096
        }
    ]
}
config['models']['providers']['free-proxy'] = new_provider

# 2. Add Profile
new_profile = {
    "provider": "free-proxy",
    "mode": "api_key",
    "key": key
}
config['auth']['profiles']['free-proxy:default'] = new_profile

try:
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print("Successfully patched config.")
except Exception as e:
    print(f"Error writing config: {e}")
    exit(1)
