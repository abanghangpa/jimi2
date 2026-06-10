
import sys
import os

def trace_calls(frame, event, arg):
    if event == 'call':
        code = frame.f_code
        func_name = code.co_name
        filename = os.path.basename(code.co_filename)
        print(f"CALL: {filename} -> {func_name}")
    return trace_calls

sys.settrace(trace_calls)

# Now import the scanner logic
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    import scripts.scanner as scanner
    print("Successfully imported scanner!")
except Exception as e:
    print(f"Import failed: {e}")
