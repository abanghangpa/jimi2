import pandas as pd
import numpy as np
lookback = 24
window = 12
n = 1000
cvd = pd.Series([np.nan]*n)
for i in range(lookback + window, n):
    look = min(lookback, i)
    for j in range(max(0, i - look), i - 4):
        start = max(0, j-1)
        end = j+1
        s = cvd.iloc[start:end]
        if len(s) == 0:
            print(f"Empty slice: i={i}, j={j}, start={start}, end={end}")
            print(f"  i-look={i-look}, max={max(0, i-look)}")
            break
    else:
        continue
    break
else:
    print("No empty slice found")
