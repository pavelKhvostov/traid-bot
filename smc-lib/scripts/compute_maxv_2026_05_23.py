"""maxV для 2026-05-23 LONG (LOSS) — сравнение с 2026-05-19 (WIN)."""
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


# Pattern 2026-05-23 LONG:
# C1 = 02:00 MSK = 23:00 UTC 2026-05-22
# C2 = 03:00 MSK = 00:00 UTC 2026-05-23 (низ 75220.00)
# C3 = 04:00 MSK = 01:00 UTC
# C4 = 05:00 MSK = 02:00 UTC
# C5 = 06:00 MSK = 03:00 UTC, close at 07:00 MSK = 04:00 UTC
# Entry fill = 08:24 MSK = 05:24 UTC
# Exit (LOSS at SL=75220) = 10:31 MSK = 07:31 UTC

pattern_low = 75220.00
entry = 75494.92
block = (75489.84, 75500.00)
poi = (75489.84, 75539.50)

# Поиск anchor 1m в C2 (00:00-01:00 UTC)
c2_bars = load_range(
    datetime(2026, 5, 23, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 5, 23, 1, 0, tzinfo=timezone.utc),
)
anchor_bar = None
for t, o, h, l, c, v in c2_bars:
    if abs(l - pattern_low) < 0.01:
        anchor_bar = (t, o, h, l, c, v); break
if anchor_bar is None:
    anchor_bar = min(c2_bars, key=lambda x: x[3])

print(f"Anchor 1m: {anchor_bar[0].astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")
print(f"  O={anchor_bar[1]:.2f} H={anchor_bar[2]:.2f} L={anchor_bar[3]:.2f} C={anchor_bar[4]:.2f} V={anchor_bar[5]:.5f}")

entry_ts = datetime(2026, 5, 23, 5, 24, tzinfo=timezone.utc)
print(f"Entry fill: {entry_ts.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")

window = load_range(anchor_bar[0], entry_ts)
print(f"\n1m bars в окне: {len(window)}")

bull = [b for b in window if b[4] > b[1]]
bear = [b for b in window if b[4] < b[1]]
max_bull = max(bull, key=lambda x: x[5]) if bull else None
max_bear = max(bear, key=lambda x: x[5]) if bear else None

if max_bull:
    print(f"\nBull-1m count: {len(bull)},  max_bull_volume={max_bull[5]:.2f}  close={max_bull[4]:.2f}  time={max_bull[0].astimezone(MSK).strftime('%H:%M')} MSK")
if max_bear:
    print(f"Bear-1m count: {len(bear)},  max_bear_volume={max_bear[5]:.2f}  close={max_bear[4]:.2f}  time={max_bear[0].astimezone(MSK).strftime('%H:%M')} MSK")

if max_bull and max_bear:
    if max_bull[5] > max_bear[5]:
        maxV_dir = "BULL"; maxV = max_bull[4]; maxV_time = max_bull[0]
    else:
        maxV_dir = "BEAR"; maxV = max_bear[4]; maxV_time = max_bear[0]
elif max_bull:
    maxV_dir = "BULL"; maxV = max_bull[4]; maxV_time = max_bull[0]
else:
    maxV_dir = "BEAR"; maxV = max_bear[4]; maxV_time = max_bear[0]

print(f"\n=== maxV (ASVK ViC) ===")
print(f"  Дирекция: {maxV_dir}")
print(f"  maxV (close) = {maxV:.2f}")
print(f"  Время: {maxV_time.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK")

delta = maxV - entry
print(f"\n=== Положение ===")
print(f"  Entry:    {entry:.2f}")
print(f"  maxV:     {maxV:.2f}")
print(f"  maxV − entry: {delta:+.2f} ({delta/entry*100:+.3f}%)")
print(f"  R_unit:   {entry - pattern_low:.2f}")
print(f"  maxV в R-unit от entry: {delta / (entry - pattern_low):+.3f} R")

if maxV < pattern_low: pos = "ПОД pattern_low (!)"
elif maxV < block[0]: pos = "между pattern_low и block.bottom"
elif maxV <= block[1]: pos = "ВНУТРИ block"
elif maxV < poi[1]: pos = "между block.top и POI.top"
elif maxV > entry: pos = f"ВЫШЕ entry на {delta:+.2f}"
else: pos = "около entry"
print(f"\n  → {pos}")
