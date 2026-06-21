"""
Strict Williams-i labeling на 12h candles.

Цель: для каждой 12h свечи определить является ли она i-экстремумом Williams n=2.

Strict canon:
  - FH: high[i] СТРОГО > high[i-2], high[i-1], high[i+1], high[i+2]
  - FL: low[i]  СТРОГО < low[i-2],  low[i-1],  low[i+1],  low[i+2]
  - Confirmation: после close i+2 (т.е. open_time + (N+1)*12h = +36h после open_time[i])

ВАЖНО — fix старого bug: label = ТОЛЬКО candle_i = pivot. Следующая свеча (i+1) НЕ
засчитывается в позитивный класс. Старая логика «candle_t OR candle_{t+1}» отвергнута
([[force-model-v2-architecture]]).
"""
from __future__ import annotations

import pandas as pd


def label_williams_12h(df_12h: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    """
    Пометить каждый 12h бар: pivot_high / pivot_low / any_pivot (strict Williams n).

    df_12h: 12h OHLC с DatetimeIndex (open_time). Должен быть отсортирован.
    n: Williams окно (default 2 = 5-bar окно).

    Returns DataFrame с теми же индексами + колонками:
      - is_fh: bool, strict Fractal High
      - is_fl: bool, strict Fractal Low
      - is_pivot: bool, is_fh OR is_fl
      - confirm_ts: pd.Timestamp когда подтверждается (= open_time[i+n])
    Краевые бары (первые n и последние n) → is_fh = is_fl = False (нельзя подтвердить).
    """
    highs = df_12h["high"].to_numpy()
    lows = df_12h["low"].to_numpy()
    N = len(df_12h)
    is_fh = [False] * N
    is_fl = [False] * N

    for i in range(n, N - n):
        h = highs[i]
        l = lows[i]
        # FH: strictly greater than 2n neighbors
        fh = True
        fl = True
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
    out["is_pivot"] = out["is_fh"] | out["is_fl"]
    # Подтверждение: open_time[i + n]; для краевых баров → NaT
    confirm = [pd.NaT] * N
    for i in range(N - n):
        confirm[i] = df_12h.index[i + n]
    out["confirm_ts"] = confirm
    return out
