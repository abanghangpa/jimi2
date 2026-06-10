import json

config_path = '/root/.openclaw/openclaw.json'

try:
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Remove the 'key' field from the free-proxy profile
    if 'auth' in config and 'profiles' in config['auth']:
        if 'free-proxy:default' in config['auth']['profiles']:
            if 'key' in config['auth']['profiles']['free-proxy:default']:
                del config['auth']['profiles']['free-proxy:default']['key']
                print("Removed 'key' from 'free-proxy:default' profile.")
            else:
                print("'key' not found in 'free-proxy:default' profile.")
        else:
            print("'free-proxy:default' profile not found.")
    else:
        print("auth or profiles not found in config.")

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print("Successfully updated openclaw.json.")

except Exception as e:
    print(f"Error: {e}")
