"""Поиск последних i-RDRB + FVG (FVG в ту же сторону) на заданном ТФ.

Пагинирует через Binance API для полного исторического окна (по умолчанию 6 лет).
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
from elements.fvg.code import detect_fvg

MSK = timezone(timedelta(hours=3))
TF = sys.argv[1] if len(sys.argv) > 1 else "1h"
YEARS = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0

TF_HOURS = {"15m": 0.25, "30m": 0.5, "1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}
if TF not in TF_HOURS:
    raise SystemExit(f"Unsupported TF {TF!r}. Supported: {list(TF_HOURS)}")

END = datetime.now(tz=timezone.utc)
START = END - timedelta(days=365 * YEARS)


def fetch_chunk(start_ms: int, end_ms: int):
    url = (
        f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={TF}"
        f"&startTime={start_ms}&endTime={end_ms}&limit=1000"
    )
    return json.loads(subprocess.check_output(["curl", "-s", url], timeout=30))


def fetch_all():
    candles: list[Candle] = []
    cursor = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000)
    step_ms = int(TF_HOURS[TF] * 3600 * 1000)
    while cursor < end_ms:
        chunk = fetch_chunk(cursor, end_ms)
        if not chunk:
            break
        for k in chunk:
            candles.append(Candle(
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                open_time=int(k[0]),
            ))
        cursor = int(chunk[-1][0]) + step_ms
        if len(chunk) < 1000:
            break
    return candles


def fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


print(f"Fetching BTCUSDT {TF} for ~{YEARS} years...")
candles = fetch_all()
print(f"Fetched {len(candles)} candles ({fmt(candles[0].open_time)} → {fmt(candles[-1].open_time)})\n")

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
    print(f"=== Latest {d.upper()} i-RDRB + FVG on {TF} ===")
    if not buckets[d]:
        print("  (none found)\n")
        continue
    c1, ir, fvg, c5 = max(buckets[d], key=lambda x: x[0].open_time)
    print(f"  C1 start (MSK): {fmt(c1.open_time)}")
    for label, c in [("C1", ir.rdrb.c1), ("C2", ir.rdrb.c2), ("C3", ir.rdrb.c3), ("C4", ir.c4), ("C5", c5)]:
        d_ = "BULL" if c.close > c.open else ("BEAR" if c.close < c.open else "DOJI")
        print(f"  {label}: O={c.open:.2f}  H={c.high:.2f}  L={c.low:.2f}  C={c.close:.2f}  {d_}")
    print(f"  RDRB:  dir={ir.rdrb.direction}  variant={ir.rdrb.variant}")
    print(f"         POI={ir.rdrb.poi}  block={ir.rdrb.block}  liq={ir.rdrb.liq}")
    print(f"  i-RDRB dir={ir.direction}")
    print(f"  FVG    dir={fvg.direction}  zone={fvg.zone}  (height={fvg.zone[1]-fvg.zone[0]:.2f})")
    print(f"  Total {d} i-RDRB+FVG on {TF} over {YEARS}y: {len(buckets[d])}\n")
