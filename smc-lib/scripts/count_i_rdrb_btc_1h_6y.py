"""Считает количество i-RDRB на BTCUSDT 1h за 6 лет.

Пагинирует через Binance API (limit=1000 на запрос).
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb

INTERVAL = "1h"
END = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)
START = END - timedelta(days=365 * 6)


def fetch_chunk(start_ms: int, end_ms: int):
    url = (
        f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={INTERVAL}"
        f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    return json.loads(subprocess.check_output(["curl", "-s", url], timeout=30))


def fetch_all():
    candles: list[Candle] = []
    cursor = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000)
    while cursor < end_ms:
        chunk = fetch_chunk(cursor, end_ms)
        if not chunk:
            break
        for k in chunk:
            candles.append(Candle(
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                open_time=int(k[0]),
            ))
        cursor = int(chunk[-1][0]) + 60 * 60 * 1000  # +1h to skip last fetched
        if len(chunk) < 1000:
            break
    return candles


print(f"Fetching BTCUSDT {INTERVAL} {START.date()} → {END.date()}...")
candles = fetch_all()
print(f"Fetched {len(candles)} candles "
      f"({datetime.fromtimestamp(candles[0].open_time/1000, tz=timezone.utc).date()} → "
      f"{datetime.fromtimestamp(candles[-1].open_time/1000, tz=timezone.utc).date()})")

counts = {"long": 0, "short": 0}
rdrb_counts = {"long_v1": 0, "long_v2": 0, "short_v1": 0, "short_v2": 0}

for i in range(len(candles) - 3):
    r = detect_i_rdrb(candles[i], candles[i + 1], candles[i + 2], candles[i + 3])
    if r is None:
        continue
    counts[r.direction] += 1
    rdrb_counts[f"{r.rdrb.direction}_{r.rdrb.variant.lower()}"] += 1

total = counts["long"] + counts["short"]
print(f"\nTotal i-RDRB on BTC {INTERVAL} over 6 years: {total}")
print(f"  LONG i-RDRB:  {counts['long']}   (= reversal on SHORT RDRB)")
print(f"  SHORT i-RDRB: {counts['short']}  (= reversal on LONG RDRB)")
print(f"\nBy underlying RDRB variant:")
for k, v in rdrb_counts.items():
    print(f"  RDRB {k:<10} → {v} i-RDRB")

print(f"\nFrequency: {total / (len(candles) / (365 * 24)):.1f} i-RDRB per year (avg)")
print(f"Probability per 4-candle window: {total / (len(candles) - 3) * 100:.3f}%")
