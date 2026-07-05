#!/usr/bin/env python3
"""POST /note {"source":"x","note":"text"} -> appends to memory/YYYY-MM-DD.md"""
import json, os, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

MEMORY_DIR = "/root/.openclaw/workspace/memory/"
PORT = 9877

class NoteHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/note":
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        source = body.get("source", "unknown")
        note = body.get("note", "")
        date = body.get("date", datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"))
        time = datetime.datetime.now(datetime.UTC).strftime("%H:%M")
        if not note:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error": "note required"}'); return
        memory_path = os.path.join(MEMORY_DIR, f"{date}.md")
        if not os.path.exists(memory_path):
            with open(memory_path, "w") as f:
                f.write(f"# Daily Log {chr(8212)} {date}\n\n")
        with open(memory_path, "a") as f:
            f.write(f"\n### Note from [{source}] ({time} UTC)\n{note}\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}'); return
        self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), NoteHandler)
    print(f"Sync note server on :{PORT}")
    server.serve_forever()
