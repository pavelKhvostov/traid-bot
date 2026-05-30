"""Расширяет кэш BTCUSDT_15m_vic_vadim.csv влево до 2020-05-01.

Не трогает существующие данные; докачивает только недостающий «хвост слева»
и склеивает.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"

START_NEW = pd.Timestamp("2020-05-01", tz="UTC")
BINANCE_URL = "https://api.binance.com/api/v3/klines"


def fetch_range(start: pd.Timestamp, end: pd.Timestamp) -> list[list]:
    rows: list[list] = []
    cur = start
    while cur < end:
        params = {
            "symbol": "BTCUSDT",
            "interval": "15m",
            "startTime": int(cur.timestamp() * 1000),
            "limit": 1000,
        }
        r = requests.get(BINANCE_URL, params=params, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last_close = pd.to_datetime(batch[-1][6], unit="ms", utc=True)
        if last_close <= cur:
            break
        cur = last_close + pd.Timedelta(milliseconds=1)
        time.sleep(0.12)
        if len(rows) % 5000 == 0:
            print(f"  fetched up to {last_close.date()}, total {len(rows):,}", flush=True)
    return rows


def main() -> None:
    existing = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    existing.index = existing.index.tz_convert("UTC") if existing.index.tz else existing.index.tz_localize("UTC")
    existing = existing.sort_index()
    existing_min = existing.index.min()
    print(f"existing cache: {len(existing):,} bars, min={existing_min}")
    if existing_min <= START_NEW:
        print("ничего расширять не нужно")
        return

    # Скачиваем диапазон [START_NEW, existing_min)
    end_new = existing_min
    print(f"fetching {START_NEW.date()} → {end_new.date()}")
    rows = fetch_range(START_NEW, end_new)
    print(f"got {len(rows):,} new rows")
    if not rows:
        return

    df_new = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbv", "tqv", "ignore",
    ])
    df_new = df_new[["open_time", "open", "high", "low", "close", "volume"]].copy()
    df_new["open_time"] = pd.to_datetime(df_new["open_time"], unit="ms", utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df_new[c] = df_new[c].astype(float)
    df_new = df_new.set_index("open_time").sort_index()
    df_new = df_new[df_new.index < existing_min]

    merged = pd.concat([df_new, existing]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged.to_csv(CACHE)
    print(f"saved merged: {CACHE} ({len(merged):,} bars, "
          f"{merged.index.min()} → {merged.index.max()})")


if __name__ == "__main__":
    main()
