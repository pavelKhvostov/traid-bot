"""Полный подсчёт i-RDRB + FVG (same direction) по всем стандартным TF за 6 лет на BTC."""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

TFS = [
    ("15m", 15), ("30m", 30), ("45m", 45),
    ("1h", 60), ("2h", 120), ("3h", 180),
    ("4h", 240), ("6h", 360), ("8h", 480),
    ("12h", 720), ("1d", 1440), ("2d", 2880), ("3d", 4320),
]


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m...")
data = load_1m()
print(f"  {len(data):,} 1m candles ({datetime.fromtimestamp(data[0][0]/1000, tz=timezone.utc):%Y-%m-%d} → {datetime.fromtimestamp(data[-1][0]/1000, tz=timezone.utc):%Y-%m-%d})\n")

print(f"{'TF':<6} {'candles':<10} {'LONG':<7} {'SHORT':<7} {'TOTAL':<8} {'/year':<8}")
print("-" * 55)

grand_total = 0; grand_long = 0; grand_short = 0
years = (data[-1][0] - data[0][0]) / (365.25 * 24 * 3600 * 1000)

for name, tf_min in TFS:
    cs = aggregate(data, tf_min)
    n_long = 0; n_short = 0
    for i in range(len(cs) - 4):
        c1, c2, c3, c4, c5 = cs[i:i + 5]
        ir = detect_i_rdrb(c1, c2, c3, c4)
        if ir is None: continue
        fvg = detect_fvg(c3, c4, c5)
        if fvg is None or fvg.direction != ir.direction: continue
        if ir.direction == "long": n_long += 1
        else: n_short += 1
    total = n_long + n_short
    grand_total += total; grand_long += n_long; grand_short += n_short
    print(f"{name:<6} {len(cs):<10,} {n_long:<7} {n_short:<7} {total:<8} {total/years:<8.1f}")

print("-" * 55)
print(f"{'GRAND':<6} {'':10} {grand_long:<7} {grand_short:<7} {grand_total:<8} {grand_total/years:<8.1f}")
print(f"\nЗа {years:.1f} лет — ~{grand_total/years:.0f} паттернов в год по всем TF суммарно")
