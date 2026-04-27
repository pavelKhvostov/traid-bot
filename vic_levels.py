"""Расчёт уровня maxV (VIC Day) — чистая функция, без I/O."""
from __future__ import annotations

import pandas as pd


def calculate_vic_d(df_1m: pd.DataFrame, day: pd.Timestamp) -> float | None:
    """maxV для дня `day` — close 1m-свечи с макс объёмом среди bull (close>open)
    или bear (close<open), в зависимости от того, у какой группы максимум объёма
    выше.

    Возвращает None если за день нет данных, либо нет ни одной bull/bear свечи.
    При равенстве max_bull == max_bear выбирается bear (следует §2 спеки —
    ветка else в `if max_bull > max_bear`)."""
    next_day = day + pd.Timedelta(days=1)
    mask = (df_1m.index >= day) & (df_1m.index < next_day)
    day_1m = df_1m.loc[mask]
    if day_1m.empty:
        return None

    bull = day_1m[day_1m["close"] > day_1m["open"]]
    bear = day_1m[day_1m["close"] < day_1m["open"]]

    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0

    if max_bull == 0 and max_bear == 0:
        return None

    if max_bull > max_bear:
        return float(bull.loc[bull["volume"].idxmax(), "close"])
    return float(bear.loc[bear["volume"].idxmax(), "close"])
