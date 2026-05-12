"""Этап 27: загрузка недостающих 1m данных за gap 2022-01-01 .. 2023-04-26.

Текущий BTCUSDT_1m.csv имеет дыру в 480 дней. Загружаем через Binance REST.
~691200 1m баров = ~692 батча по 1000, ~104 сек sleep + время API.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import time
from pathlib import Path
import pandas as pd

from data_manager import fetch_klines_range

SYMBOL = "BTCUSDT"
TF = "1m"
GAP_START = "2022-01-01 00:00:00"
GAP_END = "2023-04-27 00:00:00"  # inclusive до 27 апреля чтобы покрыть конец gap
CSV_PATH = Path("data/BTCUSDT_1m.csv")


def main():
    t0 = time.time()
    print(f"[INFO] loading existing CSV: {CSV_PATH}")
    df_existing = pd.read_csv(CSV_PATH)
    df_existing.iloc[:, 0] = pd.to_datetime(df_existing.iloc[:, 0])
    df_existing = df_existing.set_index(df_existing.columns[0])
    print(f"  existing: {len(df_existing)} bars, {df_existing.index.min()} -> {df_existing.index.max()}")

    print(f"\n[INFO] fetching gap {GAP_START} -> {GAP_END}")
    start_ms = int(pd.Timestamp(GAP_START, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(GAP_END, tz="UTC").timestamp() * 1000)
    df_new = fetch_klines_range(SYMBOL, TF, start_ms, end_ms)
    print(f"  fetched: {len(df_new)} new 1m bars")
    print(f"  range: {df_new.index.min()} -> {df_new.index.max()}")

    print(f"\n[INFO] merging and dedup")
    combined = pd.concat([df_existing, df_new])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    print(f"  combined: {len(combined)} bars")
    print(f"  range: {combined.index.min()} -> {combined.index.max()}")

    # year breakdown
    print(f"\n[INFO] count by year:")
    print(combined.groupby(combined.index.year).size().to_string())

    # check gaps
    diffs = combined.index.to_series().diff()
    big_gaps = diffs[diffs > pd.Timedelta(minutes=30)]
    print(f"\n[INFO] gaps > 30min: {len(big_gaps)}")
    if len(big_gaps) > 0:
        print("  top-5 biggest gaps:")
        for ts, gap in big_gaps.sort_values(ascending=False).head(5).items():
            print(f"    {ts - gap} -> {ts}: {gap}")

    print(f"\n[INFO] saving to {CSV_PATH}")
    combined.reset_index().rename(columns={"index": "open_time"}).to_csv(CSV_PATH, index=False)
    print(f"[TIME] total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
