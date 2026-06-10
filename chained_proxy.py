import http.server
import socketserver
import json
import urllib.request
import urllib.error
import os
import sys

# --- CONFIGURATION ---
FREE_PROXY_URL = "https://aiapiv2.pekpik.com/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
PORT = 8000
KEYS_FILE = "/root/.openclaw/workspace/free_keys.json"

def load_keys():
    try:
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[⚠️ WARNING] Could not load keys: {e}")
        return {}

def try_free_proxy(request_data, auth_key):
    """Try the free proxy with a given key."""
    req = urllib.request.Request(FREE_PROXY_URL, data=json.dumps(request_data).encode('utf-8'), headers={
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {auth_key}"
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read(), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

def try_nvidia(request_data):
    """Try NVIDIA API."""
    nvidia_key = os.environ.get("NVIDIA_API_KEY")
    if not nvidia_key:
        return None, Exception("NVIDIA_API_KEY not set")
    req = urllib.request.Request(NVIDIA_URL, data=json.dumps(request_data).encode('utf-8'), headers={
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {nvidia_key}"
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read(), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

def try_google(request_data):
    """Try Google Gemini API."""
    google_key = os.environ.get("PROD_API_KEY")
    if not google_key:
        return None, Exception("PROD_API_KEY not set")
    req = urllib.request.Request(GOOGLE_URL, data=json.dumps(request_data).encode('utf-8'), headers={
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {google_key}"
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read(), None
    except urllib.error.HTTPError as e:
        return None, e
    except Exception as e:
        return None, e

class ChainedHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        # Parse the request body to get model (if any) and pass it through.
        try:
            request_data = json.loads(post_data.decode('utf-8'))
        except Exception:
            # If not JSON, just forward as is? We'll assume JSON.
            request_data = {"messages": [{"role": "user", "content": post_data.decode('utf-8')}]}
        
        print(f"[*] Incoming request. Trying free proxy keys...")
        
        # Load keys
        keys_dict = load_keys()
        # Flatten keys: list of (model, key) but we don't need model for trying, just try all.
        all_keys = []
        for model, keys in keys_dict.items():
            for key in keys:
                all_keys.append(key)
        
        # Try each free key
        free_success = False
        for key in all_keys:
            resp_body, error = try_free_proxy(request_data, key)
            if resp_body is not None:
                print("[✅ SUCCESS] Free proxy key worked.")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(resp_body)
                free_success = True
                return
            else:
                print(f"[⚠️ FAILED] Free proxy key error: {error}")
        
        print("[*] All free keys failed. Trying NVIDIA...")
        # Try NVIDIA
        resp_body, error = try_nvidia(request_data)
        if resp_body is not None:
            print("[✅ SUCCESS] NVIDIA worked.")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(resp_body)
            return
        else:
            print(f"[⚠️ FAILED] NVIDIA error: {error}")
        
        print("[*] NVIDIA failed. Trying Google Gemini...")
        # Try Google
        resp_body, error = try_google(request_data)
        if resp_body is not None:
            print("[✅ SUCCESS] Google Gemini worked.")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(resp_body)
            return
        else:
            print(f"[❌ CRITICAL] Google Gemini also failed: {error}")
            self.send_error(502, f"All fallbacks failed: {error}")

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    # Ensure environment variables are set
    if not os.environ.get("NVIDIA_API_KEY"):
        print("[⚠️ WARNING] NVIDIA_API_KEY not set in environment.")
    if not os.environ.get("PROD_API_KEY"):
        print("[⚠️ WARNING] PROD_API_KEY not set in environment.")
    
    print(f"🚀 Chained Proxy (Free -> NVIDIA -> Google) running on port {PORT}")
    with ThreadedHTTPServer(("", PORT), ChainedHandler) as httpd:
        httpd.serve_forever()