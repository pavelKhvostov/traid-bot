"""Binance Spot klines: скачивание, инкрементальное обновление, CSV-хранилище.

Перенесено из монолитного OBX4-скрипта. Математика/структура один-в-один,
поменяли только пути (DATA_DIR из config) и обобщили под любой symbol/tf.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from config import DATA_DIR, HISTORY_START_DATE, TIMEFRAMES_COMPOSED

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def tf_to_ms(tf: str) -> int:
    """Таймфрейм -> миллисекунды."""
    unit = tf[-1]
    n = int(tf[:-1])
    mult = {"m": 60_000, "h": 60 * 60_000, "d": 24 * 60 * 60_000, "w": 7 * 24 * 60 * 60_000}
    return n * mult[unit]


def tf_to_pandas_rule(tf: str) -> str:
    """Таймфрейм -> правило для pandas.resample."""
    unit = tf[-1]
    n = int(tf[:-1])
    mapping = {"m": "min", "h": "h", "d": "D", "w": "W"}
    return f"{n}{mapping[unit]}"


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Привести raw-klines к чистому OHLCV-фрейму с DatetimeIndex UTC."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = df.copy()
    if "open_time" in out.columns:
        out["open_time"] = pd.to_datetime(out["open_time"], unit="ms", utc=True)
        out = out.set_index("open_time")
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out[["open", "high", "low", "close", "volume"]]
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    return out


def _csv_path(symbol: str, tf: str) -> Path:
    return DATA_DIR / f"{symbol}_{tf}.csv"


def save_df(df: pd.DataFrame, symbol: str, tf: str) -> None:
    path = _csv_path(symbol, tf)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.index.name = "open_time"
    out.to_csv(path)


def load_df(symbol: str, tf: str) -> pd.DataFrame:
    path = _csv_path(symbol, tf)
    if not path.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.read_csv(path)
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df = df.set_index("open_time")
    df = df.sort_index()
    return df


def _get_with_retry(url: str, params: dict, timeout: int = 30,
                    retries: int = 5) -> requests.Response:
    """GET с экспоненциальным backoff на network/DNS ошибках.

    DNS на VPS бывает временно недоступен (Errno -3). Без retry первый же
    провал кладёт bootstrap. Backoff: 2s, 4s, 8s, 16s, 32s.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_err = e
            wait = 2 ** (attempt + 1)
            print(f"[WARN] network error attempt {attempt + 1}/{retries}: "
                  f"{type(e).__name__}, retry in {wait}s")
            time.sleep(wait)
    assert last_err is not None
    raise last_err


def fetch_klines_range(
    symbol: str,
    tf: str,
    start_ms: int,
    end_ms: int | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Скачать свечи [start_ms, end_ms) батчами по 1000."""
    rows: list[list] = []
    cur = start_ms
    while True:
        params = {
            "symbol": symbol,
            "interval": tf,
            "startTime": cur,
            "limit": limit,
        }
        if end_ms is not None:
            params["endTime"] = end_ms
        r = _get_with_retry(BINANCE_KLINES_URL, params)
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last_open = batch[-1][0]
        next_cur = last_open + tf_to_ms(tf)
        if len(batch) < limit:
            cur = next_cur
            break
        cur = next_cur
        if end_ms is not None and cur >= end_ms:
            break
        time.sleep(0.15)  # щадяще к rate-limit
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    return normalize_df(df)


def fetch_full_history(symbol: str, tf: str, start: str = HISTORY_START_DATE) -> pd.DataFrame:
    """Полная история с start до текущего момента (только закрытые свечи)."""
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    now_ms = int(time.time() * 1000)
    # отсекаем незакрытую текущую свечу
    step = tf_to_ms(tf)
    end_ms = (now_ms // step) * step
    df = fetch_klines_range(symbol, tf, start_ms, end_ms)
    # на всякий: убрать последнюю, если она равна текущему незакрытому бару
    if not df.empty:
        last_open_ms = int(df.index[-1].timestamp() * 1000)
        if last_open_ms + step > now_ms:
            df = df.iloc[:-1]
    return df


def update_df_incrementally(symbol: str, tf: str) -> pd.DataFrame:
    """Догрузить свечи с момента последней сохранённой до сейчас."""
    df = load_df(symbol, tf)
    step = tf_to_ms(tf)
    now_ms = int(time.time() * 1000)
    end_ms = (now_ms // step) * step

    if df.empty:
        fresh = fetch_full_history(symbol, tf)
    else:
        last_open_ms = int(df.index[-1].timestamp() * 1000)
        start_ms = last_open_ms + step
        if start_ms >= end_ms:
            return df
        new_rows = fetch_klines_range(symbol, tf, start_ms, end_ms)
        if new_rows.empty:
            return df
        fresh = pd.concat([df, new_rows])
        fresh = fresh[~fresh.index.duplicated(keep="last")].sort_index()

    # защита от незакрытой свечи
    if not fresh.empty:
        last_open_ms = int(fresh.index[-1].timestamp() * 1000)
        if last_open_ms + step > now_ms:
            fresh = fresh.iloc[:-1]

    save_df(fresh, symbol, tf)
    return fresh


def compose_from_base(base_df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Собрать составной ТФ (3h, 2d...) из базового (1h, 1d) через resample."""
    if base_df.empty:
        return base_df.copy()
    rule = tf_to_pandas_rule(tf)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    # origin='epoch' -> выравнивание по UTC-эпохе, label/closed='left' -> open_time = начало бара
    out = base_df.resample(rule, origin="epoch", label="left", closed="left").agg(agg)
    out = out.dropna(subset=["open", "high", "low", "close"])

    # отрезаем последний незавершённый бар (если текущее время внутри него)
    if not out.empty:
        step_ms = tf_to_ms(tf)
        now_ms = int(time.time() * 1000)
        last_open_ms = int(out.index[-1].timestamp() * 1000)
        if last_open_ms + step_ms > now_ms:
            out = out.iloc[:-1]
    return out


def get_df(symbol: str, tf: str, refresh: bool = True) -> pd.DataFrame:
    """Удобный фасад: вернуть актуальный df для symbol/tf, работает с составными."""
    if tf in TIMEFRAMES_COMPOSED:
        base_tf = TIMEFRAMES_COMPOSED[tf]
        base = update_df_incrementally(symbol, base_tf) if refresh else load_df(symbol, base_tf)
        composed = compose_from_base(base, tf)
        save_df(composed, symbol, tf)
        return composed
    return update_df_incrementally(symbol, tf) if refresh else load_df(symbol, tf)
