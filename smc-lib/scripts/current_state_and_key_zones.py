"""Текущее состояние BTC + анализ положения относительно ключевых D-зон."""
from __future__ import annotations

import csv
import pathlib
from datetime import datetime, timedelta, timezone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')


data = load_1m()
last_ts, _, _, _, last_close = data[-1]
print(f"Last 1m: {fmt(last_ts)}  close = {last_close:.2f}\n")

# Сегодняшний D = с 00:00 UTC 24-го
today_open_ms = int(datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
today_1m = [r for r in data if r[0] >= today_open_ms]
if today_1m:
    o = today_1m[0][1]
    h = max(r[2] for r in today_1m)
    l = min(r[3] for r in today_1m)
    c = today_1m[-1][4]
    print(f"Today's forming D-bar (24-05 от 00:00 UTC):")
    print(f"  O={o:.2f}  H={h:.2f}  L={l:.2f}  C={c:.2f}  range={h-l:.2f}")
    print(f"  bars so far: {len(today_1m)} ({len(today_1m)/60:.1f} hours of 24)\n")

# Вчерашний (закрытый) D = 23-05
yesterday_open_ms = int(datetime(2026, 5, 23, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
yesterday_close_ms = today_open_ms
y_1m = [r for r in data if yesterday_open_ms <= r[0] < yesterday_close_ms]
if y_1m:
    yo = y_1m[0][1]; yh = max(r[2] for r in y_1m); yl = min(r[3] for r in y_1m); yc = y_1m[-1][4]
    print(f"Yesterday closed D (23-05):  O={yo:.2f}  H={yh:.2f}  L={yl:.2f}  C={yc:.2f}\n")

# Ключевые активные зоны (свежие, в диапазоне +-3% от текущей цены)
print(f"=== Zones near current price {last_close:.2f} (±5%) ===\n")
zones = [
    # (label, low, high)
    ("FH 05-21 (level)",       78200, 78200),
    ("FH 05-14 (level)",       82048, 82048),
    ("FH 05-10 (level)",       82479, 82479),
    ("FH 05-06 (top swept)",   82850, 82850),
    ("FL 05-18 (level)",       76051, 76051),
    ("FL 05-08 (level)",       79181, 79181),

    ("SHORT OB 05-22 (zone)",  75540, 78200),
    ("SHORT OB 05-22 breaker", 75540, 77552),
    ("SHORT RDRB 05-23 POI",   76752, 77552),
    ("SHORT RDRB 05-23 block", 76752, 77404),
    ("LONG OB 05-20 zone",     76145, 77552),
    ("LONG RDRB 05-21 POI/V2", 77002, 77415),
    ("SHORT i_rdrb 05-22 V2",  77002, 77415),

    ("SHORT FVG 05-17 (gap)",  78600, 78659),
    ("SHORT FVG 05-08 (gap)",  80500, 80731),
    ("LONG FVG 05-05 (gap)",   79447, 79809),
    ("LONG FVG 05-02 (gap)",   76669, 78040),
]

zones_sorted = sorted(zones, key=lambda z: -z[2])
for label, lo, hi in zones_sorted:
    if abs(((lo + hi) / 2 - last_close) / last_close) > 0.05:
        continue
    if lo == hi:
        rel = (lo - last_close) / last_close * 100
        marker = "↑" if lo > last_close else "↓"
        print(f"  {marker} {label:<32}  level {lo:.0f}  ({rel:+.2f}% от close)")
    else:
        pos = "above" if lo > last_close else ("below" if hi < last_close else "INSIDE")
        rel_low = (lo - last_close) / last_close * 100
        rel_high = (hi - last_close) / last_close * 100
        print(f"  {pos:<6}  {label:<32}  [{lo:.0f}, {hi:.0f}]  ({rel_low:+.2f}% / {rel_high:+.2f}%)")
