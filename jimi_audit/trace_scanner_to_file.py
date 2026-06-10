
import sys
import os

def trace_calls(frame, event, arg):
    if event == 'call':
        code = frame.f_code
        func_name = code.co_name
        filename = os.path.basename(code.co_filename)
        with open('/tmp/scanner_trace.log', 'a') as f:
            f.write(f"CALL: {filename} -> {func_name}\n")
    return trace_calls

# Clear previous log
with open('/tmp/scanner_trace.log', 'w') as f:
    f.write("--- Start Trace ---\n")

sys.settrace(trace_calls)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    import scripts.scanner as scanner
    print("Successfully imported scanner!")
except Exception as e:
    print(f"Import failed: {e}")
