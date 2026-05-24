"""Вычисление maxV (ViC ASVK) на момент входа сделки 2026-05-19 LONG.

Anchor: 1m свеча с pattern_low (76144.71) в C2 (17:00 MSK = 14:00 UTC).
Конец интервала: entry fill в 2026-05-20 03:12 MSK = 00:12 UTC.
Granularity: 1m (соответствует LTF auto для chart_TF=1h, mlt=100).
"""
from __future__ import annotations

import csv
import pathlib
from datetime import datetime, timedelta, timezone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))


def load_range(start_utc, end_utc):
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            if t < start_utc: continue
            if t > end_utc: break
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


# C2 = 2026-05-19 14:00 UTC (= 17:00 MSK). Поищем 1m с low=76144.71
anchor_start = datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc)
anchor_end = datetime(2026, 5, 19, 15, 0, tzinfo=timezone.utc)

c2_bars = load_range(anchor_start, anchor_end)
pattern_low = 76144.71
anchor_bar = None
for t, o, h, l, c, v in c2_bars:
    if abs(l - pattern_low) < 0.01:
        anchor_bar = (t, o, h, l, c, v); break
if anchor_bar is None:
    # nearest
    anchor_bar = min(c2_bars, key=lambda x: x[3])

print(f"Anchor 1m: {anchor_bar[0].astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")
print(f"  O={anchor_bar[1]:.2f} H={anchor_bar[2]:.2f} L={anchor_bar[3]:.2f} C={anchor_bar[4]:.2f} V={anchor_bar[5]:.5f}")

# Entry fill = 2026-05-20 00:12 UTC (03:12 MSK)
entry_ts = datetime(2026, 5, 20, 0, 12, tzinfo=timezone.utc)
print(f"Entry fill: {entry_ts.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")

# Load 1m в интервале anchor → entry
window = load_range(anchor_bar[0], entry_ts)
print(f"\n1m bars в окне: {len(window)}")

# ASVK ViC formula
bull = [(t, o, h, l, c, v) for t, o, h, l, c, v in window if c > o]
bear = [(t, o, h, l, c, v) for t, o, h, l, c, v in window if c < o]

max_bull = max(bull, key=lambda x: x[5]) if bull else None
max_bear = max(bear, key=lambda x: x[5]) if bear else None

print(f"\nBull-1m count: {len(bull)},  max_bull_volume={max_bull[5]:.2f}  close={max_bull[4]:.2f}  time={max_bull[0].astimezone(MSK).strftime('%H:%M')} MSK") if max_bull else None
print(f"Bear-1m count: {len(bear)},  max_bear_volume={max_bear[5]:.2f}  close={max_bear[4]:.2f}  time={max_bear[0].astimezone(MSK).strftime('%H:%M')} MSK") if max_bear else None

if max_bull and max_bear:
    if max_bull[5] > max_bear[5]:
        maxV_dir = "BULL"
        maxV = max_bull[4]
        maxV_time = max_bull[0]
    else:
        maxV_dir = "BEAR"
        maxV = max_bear[4]
        maxV_time = max_bear[0]
elif max_bull:
    maxV_dir = "BULL"; maxV = max_bull[4]; maxV_time = max_bull[0]
else:
    maxV_dir = "BEAR"; maxV = max_bear[4]; maxV_time = max_bear[0]

print(f"\n=== maxV (ASVK ViC) ===")
print(f"  Дирекция: {maxV_dir}")
print(f"  maxV (close) = {maxV:.2f}")
print(f"  Время свечи: {maxV_time.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")

# Сравнение с entry
entry = 76635.88
print(f"\n=== Положение относительно entry ===")
print(f"  Entry (0.5 block):  {entry:.2f}")
print(f"  maxV:               {maxV:.2f}")
delta = maxV - entry
print(f"  maxV − entry:       {delta:+.2f}  ({delta/entry*100:+.3f}%)")
if maxV > entry:
    print(f"  → maxV ВЫШЕ entry  (resistance, потенциальный TP cap)")
else:
    print(f"  → maxV НИЖЕ entry  (support, под entry)")

# Также покажем относительно pattern_low и block
print(f"\n=== Положение в структуре паттерна ===")
print(f"  pattern_low:  76144.71")
print(f"  block:        [76596.00, 76675.76]")
print(f"  entry:        76635.88")
print(f"  maxV:         {maxV:.2f}")
if maxV < 76144.71: pos = "под pattern_low"
elif maxV < 76596.00: pos = "между pattern_low и block.bottom"
elif maxV <= 76675.76: pos = "ВНУТРИ block"
elif maxV < 76872.75: pos = "между block.top и C1.body_bottom (= POI top)"
else: pos = "выше POI"
print(f"  → maxV расположен: {pos}")
