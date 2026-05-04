"""Догрузить 3 года истории 15m + 1m для ETH/SOL.

В data/ETHUSDT_15m.csv и data/SOLUSDT_15m.csv лежит только ~3 месяца истории
(с 2026-01-26). Для 1.1.1 backtest нужны те же 3 года что и BTC (2023-04-26).

Шаги: для каждого (символ, ТФ) дозагрузить недостающую часть с 2023-04-26 до
начала существующих данных, конкатить, сохранить.
"""
from __future__ import annotations

import time

import pandas as pd

from data_manager import _csv_path, fetch_klines_range, load_df, save_df

START_DATE = "2023-04-26"
SYMBOLS = ["ETHUSDT", "SOLUSDT"]
TFS = ["15m", "1m"]


def tf_to_ms(tf: str) -> int:
    if tf.endswith("m"): return int(tf[:-1]) * 60_000
    if tf.endswith("h"): return int(tf[:-1]) * 3_600_000
    if tf.endswith("d"): return int(tf[:-1]) * 86_400_000
    raise ValueError(tf)


def main() -> None:
    target_start_ms = int(pd.Timestamp(START_DATE, tz="UTC").timestamp() * 1000)
    for symbol in SYMBOLS:
        for tf in TFS:
            print(f"\n=== {symbol} {tf} ===")
            existing = load_df(symbol, tf)
            print(f"  existing: {len(existing)} rows")
            if existing.empty:
                first_existing_ms = int(time.time() * 1000)
            else:
                first_existing_ms = int(existing.index[0].timestamp() * 1000)
                print(f"  starts at {existing.index[0]}")

            if first_existing_ms <= target_start_ms:
                print(f"  already covers {START_DATE} — skip")
                continue

            step = tf_to_ms(tf)
            end_ms = first_existing_ms - step
            print(f"  fetching range: {pd.Timestamp(target_start_ms, unit='ms', tz='UTC')} -> "
                  f"{pd.Timestamp(end_ms, unit='ms', tz='UTC')}")
            t0 = time.time()
            new_data = fetch_klines_range(symbol, tf, target_start_ms, end_ms)
            elapsed = time.time() - t0
            print(f"  fetched: {len(new_data)} rows in {elapsed:.1f}s")

            if not new_data.empty:
                if existing.empty:
                    merged = new_data
                else:
                    merged = pd.concat([new_data, existing])
                    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                save_df(merged, symbol, tf)
                print(f"  saved: {len(merged)} rows -> {_csv_path(symbol, tf)}")


if __name__ == "__main__":
    main()
