#!/usr/bin/env python3
import os
import time
import subprocess
import json
import urllib.request
import urllib.error
import sys

def kill_procs():
    subprocess.run(['pkill', '-f', 'master_tiered_proxy.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)

def main():
    kill_procs()
    
    # Start Ollama (we want the service running so that the connection attempt doesn't fail immediately?
    # Actually, if Ollama is not running, we get a connection error and move to next tier.
    # We want to test the case where Ollama is running but the model doesn't exist.
    # So we start Ollama.
    time.sleep(2)  # let it start
    
    # Prepare environment: we want to keep NVIDIA_API_KEY and FREE_PROXY_KEY from .env, but set PROD_API_KEY to empty
    env = os.environ.copy()
    # Load .env file
    env_path = '/root/.openclaw/workspace/.env'
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env[key] = value
    # Override PROD_API_KEY to empty to make Tier 1 fail
    env['PROD_API_KEY'] = ''
    # Ensure NVIDIA_API_KEY and FREE_PROXY_KEY are set (they should be from .env)
    
    # Backup and empty free_keys.json
    free_keys_path = '/root/.openclaw/workspace/free_keys.json'
    backup_path = free_keys_path + '.backup'
    if os.path.exists(free_keys_path):
        os.rename(free_keys_path, backup_path)
    with open(free_keys_path, 'w') as f:
        json.dump({}, f)
    
    # Start the proxy
    proxy_proc = subprocess.Popen(
        ['python3', '/root/.openclaw/workspace/master_tiered_proxy.py'],
        stdout=open('/root/.openclaw/workspace/master_proxy.log', 'w'),
        stderr=subprocess.STDOUT,
        env=env
    )
    time.sleep(3)  # let proxy start
    
    # Make the request
    url = 'http://localhost:8000/v1/chat/completions'
    data = json.dumps({
        'model': 'default',
        'messages': [{'role': 'user', 'content': 'Say hello in one word'}]
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            resp_data = response.read()
            print('Response:')
            print(resp_data.decode('utf-8'))
    except Exception as e:
        print(f'Error making request: {e}')
    
    # Show the last 20 lines of the proxy log
    log_path = '/root/.openclaw/workspace/master_proxy.log'
    if os.path.exists(log_path):
        print('\n=== Proxy Log (last 20 lines) ===')
        with open(log_path) as f:
            lines = f.readlines()
            for line in lines[-20:]:
                print(line.rstrip())
        print('=============================')
    
    # Cleanup
    kill_procs()
    # Restore free_keys.json
    if os.path.exists(backup_path):
        os.rename(backup_path, free_keys_path)
    # Terminate Ollama and proxy if they are still running (should have been killed by kill_procs)
    subprocess.run(['pkill', '-f', 'master_tiered_proxy.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    main()