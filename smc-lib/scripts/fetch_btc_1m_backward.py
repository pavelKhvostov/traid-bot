"""Докачать историю BTCUSDT 1m НАЗАД до указанной даты, prepend к существующему CSV."""
from __future__ import annotations
import csv, pathlib, subprocess, time, json
from datetime import datetime, timezone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BINANCE_URL = "https://api.binance.com/api/v3/klines"

TARGET_START_STR = "2020-01-01 00:00:00"
TARGET_START_MS = int(datetime.fromisoformat(TARGET_START_STR).replace(tzinfo=timezone.utc).timestamp()*1000)

def first_ts_in_csv() -> int:
    with CSV_PATH.open("r", encoding="utf-8") as f:
        header = f.readline()
        first_line = f.readline().strip()
    ts_str = first_line.split(",")[0]
    return int(datetime.fromisoformat(ts_str).timestamp() * 1000)

def fetch_klines_range(start_ms: int, end_ms: int) -> list:
    out = []
    cursor = start_ms
    while cursor < end_ms:
        url = f"{BINANCE_URL}?symbol=BTCUSDT&interval=1m&startTime={cursor}&endTime={end_ms}&limit=1000"
        result = subprocess.run(["curl", "-sS", url], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        chunk = json.loads(result.stdout)
        if not chunk: break
        out.extend(chunk)
        last = chunk[-1][0]
        if last <= cursor: break
        cursor = last + 60_000
        time.sleep(0.12)
    return out

first_ts = first_ts_in_csv()
first_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
target_dt = datetime.fromtimestamp(TARGET_START_MS / 1000, tz=timezone.utc)
print(f"CSV first: {first_dt.isoformat()}")
print(f"Target start: {target_dt.isoformat()}")

if TARGET_START_MS >= first_ts:
    print("Already covers target start. Nothing to do.")
    raise SystemExit(0)

print(f"Fetching backward: {target_dt.isoformat()} → {first_dt.isoformat()}")
klines = fetch_klines_range(TARGET_START_MS, first_ts)
print(f"Got {len(klines)} klines")
if not klines:
    print("No data returned.")
    raise SystemExit(1)

# Format rows (open_time, open, high, low, close, volume)
new_rows = []
for k in klines:
    ts_ms = k[0]
    dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)
    ts_iso = dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    new_rows.append([ts_iso, k[1], k[2], k[3], k[4], k[5]])

# Prepend: read header + existing, write new
print("Reading existing CSV...")
with CSV_PATH.open("r", encoding="utf-8") as f:
    header_line = f.readline()
    existing = f.read()

print(f"Writing {len(new_rows)} new rows + existing...")
tmp = CSV_PATH.with_suffix(".tmp")
with tmp.open("w", encoding="utf-8", newline="") as f:
    f.write(header_line)
    w = csv.writer(f)
    for r in new_rows:
        w.writerow(r)
    f.write(existing)
tmp.replace(CSV_PATH)
print(f"Done. CSV updated.")

# Verify
with CSV_PATH.open("r", encoding="utf-8") as f:
    f.readline()
    first_new = f.readline().strip()
print(f"New first row: {first_new[:50]}")
