"""
Directional Williams-i labeling на 12h candles.

Strict canon (n=2 Williams BW):
  - FH: high[i] СТРОГО > high[i-2], high[i-1], high[i+1], high[i+2]
  - FL: low[i]  СТРОГО < low[i-2],  low[i-1],  low[i+1],  low[i+2]
  - Confirmation: open_time[i+n]

Target в v3 directional:
  is_FH = 1 для short-side rows
  is_FL = 1 для long-side rows
"""
from __future__ import annotations

import pandas as pd


def label_williams_12h(df_12h: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    """
    Returns same df + columns:
      - is_fh: bool (strict Williams High)
      - is_fl: bool (strict Williams Low)
      - confirm_ts: timestamp of confirmation bar (= open_time[i+n])
    """
    highs = df_12h["high"].to_numpy()
    lows = df_12h["low"].to_numpy()
    N = len(df_12h)
    is_fh = [False] * N
    is_fl = [False] * N
    for i in range(n, N - n):
        h = highs[i]; l = lows[i]
        fh = True; fl = True
        for k in range(1, n + 1):
            if highs[i - k] >= h or highs[i + k] >= h:
                fh = False
            if lows[i - k] <= l or lows[i + k] <= l:
                fl = False
            if not fh and not fl:
                break
        is_fh[i] = fh
        is_fl[i] = fl

    out = df_12h.copy()
    out["is_fh"] = is_fh
    out["is_fl"] = is_fl
    confirm = [pd.NaT] * N
    for i in range(N - n):
        confirm[i] = df_12h.index[i + n]
    out["confirm_ts"] = confirm
    return out
