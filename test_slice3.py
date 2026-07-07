import pandas as pd
import numpy as np
cvd = pd.Series([], dtype=float)
print('length:', len(cvd))
try:
    s = cvd.iloc[0:1]
    print('slice length:', len(s))
    print('slice:', s)
except Exception as e:
    print('error:', e)
