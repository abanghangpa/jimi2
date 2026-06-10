#!/usr/bin/env python3
"""
LLM wrapper with caching and rate limiting for NVIDIA API (40 RPM).
Free‑proxy keys can also be used; they are not rate‑limited here but we still cache.
"""
import os
import json
import time
import hashlib
import requests
from pathlib import Path
from typing import Optional, Dict, Any

CACHE_DIR = Path("/root/.openclaw/workspace/llm_cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL = 300  # seconds (5 min)

# NVIDIA rate limiting: 40 requests per minute => min interval 1.5s
MIN_INTERVAL = 1.5
_last_call_ts = 0.0


def _cache_key(prompt: str, model: str, temperature: float = 0.7, max_tokens: int = 500) -> str:
    data = f"{prompt}|{model}|{temperature}|{max_tokens}"
    return hashlib.sha256(data.encode()).hexdigest()


def _get_from_cache(key: str) -> Optional[Dict]:
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                entry = json.load(f)
            if time.time() - entry["ts"] < CACHE_TTL:
                return entry["response"]
        except Exception:
            pass
    return None


def _save_to_cache(key: str, response: Dict):
    cache_file = CACHE_DIR / f"{key}.json"
    try:
        with open(cache_file, "w") as f:
            json.dump({"ts": time.time(), "response": response}, f)
    except Exception:
        pass


def _rate_limit():
    global _last_call_ts
    now = time.time()
    elapsed = now - _last_call_ts
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call_ts = time.time()


def call_llm(
    prompt: str,
    model: str,
    api_key: str,
    api_base: str,
    temperature: float = 0.7,
    max_tokens: int = 500,
    use_cache: bool = True,
) -> Optional[str]:
    """
    Call an OpenAI‑compatible LLM API with caching and rate limiting.
    Returns the response text or None on failure.
    """
    if use_cache:
        key = _cache_key(prompt, model, temperature, max_tokens)
        cached = _get_from_cache(key)
        if cached is not None:
            return cached.get("choices", [{}])[0].get("message", {}).get("content")

    _rate_limit()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(api_base, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if use_cache:
            _save_to_cache(key, data)
        return data.get("choices", [{}])[0].get("message", {}).get("content")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            # Too Many Requests – wait a bit and retry once
            time.sleep(5)
            try:
                resp = requests.post(api_base, headers=headers, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if use_cache:
                    _save_to_cache(key, data)
                return data.get("choices", [{}])[0].get("message", {}).get("content")
            except Exception as e2:
                print(f"[LLM] Retry failed: {e2}")
        else:
            print(f"[LLM] HTTP error: {e}")
    except Exception as e:
        print(f"[LLM] Request error: {e}")
    return None