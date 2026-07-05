#!/usr/bin/env python3
"""
Extract meaningful discussions for a given day.
Sources:
  1. Session logs in jimi_audit/reports/session_log_YYYY-MM-DD.md (curated)
  2. Human conversations from JSONL session files (non-cron)
Skips: cron outputs, scanner reports, key rotation, deep analysis (already in reports/)
"""

import json, os, sys, glob
from datetime import datetime, timedelta

WORKSPACE = "/root/.openclaw/workspace/"
SESSIONS_DIR = "/root/.openclaw/agents/main/sessions/"
MEMORY_DIR = os.path.join(WORKSPACE, "memory/")
REPORTS_DIR = os.path.join(WORKSPACE, "jimi_audit/reports/")

SKIP_PATTERNS = [
    "cron:", "HEARTBEAT_OK", "assistant turn failed",
    "Command still running", "Process exited",
    "Jimi Scanner", "Rotate Free Keys",
    "Liquidity Collector", "Liquidity Reporter",
    "scanner.py", "JSON output", "generate the report",
    "Key rotation completed", "free_keys.json",
]

def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    return ""

def get_session_log(target_date):
    """Grab curated session log if it exists."""
    path = os.path.join(REPORTS_DIR, f"session_log_{target_date}.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return None

def get_human_conversations(target_date):
    """Extract non-cron user messages from JSONL session files."""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    ts_start, ts_end = dt.timestamp(), (dt + timedelta(days=1)).timestamp()
    
    conversations = []
    for f in glob.glob(os.path.join(SESSIONS_DIR, "*.jsonl")):
        if "trajectory" in f:
            continue
        mtime = os.path.getmtime(f)
        if mtime < ts_start or mtime >= ts_end:
            continue
        try:
            for line in open(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except:
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message", {})
                if msg.get("role") != "user":
                    continue
                text = extract_text(msg.get("content", ""))
                if not text or len(text) < 30:
                    continue
                if any(p in text for p in SKIP_PATTERNS):
                    continue
                conversations.append(text[:300])
        except:
            continue
    return conversations

def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    
    memory_path = os.path.join(MEMORY_DIR, f"{target_date}.md")
    
    # Check if we already have a Discussions section (avoid duplicates)
    if os.path.exists(memory_path):
        with open(memory_path) as f:
            if "## Discussions & Findings" in f.read():
                print(f"Already have discussions for {target_date}, skipping")
                return
    
    sections = []
    
    # 1. Session log (curated findings)
    session_log = get_session_log(target_date)
    if session_log:
        sections.append(("SESSION LOG", session_log))
    
    # 2. Human conversations
    conversations = get_human_conversations(target_date)
    if conversations:
        sections.append(("CONVERSATIONS", conversations))
    
    if not sections:
        print(f"No new discussions for {target_date}")
        return
    
    # Write to memory file
    if not os.path.exists(memory_path):
        with open(memory_path, "w") as f:
            f.write(f"# Daily Log — {target_date}\n\n")
    
    with open(memory_path, "a") as f:
        f.write(f"\n## Discussions & Findings\n\n")
        
        for kind, content in sections:
            if kind == "SESSION LOG":
                f.write(f"### 📋 Session Log\n\n{content}\n\n---\n\n")
            elif kind == "CONVERSATIONS":
                f.write(f"### 💬 Human Conversations\n\n")
                for i, text in enumerate(content, 1):
                    f.write(f"> {text}\n\n")
                f.write("---\n\n")
    
    total = (1 if session_log else 0) + len(conversations)
    print(f"Extracted {total} sections for {target_date}")

if __name__ == "__main__":
    main()
