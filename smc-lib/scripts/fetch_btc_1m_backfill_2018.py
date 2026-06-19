"""Backfill BTCUSDT 1m с 2018-01-01 до начала текущего CSV (обычно 2020-01-01).

Fetches forward from start_target → existing CSV start. Saves into separate file,
then merges into main CSV (prepend sorted).
"""
from __future__ import annotations
import csv, subprocess, time, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BACKFILL_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_backfill_2018.csv"
BINANCE_URL = "https://api.binance.com/api/v3/klines"

START_MS = int(datetime(2018,1,1,tzinfo=timezone.utc).timestamp()*1000)

def first_ts_in_csv():
    with CSV_PATH.open() as f:
        f.readline()  # header
        first = f.readline().strip()
    ts_str = first.split(",")[0]
    return int(datetime.fromisoformat(ts_str).timestamp()*1000)

def fetch_chunk(start_ms, end_ms):
    url = f"{BINANCE_URL}?symbol=BTCUSDT&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=1000"
    for attempt in range(3):
        try:
            r = subprocess.run(["curl","-sS",url], capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return json.loads(r.stdout)
        except Exception as e:
            print(f"  retry {attempt+1}: {e}")
        time.sleep(2)
    return []

CUR_START_MS = first_ts_in_csv()
print(f"Current CSV starts: {datetime.fromtimestamp(CUR_START_MS/1000, tz=timezone.utc)}")
print(f"Target start:       {datetime.fromtimestamp(START_MS/1000, tz=timezone.utc)}")

if CUR_START_MS <= START_MS:
    print("CSV уже покрывает 2018+, выход")
    exit(0)

# Determine resume point
if BACKFILL_PATH.exists():
    with BACKFILL_PATH.open() as f:
        f.readline()
        lines = f.readlines()
    if lines:
        last = lines[-1].strip().split(",")
        cursor_ms = int(datetime.fromisoformat(last[0]).timestamp()*1000) + 60_000
        print(f"Resuming from: {datetime.fromtimestamp(cursor_ms/1000, tz=timezone.utc)} ({len(lines)} rows already)")
    else:
        cursor_ms = START_MS
else:
    cursor_ms = START_MS
    with BACKFILL_PATH.open("w") as f:
        f.write("open_time,open,high,low,close,volume\n")

total_fetched = 0
batch_count = 0
t0 = time.time()
with BACKFILL_PATH.open("a") as f:
    while cursor_ms < CUR_START_MS:
        end_chunk = min(cursor_ms + 1000*60_000, CUR_START_MS)  # up to 1000 1m bars
        chunk = fetch_chunk(cursor_ms, end_chunk)
        if not chunk:
            print(f"  Empty chunk at {datetime.fromtimestamp(cursor_ms/1000,tz=timezone.utc)}, advancing by 1000m")
            cursor_ms += 1000*60_000
            continue
        for k in chunk:
            ts_ms = k[0]
            dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc).isoformat()
            f.write(f"{dt},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]}\n")
        last_ts = chunk[-1][0]
        cursor_ms = last_ts + 60_000
        total_fetched += len(chunk)
        batch_count += 1
        if batch_count % 30 == 0:
            elapsed = time.time() - t0
            rate = total_fetched/elapsed
            remaining = (CUR_START_MS - cursor_ms) / 60_000
            eta_s = remaining/rate if rate>0 else 0
            print(f"  [{batch_count} batches] +{total_fetched:,} bars  "
                  f"now at {datetime.fromtimestamp(cursor_ms/1000,tz=timezone.utc)}  "
                  f"rate={rate:.0f}/s  ETA={eta_s/60:.1f}min")
        time.sleep(0.05)  # rate limit

print(f"\nFetched {total_fetched:,} bars in {(time.time()-t0)/60:.1f}min")
print(f"Saved to {BACKFILL_PATH}")
print(f"\nNow merging into main CSV (prepend backfill + sort)...")

# Merge: read both, sort by ts, write
import pandas as pd
df_back = pd.read_csv(BACKFILL_PATH)
df_main = pd.read_csv(CSV_PATH)
df_full = pd.concat([df_back, df_main]).drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
print(f"  Backfill rows: {len(df_back):,}, main rows: {len(df_main):,}, merged: {len(df_full):,}")
df_full.to_csv(CSV_PATH, index=False)
print(f"  Updated {CSV_PATH}")
