import http.server
import socketserver
import json
import urllib.request
import urllib.error
import os
import sys

def load_env():
    env_path = "/root/.openclaw/workspace/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

# --- CONFIGURATION ---
MODEL_MAPPING = {
    "default": {
        "free_keys": [
            "openai/gpt-5.5",
            "openai/gpt-5.5-pro",
            "openai/gpt-chat-latest",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            "qwen/qwen3.6-flash",
            "qwen/qwen3.6-35b-a3b",
            "qwen/qwen3.6-max-preview",
            "qwen/qwen3.5-plus-20260420",
            "x-ai/grok-4.3",
            "mistralai/mistral-medium-3-5",
            "ibm-granite/granite-4.1-8b",
            "inclusionai/ring-2.6-1t:free",
            "inclusionai/ring-2.6-1t",
            "inclusionai/ling-2.6-1t:free",
            "poolside/laguna-m.1:free",
            "poolside/laguna-xs.2:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "baidu/cobuddy:free",
            "perceptron/perceptron-mk1",
            "google/gemini-3.1-flash-lite",
            "nex-agi/nex-n2-pro:free",
            "minimax/minimax-m3",
            "nvidia/nemotron-3.5-content-safety:free",
            "nvidia/nemotron-3-ultra-550b-a55b",
            "moonshotai/kimi-k2.7-code",
        ],
        "openrouter": ["openrouter/free"],
        "google_key1": [
            "models/gemma-4-31b-it",
            "models/gemma-4-26b-a4b-it",
            "models/gemini-3-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.1-flash-lite-preview",
            "models/gemini-3.5-flash",
            "models/gemini-2.5-flash"
        ],
        "google_key2": [
            "models/gemma-4-31b-it",
            "models/gemma-4-26b-a4b-it",
            "models/gemini-3-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.1-flash-lite-preview",
            "models/gemini-3.5-flash",
            "models/gemini-2.5-flash"
        ],
        "nvidia": "nvidia/nemotron-3-super-120b-a12b"
    },
    "deepseek": {
        "free_keys": [
            "deepseek/deepseek-chat",
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            "openai/gpt-5.5",
            "openai/gpt-5.5-pro",
            "qwen/qwen3.6-flash",
        ],
        "openrouter": ["openrouter/free"],
        "google_key1": [
            "models/gemma-4-31b-it",
            "models/gemma-4-26b-a4b-it",
            "models/gemini-3-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.1-flash-lite-preview",
            "models/gemini-3.5-flash",
            "models/gemini-2.5-flash"
        ],
        "google_key2": [
            "models/gemma-4-31b-it",
            "models/gemma-4-26b-a4b-it",
            "models/gemini-3-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.1-flash-lite-preview",
            "models/gemini-3.5-flash",
            "models/gemini-2.5-flash"
        ],
        "nvidia": "nvidia/nemotron-3-super-120b-a12b"
    }
}

TIERS = [
    {
        "name": "Tier 3 (Free Keys from GitHub)",
        "url": "https://aiapiv2.pekpik.com/v1/chat/completions",
        "auth_type": "multi-key",
        "keys_file": "/root/.openclaw/workspace/free_keys.json",
        "tier_key": "free_keys"
    },
    {
        "name": "Tier 2 (OpenRouter)",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "auth_type": "env-key",
        "key_env_var": "OPENROUTER_API_KEY",
        "tier_key": "openrouter"
    },
    {
        "name": "Tier 1 (Google Key 1)",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "auth_type": "env-key",
        "key_env_var": "PROD_API_KEY",
        "tier_key": "google_key1"
    },
    {
        "name": "Tier 1b (Google Key 2)",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "auth_type": "env-key",
        "key_env_var": "GOOGLE_API_KEY_2",
        "tier_key": "google_key2"
    },
    {
        "name": "Tier 0 (NVIDIA Fallback)",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "auth_type": "env-key",
        "key_env_var": "NVIDIA_API_KEY",
        "tier_key": "nvidia"
    }
]

PORT = 8821

def load_free_keys():
    try:
        keys_file = next((t["keys_file"] for t in TIERS if t["auth_type"] == "multi-key"), None)
        if not keys_file:
            print("[!] No multi-key tier configured.", flush=True)
            return {}
        with open(keys_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Error loading free_keys.json: {e}", flush=True)
        return {}

class MasterTieredHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        raw_data = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_data.decode('utf-8'))
        except Exception as e:
            self.send_error(400, f"Invalid JSON payload: {e}")
            return

        requested_model = payload.get('model', 'default')
        mapping_key = requested_model if requested_model in MODEL_MAPPING else "default"

        print(f"\n[*] Incoming request for model: {requested_model}...", flush=True)

        for tier in TIERS:
            print(f"[*] Attempting {tier['name']}...", flush=True)

            tier_model_config = MODEL_MAPPING[mapping_key].get(tier['tier_key'])
            if tier_model_config is None:
                print(f"    [!] No mapping for tier '{tier['tier_key']}' on model '{mapping_key}'. Skipping.", flush=True)
                continue

            models_to_try = tier_model_config if isinstance(tier_model_config, list) else [tier_model_config]

            for tier_model in models_to_try:
                keys_to_try = []

                if tier['auth_type'] == 'multi-key':
                    free_keys = load_free_keys()
                    keys_to_try = free_keys.get(tier_model, [])
                    if not keys_to_try:
                        print(f"    [!] No available keys for model {tier_model} in free_keys.json. Skipping.", flush=True)
                        continue
                elif tier['auth_type'] == 'env-key':
                    key = os.environ.get(tier['key_env_var'])
                    if key:
                        keys_to_try = [key]
                    else:
                        print(f"    [!] Env var {tier['key_env_var']} not set. Skipping.", flush=True)
                        continue
                else:
                    keys_to_try = [None]

                for key in keys_to_try:
                    key_preview = key[:10] if key else 'None'
                    print(f"    [*] Trying model {tier_model} with key {key_preview}...", flush=True)

                    tier_payload = payload.copy()
                    tier_payload['model'] = tier_model
                    tier_data = json.dumps(tier_payload).encode('utf-8')

                    headers = {'Content-Type': 'application/json'}
                    if key:
                        headers['Authorization'] = f"Bearer {key}"

                    try:
                        req = urllib.request.Request(tier['url'], data=tier_data, headers=headers, method='POST')
                        with urllib.request.urlopen(req, timeout=20) as response:
                            resp_data = response.read()
                            try:
                                resp_json = json.loads(resp_data.decode('utf-8'))
                                if 'choices' in resp_json and len(resp_json['choices']) > 0:
                                    content = resp_json['choices'][0].get('message', {}).get('content', '')
                                    footer = f"\n\n_(Served by: {tier['name']} - {tier_model})_"
                                    resp_json['choices'][0]['message']['content'] = content + footer
                                    resp_data = json.dumps(resp_json).encode('utf-8')
                            except Exception as e:
                                print(f"    [!] Footer injection failed: {repr(e)}. Sending raw.", flush=True)

                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(resp_data)
                            print(f"[✅ SUCCESS] Served via {tier['name']} using model {tier_model}.", flush=True)
                            return

                    except urllib.error.HTTPError as e:
                        print(f"        [⚠️ FAILED] Key returned {e.code}: {e.reason}", flush=True)
                        continue
                    except Exception as e:
                        print(f"        [❌ ERROR] Connection error: {repr(e)}", flush=True)
                        continue

        print("[❌ CRITICAL] All tiers failed.", flush=True)
        self.send_error(502, "All LLM tiers failed to respond.")

    def log_message(self, format, *args):
        # Suppress default HTTP logging (we have our own)
        pass

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    print(f"🚀 Master Tiered Proxy running on port {PORT}", flush=True)
    print(f"Sequence: {' -> '.join([t['name'] for t in TIERS])}", flush=True)
    print(f"------------------------------------------------------------", flush=True)
    with ThreadedHTTPServer(("", PORT), MasterTieredHandler) as httpd:
        httpd.serve_forever()
