"""Generic backfill: докачать 1m историю НАЗАД до указанной даты для любого SYMBOL.

Использование:
    python3 fetch_1m_backward.py ETHUSDT 2020-01-01
    python3 fetch_1m_backward.py SOLUSDT 2020-01-01
"""
from __future__ import annotations
import csv, pathlib, subprocess, sys, time, json
from datetime import datetime, timezone

SYMBOL = sys.argv[1].upper()
TARGET = sys.argv[2]  # "YYYY-MM-DD"
CSV_PATH = pathlib.Path.home() / f"traid-bot/data/{SYMBOL}_1m_vic_vadim.csv"
BINANCE_URL = "https://api.binance.com/api/v3/klines"

TARGET_START_MS = int(datetime.fromisoformat(f"{TARGET} 00:00:00").replace(tzinfo=timezone.utc).timestamp()*1000)


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
        url = f"{BINANCE_URL}?symbol={SYMBOL}&interval=1m&startTime={cursor}&endTime={end_ms}&limit=1000"
        for attempt in range(5):
            try:
                result = subprocess.run(["curl", "-sS", "--retry", "3", "--retry-delay", "2",
                                          "--connect-timeout", "10", "--max-time", "30", url],
                                          capture_output=True, text=True, timeout=45)
                if result.returncode == 0 and result.stdout.strip().startswith("["):
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"curl failed after 5 attempts on cursor {cursor}: {result.stderr if result else 'no result'}")
        chunk = json.loads(result.stdout)
        if not chunk:
            break
        out.extend(chunk)
        last = chunk[-1][0]
        if last <= cursor:
            break
        cursor = last + 60_000
        time.sleep(0.12)
    return out


first_ts = first_ts_in_csv()
first_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
target_dt = datetime.fromtimestamp(TARGET_START_MS / 1000, tz=timezone.utc)
print(f"[{SYMBOL}] CSV first: {first_dt.isoformat()}")
print(f"[{SYMBOL}] Target start: {target_dt.isoformat()}")

if TARGET_START_MS >= first_ts:
    print(f"[{SYMBOL}] Already covers target start. Nothing to do.")
    raise SystemExit(0)

print(f"[{SYMBOL}] Fetching backward: {target_dt.isoformat()} → {first_dt.isoformat()}")
klines = fetch_klines_range(TARGET_START_MS, first_ts)
print(f"[{SYMBOL}] Got {len(klines)} klines")
if not klines:
    print(f"[{SYMBOL}] No data returned — exchange listing date likely later than target.")
    raise SystemExit(1)

# Format rows (open_time, open, high, low, close, volume) — use space separator (same as ETH/SOL CSV)
new_rows = []
for k in klines:
    ts_ms = k[0]
    dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)
    ts_iso = dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    new_rows.append([ts_iso, k[1], k[2], k[3], k[4], k[5]])

print(f"[{SYMBOL}] Reading existing CSV...")
with CSV_PATH.open("r", encoding="utf-8") as f:
    header_line = f.readline()
    existing = f.read()

print(f"[{SYMBOL}] Writing {len(new_rows)} new rows + existing...")
tmp = CSV_PATH.with_suffix(".tmp")
with tmp.open("w", encoding="utf-8", newline="") as f:
    f.write(header_line)
    w = csv.writer(f)
    for r in new_rows:
        w.writerow(r)
    f.write(existing)
tmp.replace(CSV_PATH)
print(f"[{SYMBOL}] Done. CSV updated.")

with CSV_PATH.open("r", encoding="utf-8") as f:
    f.readline()
    first_new = f.readline().strip()
print(f"[{SYMBOL}] New first row: {first_new[:50]}")
