"""Fetch perpetual Open Interest history.

Source: Bybit v5 API (Binance limits OI history to ~30 days, Bybit goes back to 2021-01-01).
Endpoint: GET https://api.bybit.com/v5/market/open-interest
  - intervalTime: 5min, 15min, 30min, 1h, 4h, 1d
  - limit 200 per page, paginated with `cursor`
  - history available from ~2021-01-01 for linear perps

Output: ~/smc-lib/projects/ob-vc/data-channels/oi/{SYMBOL}_oi_{INTERVAL}.parquet
  columns: ts_ms, open_interest_coin

Note: BTC perp OI before 2021-01-01 is NOT available from any free source.
v1.5 ML will have OI=NaN for 2020 events.
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
INTERVAL = (sys.argv[2] if len(sys.argv) > 2 else "1h")
OUT = pathlib.Path(__file__).resolve().parent / f"{SYMBOL}_oi_{INTERVAL}.parquet"
START_MS = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
URL = "https://api.bybit.com/v5/market/open-interest"

INTERVAL_MS = {
    "5min": 5*60_000, "15min": 15*60_000, "30min": 30*60_000,
    "1h": 60*60_000, "4h": 4*60*60_000, "1d": 24*60*60_000,
}[INTERVAL]


def fetch_page(start_ms: int, end_ms: int) -> dict:
    url = (f"{URL}?category=linear&symbol={SYMBOL}&intervalTime={INTERVAL}"
           f"&startTime={start_ms}&endTime={end_ms}&limit=200")
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
    # ~200 records × interval per request
    win_ms = 200 * INTERVAL_MS
    page = 0

    print(f"[oi {SYMBOL} {INTERVAL}] fetching from {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}")

    while cursor < now_ms:
        end_ms = min(cursor + win_ms, now_ms)
        resp = fetch_page(cursor, end_ms)
        if resp.get("retCode") != 0:
            print(f"  API error: {resp.get('retMsg')}")
            cursor = end_ms + 1
            continue
        rows = resp.get("result", {}).get("list", [])
        if not rows:
            cursor = end_ms + 1
            page += 1
            continue
        all_rows.extend(rows)
        # Bybit returns DESCENDING — first row is newest. Use OLDEST (last in list) as advance marker.
        oldest_ts = int(rows[-1]["timestamp"])
        newest_ts = int(rows[0]["timestamp"])
        # advance window to next
        cursor = newest_ts + INTERVAL_MS
        page += 1
        if page % 10 == 0:
            print(f"  page {page}: now @ {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}  rows={len(all_rows):,}")
        time.sleep(0.20)

    print(f"[oi {SYMBOL} {INTERVAL}] total rows: {len(all_rows):,}")
    if not all_rows:
        return

    df = pd.DataFrame(all_rows)
    df["ts_ms"] = df["timestamp"].astype(int)
    df["open_interest_coin"] = df["openInterest"].astype(float)
    df = df[["ts_ms", "open_interest_coin"]].drop_duplicates(subset="ts_ms")
    df = df.sort_values("ts_ms").reset_index(drop=True)
    df.to_parquet(OUT, index=False)
    first = datetime.fromtimestamp(df.ts_ms.iloc[0]/1000, tz=timezone.utc)
    last  = datetime.fromtimestamp(df.ts_ms.iloc[-1]/1000, tz=timezone.utc)
    print(f"[oi {SYMBOL} {INTERVAL}] saved -> {OUT}")
    print(f"  rows: {len(df):,}  ({first.date()} -> {last.date()})")
    coverage_days = (df.ts_ms.iloc[-1] - df.ts_ms.iloc[0]) / 1000 / 86400
    expected = coverage_days * 86400 * 1000 / INTERVAL_MS
    print(f"  coverage: {coverage_days:.0f}d  density: {len(df)/expected*100:.1f}% of expected")


if __name__ == "__main__":
    main()
