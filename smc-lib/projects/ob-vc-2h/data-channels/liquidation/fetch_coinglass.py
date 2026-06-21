"""Coinglass historical liquidation fetcher.

⚠ REQUIRES FREE API KEY:
   1. Register at https://www.coinglass.com → API → Get Free Key
   2. Free tier: 30 requests/minute, ~5y of history
   3. Save key to ~/smc-lib/projects/ob-vc/data-channels/liquidation/coinglass_key.txt

Endpoint (v4):
  GET https://open-api-v4.coinglass.com/api/futures/liquidation/history
    headers: { 'CG-API-KEY': <key> }
    params: symbol=BTCUSDT, interval=1h, limit=200, startTime, endTime

Output: ~/smc-lib/projects/ob-vc/data-channels/liquidation/{SYMBOL}_liq_{INTERVAL}.parquet
  columns: ts_ms, long_usd, short_usd, total_usd
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
KEY_PATH = pathlib.Path(__file__).resolve().parent / "coinglass_key.txt"
OUT = pathlib.Path(__file__).resolve().parent / f"{SYMBOL}_liq_{INTERVAL}.parquet"
START_MS = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
URL = "https://open-api-v4.coinglass.com/api/futures/liquidation/history"

INTERVAL_MS = {
    "1m": 60_000, "5m": 5*60_000, "15m": 15*60_000, "30m": 30*60_000,
    "1h": 60*60_000, "4h": 4*60*60_000, "12h": 12*60*60_000, "1d": 24*60*60_000,
}[INTERVAL]


def load_key() -> str:
    if not KEY_PATH.exists():
        raise SystemExit(
            f"\n⚠ Coinglass API key not found.\n"
            f"  1. Register at https://www.coinglass.com → API → Get Free Key\n"
            f"  2. Save key to: {KEY_PATH}\n"
            f"  3. Re-run this script\n"
        )
    return KEY_PATH.read_text().strip()


def fetch_page(key: str, start_ms: int, end_ms: int) -> list:
    url = (f"{URL}?symbol={SYMBOL}&interval={INTERVAL}"
           f"&startTime={start_ms}&endTime={end_ms}&limit=200")
    for attempt in range(5):
        try:
            r = subprocess.run([
                "curl", "-sS", "--connect-timeout", "10", "--max-time", "30",
                "-H", f"CG-API-KEY: {key}",
                "-H", "accept: application/json",
                url
            ], capture_output=True, text=True, timeout=45)
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                resp = json.loads(r.stdout)
                if resp.get("code") in (0, "0"):
                    return resp.get("data", [])
                else:
                    print(f"  API error: {resp.get('msg')}")
                    return []
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed at start_ms={start_ms}")


def main():
    key = load_key()
    now_ms = int(time.time() * 1000)
    all_rows = []
    cursor = START_MS
    win_ms = 200 * INTERVAL_MS
    page = 0

    print(f"[liq {SYMBOL} {INTERVAL}] fetching from {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}")

    while cursor < now_ms:
        end_ms = min(cursor + win_ms, now_ms)
        chunk = fetch_page(key, cursor, end_ms)
        if not chunk:
            cursor = end_ms + 1
            continue
        all_rows.extend(chunk)
        last_ts = int(chunk[-1].get("t") or chunk[-1].get("timestamp") or 0)
        if last_ts <= cursor:
            cursor = end_ms + 1
        else:
            cursor = last_ts + INTERVAL_MS
        page += 1
        if page % 10 == 0:
            print(f"  page {page}: now @ {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()}  rows={len(all_rows):,}")
        time.sleep(2.0)  # 30 req/min => sleep 2s

    if not all_rows:
        print(f"[liq {SYMBOL}] no data")
        return

    df = pd.DataFrame(all_rows)
    # Coinglass schema varies; expect fields like longLiquidationUsd, shortLiquidationUsd
    df = df.rename(columns={
        "t": "ts_ms", "timestamp": "ts_ms",
        "longLiquidationUsd": "long_usd",
        "shortLiquidationUsd": "short_usd",
    })
    df["ts_ms"] = df["ts_ms"].astype(int)
    if "long_usd" in df.columns and "short_usd" in df.columns:
        df["total_usd"] = df["long_usd"].astype(float) + df["short_usd"].astype(float)
    df = df.drop_duplicates(subset="ts_ms").sort_values("ts_ms").reset_index(drop=True)
    df.to_parquet(OUT, index=False)
    print(f"[liq {SYMBOL}] saved -> {OUT}")
    print(f"  rows: {len(df):,}")


if __name__ == "__main__":
    main()
