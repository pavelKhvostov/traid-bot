"""
Загрузка BTC 1m CSV из ~/traid-bot/data/.

Конвенция:
- CSV имеет смешанный формат timestamps (старые '+00:00' и новые ISO 'T...+00:00'),
  pandas pd.to_datetime справляется с обоими через format='mixed'.
- Все timestamps UTC.
- Возврат: DataFrame с DatetimeIndex (UTC, name='open_time') и колонками [open, high, low, close, volume].

Файл большой (~3.2M строк, ~250MB). Поддерживаем фильтр по диапазону дат на этапе чтения,
чтобы не держать всё в памяти когда нужен только год обучения.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Можно переопределить через env BTC_DATA_PATH (используется в portable-режиме)
DEFAULT_BTC_1M_PATH = Path(os.environ.get(
    "BTC_DATA_PATH",
    str(Path.home() / "traid-bot" / "data" / "BTCUSDT_1m_vic_vadim.csv"),
))


def load_btc_1m(
    path: str | Path = DEFAULT_BTC_1M_PATH,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """
    Прочитать 1m OHLCV для BTC.

    start, end: optional bounds (включительно). Если строка — парсится как UTC.

    Returns DataFrame с DatetimeIndex (UTC) и колонками [open, high, low, close, volume].
    """
    df = pd.read_csv(path)
    df["open_time"] = pd.to_datetime(df["open_time"], format="mixed", utc=True)
    df = df.set_index("open_time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)

    if start is not None:
        if isinstance(start, str):
            start = pd.Timestamp(start, tz="UTC")
        df = df.loc[df.index >= start]
    if end is not None:
        if isinstance(end, str):
            end = pd.Timestamp(end, tz="UTC")
        df = df.loc[df.index <= end]
    return df
