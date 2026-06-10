import requests
import re

def get_key(model_name):
    url = "https://github.com/alistaitsacle/free-llm-api-keys"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        text = r.text
        
        # Find the first 'sk-' key that appears after the model name
        model_pos = text.find(model_name)
        if model_pos == -1:
            return None
        
        match = re.search(r'sk-[a-zA-Z0-9]{40,}', text[model_pos:])
        return match.group(0) if match else None
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    key = get_key("gpt-5.5")
    if key:
        print(key)
