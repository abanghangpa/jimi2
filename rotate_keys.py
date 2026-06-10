import os
import re
import json
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timezone

REPO_PATH = "/root/.openclaw/workspace/free_keys_repo"
KEYS_FILE = "/root/.openclaw/workspace/free_keys.json"
STATE_FILE = "/root/.openclaw/workspace/rotate_keys_state.json"

# Configurable retry intervals (in seconds)
# Initial check at start of hour (triggered by cron)
# If no new data, retry after these intervals from the start time:
INITIAL_CHECK_DELAY = 0          # run immediately at start of hour
RETRY_INTERVALS = [10 * 60,      # 10 minutes after start
                   20 * 60,      # 20 additional minutes (30 total from start)
                   30 * 60]      # 30 additional minutes (60 total from start)

def log(msg):
    """Log a message with UTC timestamp."""
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f"[{timestamp}] {msg}", flush=True)

def update_repo():
    """Update the git repository. Returns True on success, False on failure."""
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
    except subprocess.TimeoutExpired:
        log("Repo update timed out.")
        return False
    except subprocess.CalledProcessError as e:
        log(f"Repo update failed with exit code {e.returncode}.")
        return False
    except Exception as e:
        log(f"Unexpected error during repo update: {e}")
        return False

def extract_keys():
    """Extract keys from README.md. Returns dict of model->list of keys."""
    readme_path = os.path.join(REPO_PATH, "README.md")
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        log(f"README.md not found at {readme_path}")
        return {}
    except Exception as e:
        log(f"Failed to read README.md: {e}")
        return {}

    # Keys start with sk-
    key_pattern = re.compile(r"(sk-[a-zA-Z0-9]{30,})")
    
    lines = content.splitlines()
    model_keys = {}
    
    for line in lines:
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|")]
            # Remove empty first/last cells due to leading/trailing '|'
            if cells and not cells[0]:
                cells.pop(0)
            if cells and not cells[-1]:
                cells.pop(-1)
            
            for i, cell in enumerate(cells):
                match = key_pattern.search(cell)
                if match:
                    # Strip backticks from the key
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
    """Compute a stable hash of the keys dictionary."""
    # Sort keys for consistent ordering
    sorted_items = sorted(keys_dict.items())
    # Create a string representation
    repr_str = json.dumps(sorted_items, sort_keys=True)
    return hashlib.sha256(repr_str.encode('utf-8')).hexdigest()

def load_state():
    """Load last known state from file."""
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
    """Save current state hash to file."""
    try:
        state = {'last_hash': hash_val, 'updated_at': datetime.now(timezone.utc).isoformat()}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        log(f"State saved with hash {hash_val[:8]}...")
    except Exception as e:
        log(f"Failed to save state: {e}")

def check_for_new_data():
    """Perform one check: update repo, extract keys, compare with last hash.
    Returns (new_data_found, keys_dict_or_none).
    """
    if not update_repo():
        return False, None  # indicate failure, no keys
    keys = extract_keys()
    if not keys:
        log("No keys extracted.")
        return False, None
    current_hash = compute_state_hash(keys)
    last_hash = load_state()
    if last_hash is None:
        log("No previous state found; treating as new data.")
        return True, keys
    if current_hash != last_hash:
        log("New data detected (hash changed).")
        return True, keys
    else:
        log("No new data (hash unchanged).")
        return False, None

def sync_config_fallbacks(found_models, config_path="/root/.openclaw/openclaw.json"):
    """Sync found models from the scraper into the agents.defaults.model.fallbacks list in openclaw.json."""
    import json
    import os

    if not os.path.exists(config_path):
        print(f"[!] Config file not found: {config_path}")
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Target: config["agents"]["defaults"]["model"]["fallbacks"]
        try:
            fallbacks = config["agents"]["defaults"]["model"]["fallbacks"]
        except KeyError:
            print("[!] Could not find fallbacks list in config structure.")
            return False

        updated = False
        for model in found_models:
            # Simple cleaning: skip if it looks like junk or if already in list
            if len(model) < 3 or model in fallbacks:
                continue
            
            # Check if it's a known provider format (e.g. provider/model or just model)
            # For this implementation, we assume the scraper returns valid identifiers.
            fallbacks.append(model)
            print(f"[*] Auto-added new fallback model: {model}")
            updated = True

        if updated:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"[+] Successfully updated {config_path}")
            return True
        else:
            print("[*] No new models to add to fallbacks.")
            return False

    except Exception as e:
        print(f"[!] Error during config sync: {e}")
        return False

def main():
    """Main execution: check for new key data with retry logic and sync fallbacks."""
    log("=== Starting rotate_keys.py ===")
    start_time = time.time()
    
    # We'll attempt checks at: start, then start+interval1, start+interval1+interval2, ...
    delays = [INITIAL_CHECK_DELAY] + RETRY_INTERVALS
    
    for attempt, delay in enumerate(delays):
        if attempt > 0:
            log(f"Waiting {delay} seconds before retry {attempt+1}...")
            time.sleep(delay)
        
        log(f"Attempt {attempt+1} of {len(delays)}.")
        new_data_found, keys = check_for_new_data()
        
        if new_data_found and keys is not None:
            # 1. Save keys to JSON
            try:
                with open(KEYS_FILE, "w", encoding="utf-8") as f:
                    json.dump(keys, f, indent=4)
                log(f"Keys saved to {KEYS_FILE} for {len(keys)} models.")
                
                # 2. Save state hash
                current_hash = compute_state_hash(keys)
                save_state(current_hash)
                log("Success: new data processed.")

                # 3. AUTO-EVOLVE: Sync newly found models into openclaw.json
                sync_config_fallbacks(list(keys.keys()))
                
                sys.exit(0)
            except Exception as e:
                log(f"Failed to save keys or sync config: {e}")
                sys.exit(1)
        else:
            log("No new data found in this attempt.")
    
    log("All retries exhausted; no new data found. This is not an error.")
    sys.exit(0)

if __name__ == "__main__":
    main()
