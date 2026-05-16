"""Дофетчить ETH/SOL HTF (1d/4h/1h) до 2020-05-15.

Параллельно с fetch_eth_sol_6y.py (который дофетчит 1m/15m)."""
from __future__ import annotations
import time
import pandas as pd
from data_manager import _csv_path, fetch_klines_range, load_df, save_df

START_DATE = "2020-05-15"
SYMBOLS = ["ETHUSDT", "SOLUSDT"]
TFS = ["1d", "4h", "1h"]


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
            print(f"  existing: {len(existing)} rows  starts {existing.index[0] if not existing.empty else 'EMPTY'}")
            if not existing.empty and int(existing.index[0].timestamp() * 1000) <= target_start_ms:
                print(f"  already covers {START_DATE} — skip")
                continue

            first_existing_ms = (int(existing.index[0].timestamp() * 1000)
                                  if not existing.empty else int(time.time()*1000))
            step = tf_to_ms(tf)
            end_ms = first_existing_ms - step
            print(f"  fetching: {pd.Timestamp(target_start_ms, unit='ms', tz='UTC')} -> "
                  f"{pd.Timestamp(end_ms, unit='ms', tz='UTC')}")
            t0 = time.time()
            new_data = fetch_klines_range(symbol, tf, target_start_ms, end_ms)
            print(f"  fetched: {len(new_data)} rows in {time.time()-t0:.1f}s")
            if not new_data.empty:
                if existing.empty:
                    merged = new_data
                else:
                    merged = pd.concat([new_data, existing])
                    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                save_df(merged, symbol, tf)
                print(f"  saved: {len(merged)} rows")


if __name__ == "__main__":
    main()
