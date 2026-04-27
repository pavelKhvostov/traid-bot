"""Расчёт уровня maxV (VIC Day) — чистая функция, без I/O."""
from __future__ import annotations

import pandas as pd


def calculate_vic_d(
    df_1m: pd.DataFrame, day: pd.Timestamp, ltf_minutes: int = 1,
) -> float | None:
    """maxV для дня `day` — close LTF-свечи с макс объёмом среди bull (close>open)
    или bear (close<open), в зависимости от того, у какой группы максимум объёма
    выше.

    `ltf_minutes` — размер LTF-агрегата для расчёта. Соответствует параметру
    `mlt` Pine-индикатора 'ViC ASVK' с auto=true: LTF = chart_TF / mlt,
    округлённое Pine `timeframe.from_seconds()` вниз до валидного TF.
    Например, на 1D-чарте при mlt=100 → 1440/100 = 14.4m → Pine round down → 14m.
    Значение по умолчанию 1 (no-op resample) — для обратной совместимости тестов
    и явного 1m-режима.

    Если `ltf_minutes > 1`, 1m-свечи дня D ресемплятся в LTF-бары через
    `pandas.resample(origin='epoch')` — выравнивание по UTC-эпохе как у
    `data_manager.compose_from_base`. Бары без 1m-данных отбрасываются.

    Возвращает None если за день нет данных, либо нет ни одной bull/bear свечи.
    При равенстве max_bull == max_bear выбирается bear (следует §2 спеки —
    ветка else в `if max_bull > max_bear`)."""
    next_day = day + pd.Timedelta(days=1)
    mask = (df_1m.index >= day) & (df_1m.index < next_day)
    day_df = df_1m.loc[mask]
    if day_df.empty:
        return None

    if ltf_minutes > 1:
        day_df = day_df.resample(
            f"{ltf_minutes}min", origin="epoch", label="left", closed="left",
        ).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["close"])
        if day_df.empty:
            return None

    bull = day_df[day_df["close"] > day_df["open"]]
    bear = day_df[day_df["close"] < day_df["open"]]

    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0

    if max_bull == 0 and max_bear == 0:
        return None

    if max_bull > max_bear:
        return float(bull.loc[bull["volume"].idxmax(), "close"])
    return float(bear.loc[bear["volume"].idxmax(), "close"])
