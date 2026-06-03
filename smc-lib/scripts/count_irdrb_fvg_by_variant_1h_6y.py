"""Поиск всех i-RDRB+FVG на BTC 1h за последние 6 лет и разделение по underlying RDRB variant.

Используется smc-lib canonical detector — `detect_i_rdrb_fvg`, который через цепочку
вызывает `detect_rdrb` с автоматическим определением variant (V1/V2):
- V1: block ⊂ POI (liq subzone непусто, C3-wick не дотягивается до тела C1)
- V2: block == POI (liq пусто, C3-wick дотягивается до тела C1)
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from patterns.i_rdrb_fvg.code import detect_i_rdrb_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF_MIN = 60


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate_epoch(d, tf_min):
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


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')


def fmt_short(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d')


print("Loading 1m...")
t0 = time.time()
data = load_1m()
print(f"  {len(data):,} 1m rows loaded ({time.time()-t0:.1f}s)")

# 1h aggregation
print("Aggregating to 1h...")
t1 = time.time()
bars = aggregate_epoch(data, TF_MIN)
print(f"  {len(bars):,} 1h bars ({time.time()-t1:.1f}s)")

# Окно: последние 6 лет
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars_in_window = [b for b in bars if b[0] >= window_start_ms]
print(f"Окно: {fmt(bars_in_window[0][0])} → {fmt(bars_in_window[-1][0])}  ({len(bars_in_window):,} 1h баров)")

candles = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_in_window]

# Scan для i-RDRB+FVG (5-свечное окно)
print("\nScanning i-RDRB+FVG patterns...")
t2 = time.time()

hits = []
for i in range(len(candles) - 4):
    c1, c2, c3, c4, c5 = candles[i:i+5]
    r = detect_i_rdrb_fvg(c1, c2, c3, c4, c5)
    if r:
        hits.append({
            'c1_ts': bars_in_window[i][0],
            'direction': r.direction,
            'rdrb_variant': r.irdrb.rdrb.variant,
            'rdrb_direction': r.irdrb.rdrb.direction,
            'block': r.irdrb.rdrb.block,
            'poi': r.irdrb.rdrb.poi,
            'fvg_zone': r.fvg.zone,
            'c4_close': c4.close,
        })

print(f"  Found {len(hits):,} i-RDRB+FVG ({time.time()-t2:.1f}s)\n")

# Split by RDRB variant
v1 = [h for h in hits if h['rdrb_variant'] == 'V1']
v2 = [h for h in hits if h['rdrb_variant'] == 'V2']

# Also split by direction
v1_long = [h for h in v1 if h['direction'] == 'long']
v1_short = [h for h in v1 if h['direction'] == 'short']
v2_long = [h for h in v2 if h['direction'] == 'long']
v2_short = [h for h in v2 if h['direction'] == 'short']

print(f"{'='*68}")
print(f"  i-RDRB + FVG на BTC 1h за 6 лет — split by underlying RDRB variant")
print(f"{'='*68}\n")
print(f"  Total found:           {len(hits):>5}")
print(f"  ├── V1 (block ⊂ POI):  {len(v1):>5}  ({len(v1)/len(hits)*100:>5.1f}%)")
print(f"  │     ├── LONG  i-RDRB:  {len(v1_long):>5}")
print(f"  │     └── SHORT i-RDRB:  {len(v1_short):>5}")
print(f"  └── V2 (block == POI): {len(v2):>5}  ({len(v2)/len(hits)*100:>5.1f}%)")
print(f"        ├── LONG  i-RDRB:  {len(v2_long):>5}")
print(f"        └── SHORT i-RDRB:  {len(v2_short):>5}")

print(f"\n  (forensic baseline в проекте was ~780-808 — для калибровки)")
print(f"\n--- Sample first 5 V1 hits ---")
for h in v1[:5]:
    print(f"  {fmt_short(h['c1_ts'])}  {h['direction']:<5}  block={h['block'][0]:.0f}-{h['block'][1]:.0f}  fvg={h['fvg_zone'][0]:.0f}-{h['fvg_zone'][1]:.0f}")

print(f"\n--- Sample first 5 V2 hits ---")
for h in v2[:5]:
    print(f"  {fmt_short(h['c1_ts'])}  {h['direction']:<5}  block={h['block'][0]:.0f}-{h['block'][1]:.0f}  fvg={h['fvg_zone'][0]:.0f}-{h['fvg_zone'][1]:.0f}")

# Сохранить детали в CSV для последующего бектеста
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/irdrb_fvg_1h_6y_by_variant.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['c1_open_time', 'direction', 'rdrb_variant', 'block_low', 'block_high', 'poi_low', 'poi_high', 'fvg_low', 'fvg_high'])
    for h in hits:
        w.writerow([
            datetime.fromtimestamp(h['c1_ts']/1000, tz=timezone.utc).isoformat(),
            h['direction'],
            h['rdrb_variant'],
            f"{h['block'][0]:.2f}", f"{h['block'][1]:.2f}",
            f"{h['poi'][0]:.2f}", f"{h['poi'][1]:.2f}",
            f"{h['fvg_zone'][0]:.2f}", f"{h['fvg_zone'][1]:.2f}",
        ])
print(f"\nSaved details → {OUT}")
print(f"Total time: {time.time()-t0:.1f}s")
