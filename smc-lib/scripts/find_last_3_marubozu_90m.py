"""Найти 3 крайних marubozu на BTC 90m по canon Pine WICK.ED."""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.marubozu.code import detect_marubozu

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF_MIN = 90


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_min):
    """epoch-anchor aggregation."""
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')


print("Loading 1m..."); data = load_1m()
candles_90m_raw = aggregate(data, TF_MIN)

# Не считаем последнюю свечу если она не закрыта (последний 1m в данных < open+90m)
last_1m_ts = data[-1][0]
last_bucket_open = candles_90m_raw[-1][0]
if last_1m_ts < last_bucket_open + TF_MIN * 60_000 - 60_000:  # последняя 1m не завершает 90m
    candles_90m = candles_90m_raw[:-1]
    print(f"Skipping unclosed last 90m bar at {fmt(last_bucket_open)}")
else:
    candles_90m = candles_90m_raw

print(f"Total closed 90m candles: {len(candles_90m)}")

marubozu_hits = []
for ts, o, h, l, c in candles_90m:
    r = detect_marubozu(Candle(open=o, high=h, low=l, close=c, open_time=ts))
    if r is not None:
        marubozu_hits.append((ts, o, h, l, c, r.direction, r.zone))

print(f"Total marubozu on 90m: {len(marubozu_hits)}")

last3 = marubozu_hits[-3:]
print(f"\n=== 3 крайних marubozu на BTC 90m ===\n")
for i, (ts, o, h, l, c, direction, zone) in enumerate(last3, 1):
    body = abs(c - o)
    rng = h - l
    arrow = "▲" if direction == "long" else "▼"
    opp_wick = (h - c) if direction == "long" else (c - l)
    print(f"{i}. {arrow} {direction.upper():<5}  open_time = {fmt(ts)}  (close = {fmt(ts + TF_MIN * 60_000)})")
    print(f"   O={o:.2f}  H={h:.2f}  L={l:.2f}  C={c:.2f}")
    print(f"   body={body:.2f}  range={rng:.2f}  body/range={body/rng:.3f}  opp_wick={opp_wick:.2f}")
    print(f"   zone = [{zone[0]:.2f}, {zone[1]:.2f}] (тело свечи)")
    print()
