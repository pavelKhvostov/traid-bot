"""Fetch Deribit volatility index history (DVOL = BTC implied vol, BVIV = ETH).

Endpoint: GET https://www.deribit.com/api/v2/public/get_volatility_index_data
  - currency: BTC | ETH
  - resolution: 60 (1min), 3600 (1h), 43200 (12h), 86400 (1d)
  - returns: list of [ts_ms, open, high, low, close]
  - history: BTC DVOL from ~2021-04, ETH DVOL from ~2022-01

For ML on 2h ob_vc setups we fetch 1h resolution for richness.

Output: ~/smc-lib/projects/ob-vc/data-channels/options/{CURRENCY}_dvol_{RES}.parquet
  columns: ts_ms, open, high, low, close
"""
from __future__ import annotations
import pathlib
import subprocess
import sys
import time
import json
from datetime import datetime, timezone

import pandas as pd

CURRENCY = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
RES = (sys.argv[2] if len(sys.argv) > 2 else "1h")
OUT = pathlib.Path(__file__).resolve().parent / f"{CURRENCY}_dvol_{RES}.parquet"

START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
RES_MS = {"1m": 60_000, "1h": 3_600_000, "12h": 43_200_000, "1d": 86_400_000}[RES]
RES_PARAM = {"1m": 60, "1h": 3600, "12h": 43200, "1d": 86400}[RES]


def fetch_page(start_ms: int, end_ms: int) -> dict:
    url = (f"{URL}?currency={CURRENCY}&start_timestamp={start_ms}"
           f"&end_timestamp={end_ms}&resolution={RES_PARAM}")
    for attempt in range(5):
        try:
            r = subprocess.run(["curl", "-sS", "--connect-timeout", "10",
                                 "--max-time", "30", url],
                                capture_output=True, text=True, timeout=45)
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                return json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed at start_ms={start_ms}")


def main():
    now_ms = int(time.time() * 1000)
    all_rows = []
    cursor = START_MS
    # Deribit caps response at 1000 candles per request — keep window matched
    win_ms = 1000 * RES_MS
    page = 0

    print(f"[dvol {CURRENCY} {RES}] fetching from {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}")

    while cursor < now_ms:
        end_ms = min(cursor + win_ms, now_ms)
        resp = fetch_page(cursor, end_ms)
        data = resp.get("result", {}).get("data", [])
        if not data:
            cursor = end_ms + 1
            page += 1
            continue
        for row in data:
            ts, o, h, l, c = row[:5]
            all_rows.append((int(ts), float(o), float(h), float(l), float(c)))
        last_ts = int(data[-1][0])
        if last_ts <= cursor:
            cursor = end_ms + 1
        else:
            cursor = last_ts + RES_MS
        page += 1
        if page % 5 == 0:
            print(f"  page {page}: now @ {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}  rows={len(all_rows):,}")
        time.sleep(0.20)

    print(f"[dvol {CURRENCY} {RES}] total rows: {len(all_rows):,}")
    if not all_rows:
        return

    df = pd.DataFrame(all_rows, columns=["ts_ms", "open", "high", "low", "close"])
    df = df.drop_duplicates(subset="ts_ms").sort_values("ts_ms").reset_index(drop=True)
    df.to_parquet(OUT, index=False)
    first = datetime.fromtimestamp(df.ts_ms.iloc[0]/1000, tz=timezone.utc)
    last  = datetime.fromtimestamp(df.ts_ms.iloc[-1]/1000, tz=timezone.utc)
    print(f"[dvol {CURRENCY} {RES}] saved -> {OUT}")
    print(f"  rows: {len(df):,}  ({first.date()} -> {last.date()})")
    print(f"  IV stats: mean={df.close.mean():.1f}%  std={df.close.std():.1f}%")
    print(f"  IV range: {df.close.min():.1f}% - {df.close.max():.1f}%")


if __name__ == "__main__":
    main()
