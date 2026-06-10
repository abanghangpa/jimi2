import http.server
import socketserver
import json
import urllib.request
import urllib.error
import os
import sys

# --- CONFIGURATION ---
MODEL_MAPPING = {
    "default": {
        "tier2": ["gpt-5.5", "claude-opus-4-7", "gemini-2.5-pro", "deepseek-chat"],
        "tier1": [
            "models/gemma-4-31b-it",
            "models/gemma-4-26b-a4b-it",
            "models/gemini-3-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.1-flash-lite-preview",
            "models/gemini-3.5-flash",
            "models/gemini-2.5-flash"
        ],
        "tier0": "nvidia/nemotron-3-super-120b-a12b"
    },
    "deepseek": {
        "tier2": ["deepseek-chat", "gpt-5.5", "claude-opus-4-7"],
        "tier1": [
            "models/gemma-4-31b-it",
            "models/gemma-4-26b-a4b-it",
            "models/gemini-3-flash",
            "models/gemini-2.5-flash-lite",
            "models/gemini-3.1-flash-lite-preview",
            "models/gemini-3.5-flash",
            "models/gemini-2.5-flash"
        ],
        "tier0": "nvidia/nemotron-3-super-120b-a12b"
    }
}

TIERS = [
    {
        "name": "Tier 2 (Free-Proxy)",
        "url": "https://aiapiv2.pekpik.com/v1/chat/completions",
        "auth_type": "multi-key",
        "keys_file": "/root/.openclaw/workspace/free_keys.json",
        "tier_key": "tier2"
    },
    {
        "name": "Tier 1 (Production - Google Gemini)",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "auth_type": "key",
        "key_env_var": "PROD_API_KEY",
        "tier_key": "tier1"
    },
    {
        "name": "Tier 0 (Final Fallback - NVIDIA)",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "auth_type": "key",
        "key_env_var": "NVIDIA_API_KEY",
        "tier_key": "tier0"
    }
]

PORT = 8000

def load_free_keys():
    try:
        # Find the tier that uses multi-key auth to get the keys_file path
        keys_file = next((t["keys_file"] for t in TIERS if t["auth_type"] == "multi-key"), None)
        if not keys_file:
            print("[!] No multi-key tier configured. Cannot load free_keys.json.", flush=True)
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

        print(f"\n[*] Incoming request for model: {payload.get('model')}...", flush=True)

        for tier in TIERS:
            print(f"[*] Attempting {tier['name']}...", flush=True)
            
            requested_model = payload.get('model', 'default')
            mapping_key = requested_model if requested_model in MODEL_MAPPING else "default"
            tier_model_config = MODEL_MAPPING[mapping_key][tier['tier_key']]
            
            models_to_try = tier_model_config if isinstance(tier_model_config, list) else [tier_model_config]
            
            for tier_model in models_to_try:
                # Determine which keys to use for this specific model
                keys_to_try = []
                if tier['auth_type'] == 'multi-key':
                    free_keys = load_free_keys()
                    keys_to_try = free_keys.get(tier_model, [])
                    if not keys_to_try:
                        print(f"    [!] No available keys for model {tier_model} in free_keys.json. Skipping.", flush=True)
                        continue
                elif tier['auth_type'] == 'key':
                    key = os.environ.get(tier['key_env_var'])
                    if key:
                        keys_to_try = [key]
                    else:
                        print(f"    [!] Error: Env var {tier['key_env_var']} not set. Skipping.", flush=True)
                        continue
                else:
                    # No auth (Tier 3)
                    keys_to_try = [None]

                for key in keys_to_try:
                    print(f"    [*] Trying model {tier_model} with key {key[:10] if key else 'None'}...", flush=True)
                    
                    tier_payload = payload.copy()
                    tier_payload['model'] = tier_model
                    tier_data = json.dumps(tier_payload).encode('utf-8')
                    
                    headers = { 'Content-Type': 'application/json' }
                    if key:
                        headers['Authorization'] = f"Bearer {key}"

                    try:
                        req = urllib.request.Request(tier['url'], data=tier_data, headers=headers, method='POST')
                        with urllib.request.urlopen(req, timeout=15) as response:
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

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    print(f"🚀 Master Tiered Proxy running on port {PORT}", flush=True)
    print(f"Sequence: {' -> '.join([t['name'] for t in TIERS])}", flush=True)
    print(f"------------------------------------------------------------", flush=True)
    with ThreadedHTTPServer(("", PORT), MasterTieredHandler) as httpd:
        httpd.serve_forever()