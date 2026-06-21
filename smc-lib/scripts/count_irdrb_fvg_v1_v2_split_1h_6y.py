"""i-RDRB+FVG на BTC 1h за 6 лет, разделённое по FVG-варианту:

  V1: 5-свечный паттерн, FVG на (C3, C4, C5) — canonical
  V2: 6-свечный паттерн, FVG на (C4, C5, C6) — continuation FVG ПОСЛЕ i-RDRB
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

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


print("Loading 1m..."); t0 = time.time()
data = load_1m()
bars = aggregate_epoch(data, TF_MIN)
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars_in_window = [b for b in bars if b[0] >= window_start_ms]
print(f"  {len(bars_in_window):,} 1h bars in 6y window  ({fmt(bars_in_window[0][0])} → {fmt(bars_in_window[-1][0])})")

candles = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_in_window]

print("\nScanning...")
v1_hits = []   # FVG на C3, C4, C5
v2_hits = []   # FVG на C4, C5, C6
both_hits = [] # одновременно V1 и V2 для того же i-RDRB
irdrb_count = 0

# Нужно 6 свечей минимум для проверки V2
for i in range(len(candles) - 5):
    c1, c2, c3, c4, c5, c6 = candles[i:i+6]

    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None:
        continue
    irdrb_count += 1

    # V1: FVG на (C3, C4, C5)
    fvg_v1 = detect_fvg(c3, c4, c5)
    v1_ok = fvg_v1 is not None and fvg_v1.direction == ir.direction

    # V2: FVG на (C4, C5, C6)
    fvg_v2 = detect_fvg(c4, c5, c6)
    v2_ok = fvg_v2 is not None and fvg_v2.direction == ir.direction

    if v1_ok:
        v1_hits.append({
            'c1_ts': bars_in_window[i][0],
            'direction': ir.direction,
            'rdrb_variant': ir.rdrb.variant,
            'block': ir.rdrb.block,
            'poi': ir.rdrb.poi,
            'fvg_zone': fvg_v1.zone,
        })
    if v2_ok:
        v2_hits.append({
            'c1_ts': bars_in_window[i][0],
            'direction': ir.direction,
            'rdrb_variant': ir.rdrb.variant,
            'block': ir.rdrb.block,
            'poi': ir.rdrb.poi,
            'fvg_zone': fvg_v2.zone,
        })
    if v1_ok and v2_ok:
        both_hits.append({
            'c1_ts': bars_in_window[i][0],
            'direction': ir.direction,
        })

print(f"  i-RDRB total (C1-C4): {irdrb_count:,}")
print(f"  V1 (FVG on C3-C4-C5): {len(v1_hits):,}")
print(f"  V2 (FVG on C4-C5-C6): {len(v2_hits):,}")
print(f"  Both (V1 ∩ V2):        {len(both_hits):,}\n")

# Split V2 by direction and underlying RDRB variant
v2_long = [h for h in v2_hits if h['direction'] == 'long']
v2_short = [h for h in v2_hits if h['direction'] == 'short']
v2_rdrb_v1 = [h for h in v2_hits if h['rdrb_variant'] == 'V1']
v2_rdrb_v2 = [h for h in v2_hits if h['rdrb_variant'] == 'V2']

print(f"{'='*70}")
print(f"  i-RDRB+FVG V1 vs V2 split — BTC 1h за 6y")
print(f"{'='*70}\n")

print(f"  V1 (FVG on C3-C4-C5, 5-bar pattern):  {len(v1_hits):>5}")
v1_long = [h for h in v1_hits if h['direction'] == 'long']
v1_short = [h for h in v1_hits if h['direction'] == 'short']
print(f"     ├── LONG:  {len(v1_long):>5}")
print(f"     └── SHORT: {len(v1_short):>5}\n")

print(f"  V2 (FVG on C4-C5-C6, 6-bar pattern):  {len(v2_hits):>5}")
print(f"     ├── LONG:  {len(v2_long):>5}")
print(f"     └── SHORT: {len(v2_short):>5}")
print(f"  underlying RDRB подвыборка V2:")
print(f"     ├── RDRB V1 (с liq):    {len(v2_rdrb_v1):>5}")
print(f"     └── RDRB V2 (block=POI):{len(v2_rdrb_v2):>5}\n")

print(f"  V1 ∩ V2 overlap (one i-RDRB producing both):  {len(both_hits):>5}")
print(f"     (т.е. в этих случаях FVG есть и на C3-C4-C5, и на C4-C5-C6)\n")

# Частоты
years = (last_ts - window_start_ms) / (365 * 24 * 3600 * 1000)
print(f"  Frequency:")
print(f"    V1: {len(v1_hits)/years:.1f}/year = {len(v1_hits)/years/12:.1f}/month")
print(f"    V2: {len(v2_hits)/years:.1f}/year = {len(v2_hits)/years/12:.1f}/month")

print(f"\n--- Sample first 5 V2 hits ---")
for h in v2_hits[:5]:
    print(f"  {fmt_short(h['c1_ts'])}  {h['direction']:<5}  RDRB-{h['rdrb_variant']}  block={h['block'][0]:.0f}-{h['block'][1]:.0f}  fvg_v2={h['fvg_zone'][0]:.0f}-{h['fvg_zone'][1]:.0f}")

# CSV дамп V2
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/irdrb_fvg_v2_1h_6y.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['c1_open_time', 'direction', 'rdrb_variant', 'block_low', 'block_high', 'poi_low', 'poi_high', 'fvg_v2_low', 'fvg_v2_high'])
    for h in v2_hits:
        w.writerow([
            datetime.fromtimestamp(h['c1_ts']/1000, tz=timezone.utc).isoformat(),
            h['direction'], h['rdrb_variant'],
            f"{h['block'][0]:.2f}", f"{h['block'][1]:.2f}",
            f"{h['poi'][0]:.2f}", f"{h['poi'][1]:.2f}",
            f"{h['fvg_zone'][0]:.2f}", f"{h['fvg_zone'][1]:.2f}",
        ])
print(f"\nSaved V2 details → {OUT}")
print(f"\nTotal time: {time.time()-t0:.1f}s")
