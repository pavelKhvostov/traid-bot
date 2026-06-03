"""
TF resampler для prediction-algo.

Конвенция:
- input: 1m OHLCV DataFrame с колонками [open, high, low, close, volume] и UTC DatetimeIndex
- output: dict[tf_str → DataFrame] с теми же колонками
- W-anchor = Monday 00:00 UTC (origin = 2017-01-02 00:00 UTC, см. memory weekly-tf-anchor-monday)
- strict cut-off: возвращаются ТОЛЬКО bars, закрытые по времени cut_off_ts (open_ts + tf_ms ≤ cut_off_ts)

TF набор канонический (расширяемый):
  1m, 5m, 15m, 30m, 45m, 1h, 2h, 3h, 4h, 6h, 8h, 12h, 1d, 3d, 1w
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

MONDAY_ANCHOR = pd.Timestamp("2017-01-02 00:00", tz="UTC")
# Unix epoch — anchor for 3D (TV-канон: Sat/Tue/Fri/Mon/Thu/Sun/Wed цикл, не Monday)
EPOCH_ANCHOR = pd.Timestamp("1970-01-01 00:00", tz="UTC")

# Канонический полный набор TF. Подмножество задаётся пользователем через tf_list.
ALL_TFS: tuple[str, ...] = (
    "1m", "5m", "15m", "20m", "30m", "45m",
    "1h", "90m", "2h", "3h", "4h", "6h", "8h", "12h", "16h",
    "1d", "32h", "2d", "3d", "1w",
)

# Map TF-строки → pandas freq. Используем Tick-like freqs (min/h), чтобы pandas
# уважал параметр origin (для D/W он его игнорирует).
_TF_TO_FREQ = {
    "1m": "1min", "5m": "5min", "15m": "15min", "20m": "20min", "30m": "30min", "45m": "45min",
    "1h": "1h", "90m": "90min", "2h": "2h", "3h": "3h", "4h": "4h", "6h": "6h", "8h": "8h",
    "12h": "12h", "16h": "16h", "32h": "32h",
    "1d": "24h", "2d": "48h", "3d": "72h", "1w": "168h",
}


def tf_to_pandas_freq(tf: str) -> str:
    """TF-строка ('12h') → pandas freq-строка ('12h')."""
    if tf not in _TF_TO_FREQ:
        raise ValueError(f"Unknown TF: {tf!r}. Allowed: {list(_TF_TO_FREQ)}")
    return _TF_TO_FREQ[tf]


def tf_to_timedelta(tf: str) -> pd.Timedelta:
    """TF-строка ('12h') → pd.Timedelta."""
    return pd.Timedelta(tf_to_pandas_freq(tf))


def resample_one(df_1m: pd.DataFrame, tf: str, cut_off_ts: pd.Timestamp) -> pd.DataFrame:
    """
    Ресемпл 1m → tf с Monday anchor и strict cut-off.

    df_1m: DatetimeIndex (UTC), колонки [open, high, low, close, volume]
    tf: '1m'..'1w'
    cut_off_ts: pd.Timestamp с tz=UTC. Возвращаются только bars где open_ts + tf <= cut_off_ts.

    Returns: DataFrame с теми же колонками, indexed by bar open_ts (UTC).

    NB: 3D использует EPOCH_ANCHOR (1970-01-01 Thu, Unix epoch) — TV-канон.
    Monday-anchor (2017-01-02) даёт ошибочный сдвиг (3346 days % 3 ≠ 0), поэтому
    3D ressampled бары съезжают на Sun/Wed/Sat/Tue/Fri. См. memory feedback-3d-resample-monday-reset.
    """
    if cut_off_ts.tzinfo is None:
        raise ValueError("cut_off_ts must be tz-aware (UTC)")
    if df_1m.index.tz is None:
        raise ValueError("df_1m must have tz-aware DatetimeIndex (UTC)")

    # Срезаем 1m до cut_off: открытие минуты должно быть строго < cut_off
    # (если cut_off ровно на границе минуты — последняя 1m бара = cut_off-1m уже закрыта)
    df_cut = df_1m.loc[df_1m.index < cut_off_ts]
    if df_cut.empty:
        return df_cut.iloc[0:0].copy()

    # 3D использует epoch anchor (Thursday) вместо MONDAY_ANCHOR (Mon).
    origin = EPOCH_ANCHOR if tf == "3d" else MONDAY_ANCHOR

    freq = tf_to_pandas_freq(tf)
    agg = df_cut.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])  # пустые корзины (без 1m баров) убираем

    # Strict cut-off: bar (open_ts, ..., close_ts=open_ts+tf) включается только если close_ts <= cut_off_ts.
    tf_td = tf_to_timedelta(tf)
    closed_mask = (agg.index + tf_td) <= cut_off_ts
    return agg.loc[closed_mask]


def resample_many(df_1m: pd.DataFrame, tf_list: Iterable[str], cut_off_ts: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """
    Ресемпл 1m в несколько TF одновременно.
    Returns: dict[tf → DataFrame].
    """
    return {tf: resample_one(df_1m, tf, cut_off_ts) for tf in tf_list}
