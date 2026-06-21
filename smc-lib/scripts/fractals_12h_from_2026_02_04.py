"""Williams N=2 fractals на 12h timeframe, начиная с 2026-02-04.

Вывод: каждый fractal с центром >= 2026-02-04 00:00 UTC.
Колонки: time MSK (center) | direction | level | confirm MSK (= center + 3*12h)
+ короткий комментарий: пройден ли уровень потом (swept?) — first touch ts.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF_MS = 12 * MS_HOUR

START_MSK = datetime(2026, 2, 4, 0, 0, tzinfo=MSK)
START_MS = int(START_MSK.timestamp() * 1000)


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_ms):
    out = []; cb = None; o = h = l = c = 0.0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m...")
data = load_1m()
print(f"  {len(data):,} rows")
bars = aggregate(data, TF_MS)
print(f"  {len(bars):,} 12h bars")

# numpy для first-touch
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


def first_touch_after(level, after_ts, kind):
    i0 = int(np.searchsorted(ts_arr, after_ts, side='left'))
    if i0 >= len(ts_arr): return None
    if kind == "high":
        mask = hi_arr[i0:] >= level
    else:
        mask = lo_arr[i0:] <= level
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')


# Detect fractals (N=2 → window 5)
fractals = []
for i in range(2, len(bars) - 2):
    f = detect_fractal(bars[i-2:i+3], n=2)
    if f is None: continue
    center_ts = bars[i].open_time
    if center_ts < START_MS: continue
    confirm_ts = center_ts + 3 * TF_MS
    # first touch проверяем после confirm_ts (потенциальное снятие уровня в future)
    ftouch = first_touch_after(f.level, confirm_ts, f.direction)
    fractals.append({
        "dir": f.direction, "level": f.level,
        "center_ts": center_ts, "confirm_ts": confirm_ts,
        "first_touch": ftouch,
    })

print(f"\n{'='*100}")
print(f" 12h fractals с {START_MSK.strftime('%Y-%m-%d MSK')} (Williams N=2)")
print(f"{'='*100}")
print(f"  всего {len(fractals)} фракталов "
      f"(FH={sum(1 for f in fractals if f['dir']=='high')}, "
      f"FL={sum(1 for f in fractals if f['dir']=='low')})\n")

print(f"{'#':>3}  {'type':>4}  {'center (pivot 12h)':<22}  {'level':>9}  "
      f"{'confirmed at':<22}  {'first touch after':<22}  status")
print("-" * 110)

now_ms = ts_arr[-1]
for idx, f in enumerate(fractals, 1):
    glyph = "▼ FH" if f["dir"] == "high" else "▲ FL"
    swept = ""
    if f["first_touch"] is None:
        swept = "💎 UNTOUCHED"
        ftstr = "—"
    else:
        ftstr = fmt(f["first_touch"])
        hours_after = (f["first_touch"] - f["confirm_ts"]) / MS_HOUR
        if hours_after < 0:
            swept = "(touched during confirm window)"
        else:
            swept = f"swept after {hours_after:.0f}h"
    print(f"{idx:>3}  {glyph}  {fmt(f['center_ts']):<22}  {f['level']:>9.1f}  "
          f"{fmt(f['confirm_ts']):<22}  {ftstr:<22}  {swept}")

print(f"\nUnswept (active) levels:")
active = [f for f in fractals if f["first_touch"] is None]
print(f"  FH (resistance): " + ", ".join(f"{f['level']:.0f} ({fmt(f['center_ts'])[:16]})" for f in active if f["dir"] == "high"))
print(f"  FL (support):    " + ", ".join(f"{f['level']:.0f} ({fmt(f['center_ts'])[:16]})" for f in active if f["dir"] == "low"))
