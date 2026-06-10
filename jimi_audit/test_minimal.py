
import sys
import os
import time

print("Test: Starting minimal script")
start = time.time()

# Try importing common libraries
try:
    import numpy as np
    print("Test: numpy imported")
except Exception as e:
    print(f"Test: numpy import failed: {e}")

try:
    import pandas as pd
    print("Test: pandas imported")
except Exception as e:
    print(f"Test: pandas import failed: {e}")

try:
    import ccxt
    print("Test: ccxt imported")
except Exception as e:
    print(f"Test: ccxt import failed: {e}")

print(f"Test: Minimal script finished in {time.time() - start:.2f}s")
