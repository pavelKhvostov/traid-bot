"""Generic докачка недостающих 1m свечей с Binance public REST.

Использование:
    python3 fetch_1m_missing.py BTCUSDT
    python3 fetch_1m_missing.py SOLUSDT
    python3 fetch_1m_missing.py ETHUSDT

CSV формат: open_time,open,high,low,close,volume
Путь CSV: ~/traid-bot/data/<SYMBOL>_1m_vic_vadim.csv
"""
from __future__ import annotations

import csv
import pathlib
import subprocess
import sys
import time
import json
from datetime import datetime, timezone

SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else 'BTCUSDT').upper()
CSV_PATH = pathlib.Path.home() / "traid-bot/data" / f"{SYMBOL}_1m_vic_vadim.csv"
BINANCE_URL = "https://api.binance.com/api/v3/klines"


def last_ts_in_csv() -> int:
    with CSV_PATH.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        chunk = min(2048, size)
        f.seek(-chunk, 2)
        tail = f.read().decode("utf-8", errors="ignore")
    last_line = [ln for ln in tail.strip().split("\n") if ln][-1]
    ts_str = last_line.split(",")[0]
    return int(datetime.fromisoformat(ts_str).timestamp() * 1000)


def fetch_klines(start_ms: int, end_ms: int) -> list:
    out = []
    cursor = start_ms
    while cursor < end_ms:
        url = f"{BINANCE_URL}?symbol={SYMBOL}&interval=1m&startTime={cursor}&limit=1000"
        result = subprocess.run(["curl", "-sS", url], capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        chunk = json.loads(result.stdout)
        if not chunk:
            break
        out.extend(chunk)
        last = chunk[-1][0]
        if last <= cursor:
            break
        cursor = last + 60_000
        time.sleep(0.15)
    return out


if not CSV_PATH.exists():
    raise SystemExit(f"CSV not found: {CSV_PATH}")

last_ts = last_ts_in_csv()
last_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)
print(f"[{SYMBOL}] CSV last: {last_dt.isoformat()}")

now_ms = int(time.time() * 1000)
start_ms = last_ts + 60_000
print(f"[{SYMBOL}] Fetching from {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).isoformat()} "
      f"to now ({datetime.fromtimestamp(now_ms/1000, tz=timezone.utc).isoformat()})")

klines = fetch_klines(start_ms, now_ms)
print(f"[{SYMBOL}] Got {len(klines)} klines from Binance")

new_rows = []
for k in klines:
    open_time_ms, o, h, l, c, v, close_time_ms, *_ = k
    if close_time_ms >= now_ms:
        continue
    dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
    new_rows.append((dt.isoformat(), o, h, l, c, v))

print(f"[{SYMBOL}] Closed bars to append: {len(new_rows)}")
if new_rows:
    print(f"  First: {new_rows[0][0]}")
    print(f"  Last:  {new_rows[-1][0]}")

with CSV_PATH.open("a", newline="") as f:
    w = csv.writer(f)
    for r in new_rows:
        w.writerow(r)
print(f"[{SYMBOL}] Appended {len(new_rows)} rows to {CSV_PATH}")
