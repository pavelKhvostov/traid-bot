"""Скачивает ETHUSDT 1m с Binance Spot за 2020-05-01 → 2026-05-21."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"

START = pd.Timestamp("2020-05-01", tz="UTC")
END = pd.Timestamp("2026-05-22", tz="UTC")
BINANCE_URL = "https://api.binance.com/api/v3/klines"


def main() -> None:
    if CACHE.exists():
        existing = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
        existing.index = existing.index.tz_convert("UTC") if existing.index.tz else existing.index.tz_localize("UTC")
        existing = existing.sort_index()
        start = existing.index.max() + pd.Timedelta(minutes=1)
        print(f"existing cache: {len(existing):,} bars, resume from {start}", flush=True)
    else:
        existing = None
        start = START

    rows: list[list] = []
    cur = start
    while cur < END:
        params = {"symbol": "ETHUSDT", "interval": "1m",
                  "startTime": int(cur.timestamp() * 1000), "limit": 1000}
        r = requests.get(BINANCE_URL, params=params, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last_close = pd.to_datetime(batch[-1][6], unit="ms", utc=True)
        if last_close <= cur: break
        cur = last_close + pd.Timedelta(milliseconds=1)
        time.sleep(0.10)
        if len(rows) % 50000 == 0:
            print(f"  up to {last_close.date()} {last_close.time()}, {len(rows):,}", flush=True)

    if not rows:
        print("nothing to fetch"); return
    df_new = pd.DataFrame(rows, columns=[
        "open_time","open","high","low","close","volume","close_time","qav","trades","tbv","tqv","ignore"])
    df_new = df_new[["open_time","open","high","low","close","volume"]].copy()
    df_new["open_time"] = pd.to_datetime(df_new["open_time"], unit="ms", utc=True)
    for c in ("open","high","low","close","volume"):
        df_new[c] = df_new[c].astype(float)
    df_new = df_new.set_index("open_time").sort_index()
    if existing is not None:
        merged = pd.concat([existing, df_new]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
    else:
        merged = df_new[~df_new.index.duplicated(keep="first")]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(CACHE)
    print(f"saved: {CACHE} ({len(merged):,} bars, {merged.index.min()} → {merged.index.max()})")


if __name__ == "__main__":
    main()
