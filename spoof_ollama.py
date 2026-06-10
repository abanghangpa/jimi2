
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OllamaSpoof")

class SpoofHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        logger.info(f"GET request to {self.path} - returning 404")
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "Ollama is not installed on this host"}')

    def do_POST(self):
        logger.info(f"POST request to {self.path} - returning 404")
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "Ollama is not installed on this host"}')

    def log_message(self, format, *args):
        # Suppress default logging to keep logs clean
        return

if __name__ == "__main__":
    server_address = ('127.0.0.1', 11434)
    httpd = HTTPServer(server_address, SpoofHandler)
    logger.info("Ollama Spoof Server started on port 11434. Blocking socket timeouts...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
