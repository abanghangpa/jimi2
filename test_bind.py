import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('127.0.0.1', 8000))
    print("Bind successful")
    s.close()
except Exception as e:
    print(f"Bind failed: {e}")
