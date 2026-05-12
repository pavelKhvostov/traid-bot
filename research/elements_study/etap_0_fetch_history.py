"""Этап 0: догрузить BTCUSDT историю с 2020-01-01 до 2022-01-01.

Существующие CSV в data/ начинаются с 2022-01-01. Догружаем 2 года истории
для всех нативных TF и объединяем.

Native TFs: 1m, 15m, 1h, 2h, 4h, 6h, 12h, 1d
20m не нативный — composed из 1m runtime через compose_from_base.

После завершения: каждый CSV покрывает 2020-01-01 to текущий момент.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd

from data_manager import (
    DATA_DIR, KLINE_COLUMNS, fetch_klines_range, load_df, save_df,
    tf_to_ms, normalize_df,
)

SYMBOL = "BTCUSDT"
START = "2020-01-01"
END = "2022-01-01"  # граница, до которой догружаем
TARGET_TFS = ["1m", "15m", "1h", "2h", "4h", "6h", "12h", "1d"]


def main():
    start_ms = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000)

    for tf in TARGET_TFS:
        print(f"\n[{tf}] downloading {START} to {END} for {SYMBOL}")
        existing = load_df(SYMBOL, tf)
        if not existing.empty:
            existing_first = existing.index[0]
            print(f"  existing CSV: {len(existing)} bars, first {existing_first}")
            if existing_first.tz_localize(None) <= pd.Timestamp(START):
                print(f"  OK already covers {START}, skip")
                continue
        else:
            existing_first = None
            print(f"  existing CSV is empty")

        # Догружаем только до начала имеющихся данных
        if existing_first is not None:
            real_end_ms = int(existing_first.timestamp() * 1000)
            real_end_ms = min(real_end_ms, end_ms)
        else:
            real_end_ms = end_ms

        print(f"  fetching range {start_ms} to {real_end_ms} ms ...")
        new_df = fetch_klines_range(SYMBOL, tf, start_ms, real_end_ms)
        if new_df.empty:
            print(f"  [!] no data returned for {tf}")
            continue
        print(f"  fetched {len(new_df)} bars, "
              f"first {new_df.index[0]}, last {new_df.index[-1]}")

        # Объединяем с существующими
        merged = pd.concat([new_df, existing])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        save_df(merged, SYMBOL, tf)
        print(f"  saved {len(merged)} total bars to {DATA_DIR / f'{SYMBOL}_{tf}.csv'}")

    # Sanity-check итог
    print("\n=== ИТОГ ===")
    for tf in TARGET_TFS:
        df = load_df(SYMBOL, tf)
        if df.empty:
            print(f"  {tf}: empty!")
            continue
        gap_check = df.index.to_series().diff().value_counts().head(2)
        expected = pd.Timedelta(milliseconds=tf_to_ms(tf))
        n_expected = (df.index[-1] - df.index[0]) / expected + 1
        coverage = len(df) / n_expected * 100 if n_expected > 0 else 0
        print(f"  {tf}: {len(df)} bars  {df.index[0]} to {df.index[-1]}  "
              f"coverage {coverage:.2f}%")


if __name__ == "__main__":
    main()
