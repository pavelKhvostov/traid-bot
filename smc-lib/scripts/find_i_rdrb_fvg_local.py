"""Поиск последних i-RDRB + FVG на локальных 1m CSV с агрегацией в HTF.

Использует ~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv (см. [[btc-data-1m-csv]]).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

MSK = timezone(timedelta(hours=3))
TF = sys.argv[1] if len(sys.argv) > 1 else "1h"
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 1

TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720, "1d": 1440}
if TF not in TF_MINUTES:
    raise SystemExit(f"Unsupported TF {TF!r}")

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.reader(f)
        next(reader)  # header
        for r in reader:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(rows_1m, tf_min: int):
    """Группирует 1m свечи в HTF, выравнивая по началу UTC-эпохи (что совпадает с Binance-anchors для 1h/2h/4h)."""
    bucket_ms = tf_min * 60 * 1000
    out: list[Candle] = []
    cur_bucket = None
    cur_o = cur_h = cur_l = cur_c = 0.0
    for ts, o, h, l, c in rows_1m:
        b = ts - (ts % bucket_ms)
        if b != cur_bucket:
            if cur_bucket is not None:
                out.append(Candle(open=cur_o, high=cur_h, low=cur_l, close=cur_c, open_time=cur_bucket))
            cur_bucket = b
            cur_o, cur_h, cur_l, cur_c = o, h, l, c
        else:
            cur_h = max(cur_h, h)
            cur_l = min(cur_l, l)
            cur_c = c
    if cur_bucket is not None:
        out.append(Candle(open=cur_o, high=cur_h, low=cur_l, close=cur_c, open_time=cur_bucket))
    return out


def fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


print(f"Loading 1m CSV...")
rows_1m = load_1m()
print(f"Loaded {len(rows_1m):,} 1m candles ({fmt(rows_1m[0][0])} → {fmt(rows_1m[-1][0])})")

print(f"Aggregating to {TF}...")
candles = aggregate(rows_1m, TF_MINUTES[TF])
print(f"Aggregated to {len(candles):,} {TF} candles\n")

buckets: dict[str, list] = {"long": [], "short": []}
for i in range(len(candles) - 4):
    c1, c2, c3, c4, c5 = candles[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None:
        continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction:
        continue
    buckets[ir.direction].append((c1, ir, fvg, c5))

for d in ("long", "short"):
    print(f"=== Top-{TOP_N} latest {d.upper()} i-RDRB + FVG on {TF} ===")
    if not buckets[d]:
        print("  (none found)\n")
        continue
    latest = sorted(buckets[d], key=lambda x: x[0].open_time, reverse=True)[:TOP_N]
    for k, (c1, ir, fvg, c5) in enumerate(latest, 1):
        print(f"\n  [{k}] C1 start (MSK): {fmt(c1.open_time)}")
        for label, c in [("C1", ir.rdrb.c1), ("C2", ir.rdrb.c2), ("C3", ir.rdrb.c3), ("C4", ir.c4), ("C5", c5)]:
            d_ = "BULL" if c.close > c.open else ("BEAR" if c.close < c.open else "DOJI")
            print(f"      {label}: O={c.open:.2f}  H={c.high:.2f}  L={c.low:.2f}  C={c.close:.2f}  {d_}")
        print(f"      RDRB: dir={ir.rdrb.direction}  variant={ir.rdrb.variant}")
        print(f"            POI={ir.rdrb.poi}  block={ir.rdrb.block}  liq={ir.rdrb.liq}")
        print(f"      FVG zone={fvg.zone}  (height={fvg.zone[1]-fvg.zone[0]:.2f})")
    print(f"\n  Total {d} i-RDRB+FVG on {TF}: {len(buckets[d])}\n")
