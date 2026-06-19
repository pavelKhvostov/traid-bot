"""Fetch Binance perpetual funding rate history for BTCUSDT / ETHUSDT.

Endpoint: GET /fapi/v1/fundingRate
  - 8h funding cycle (00:00, 08:00, 16:00 UTC)
  - History: from listing (BTC perp 2019-09, ETH perp 2019-11)
  - Limit 1000 per page, paginate by startTime

Output: ~/smc-lib/projects/ob-vc/data-channels/funding/{SYMBOL}_funding.parquet
  columns: funding_time_ms, funding_rate, mark_price
"""
from __future__ import annotations
import pathlib
import subprocess
import sys
import time
import json
from datetime import datetime, timezone

import pandas as pd

SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT").upper()
OUT = pathlib.Path(__file__).resolve().parent / f"{SYMBOL}_funding.parquet"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
URL = "https://fapi.binance.com/fapi/v1/fundingRate"


def fetch_page(start_ms: int) -> list[dict]:
    url = f"{URL}?symbol={SYMBOL}&startTime={start_ms}&limit=1000"
    for attempt in range(5):
        try:
            r = subprocess.run(["curl", "-sS", "--connect-timeout", "10",
                                 "--max-time", "30", url],
                                capture_output=True, text=True, timeout=45)
            if r.returncode == 0 and r.stdout.strip().startswith("["):
                return json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after 5 attempts at start_ms={start_ms}")


def main():
    now_ms = int(time.time() * 1000)
    all_rows = []
    cursor = START_MS
    pages = 0
    print(f"[funding {SYMBOL}] fetching from {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).isoformat()}")

    while cursor < now_ms:
        chunk = fetch_page(cursor)
        if not chunk:
            break
        all_rows.extend(chunk)
        last_ms = int(chunk[-1]["fundingTime"])
        if last_ms <= cursor:
            break
        cursor = last_ms + 1
        pages += 1
        if pages % 10 == 0:
            print(f"  page {pages}: now @ {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}  rows={len(all_rows):,}")
        time.sleep(0.15)

    print(f"[funding {SYMBOL}] total rows: {len(all_rows):,}")
    if not all_rows:
        return

    df = pd.DataFrame(all_rows)
    df["funding_time_ms"] = df["fundingTime"].astype(int)
    df["funding_rate"] = df["fundingRate"].astype(float)
    # markPrice often empty string for pre-2022 records; coerce to NaN
    df["mark_price"] = pd.to_numeric(df["markPrice"], errors="coerce")
    df = df[["funding_time_ms", "funding_rate", "mark_price"]].drop_duplicates(subset="funding_time_ms")
    df = df.sort_values("funding_time_ms").reset_index(drop=True)
    df.to_parquet(OUT, index=False)
    first = datetime.fromtimestamp(df.funding_time_ms.iloc[0]/1000, tz=timezone.utc)
    last  = datetime.fromtimestamp(df.funding_time_ms.iloc[-1]/1000, tz=timezone.utc)
    print(f"[funding {SYMBOL}] saved -> {OUT}")
    print(f"  rows: {len(df):,}  ({first.date()} -> {last.date()})")
    print(f"  rate stats: mean={df.funding_rate.mean()*1e4:.2f} bp  std={df.funding_rate.std()*1e4:.2f} bp")
    print(f"  abs max: {df.funding_rate.abs().max()*1e4:.1f} bp")


if __name__ == "__main__":
    main()
