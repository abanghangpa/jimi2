import os
import re
import json
import subprocess
import sys
import hashlib
from datetime import datetime, timezone

REPO_PATH = "/root/.openclaw/workspace/free_keys_repo"
KEYS_FILE = "/root/.openclaw/workspace/free_keys.json"
STATE_FILE = "/root/.openclaw/workspace/rotate_keys_state.json"

def log(msg):
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f"[{timestamp}] {msg}", flush=True)

def update_repo():
    try:
        log(f"Updating repo in {REPO_PATH}...")
        if not os.path.exists(REPO_PATH):
            subprocess.run(["git", "clone", "https://github.com/alistaitsacle/free-llm-api-keys", REPO_PATH], 
                           check=True, timeout=30)
        else:
            subprocess.run(["git", "-C", REPO_PATH, "pull"], 
                           check=True, timeout=30)
        log("Repo update successful.")
        return True
    except Exception as e:
        log(f"Repo update failed: {e}")
        return False

def extract_keys():
    readme_path = os.path.join(REPO_PATH, "README.md")
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        log(f"Failed to read README.md: {e}")
        return {}

    key_pattern = re.compile(r"(sk-[a-zA-Z0-9]{30,})")
    lines = content.splitlines()
    model_keys = {}

    for line in lines:
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|")]
            if cells and not cells[0]:
                cells.pop(0)
            if cells and not cells[-1]:
                cells.pop(-1)

            for i, cell in enumerate(cells):
                match = key_pattern.search(cell)
                if match:
                    key = match.group(1).strip("` ")
                    if i + 1 < len(cells):
                        model_name = cells[i+1].strip("` ")
                        if model_name and model_name not in ["Model", "Status", "Budget", "Rate Limit", "Expires", "Description"]:
                            if model_name not in model_keys:
                                model_keys[model_name] = []
                            if key not in model_keys[model_name]:
                                model_keys[model_name].append(key)
    return model_keys

def compute_state_hash(keys_dict):
    sorted_items = sorted(keys_dict.items())
    repr_str = json.dumps(sorted_items, sort_keys=True)
    return hashlib.sha256(repr_str.encode('utf-8')).hexdigest()

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get('last_hash')
    except Exception as e:
        log(f"Failed to load state: {e}")
        return None

def save_state(hash_val):
    try:
        state = {'last_hash': hash_val, 'updated_at': datetime.now(timezone.utc).isoformat()}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        log(f"State saved with hash {hash_val[:8]}...")
    except Exception as e:
        log(f"Failed to save state: {e}")

if not update_repo():
    log("Repo update failed, exiting.")
    sys.exit(1)

keys = extract_keys()
if not keys:
    log("No keys extracted.")
    sys.exit(0)

current_hash = compute_state_hash(keys)
last_hash = load_state()

if last_hash is None:
    log("No previous state found; treating as new data.")
    new_data = True
else:
    new_data = (current_hash != last_hash)

if new_data:
    try:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=4)
        log(f"Keys saved to {KEYS_FILE} for {len(keys)} models.")
        save_state(current_hash)
        log("Success: new data processed.")
        sys.exit(0)
    except Exception as e:
        log(f"Failed to save keys: {e}")
        sys.exit(1)
else:
    log("No new data (hash unchanged).")
    sys.exit(0)