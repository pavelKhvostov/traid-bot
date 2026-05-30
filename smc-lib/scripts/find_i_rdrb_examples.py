"""Поиск последних i-RDRB примеров на заданном ТФ для short и long."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb

MSK = timezone(timedelta(hours=3))
TF = sys.argv[1] if len(sys.argv) > 1 else "4h"
LIMIT = 1000


def fetch(interval: str, limit: int):
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    out = subprocess.check_output(["curl", "-s", url], timeout=30)
    return json.loads(out)


def to_candles(klines):
    return [
        Candle(open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]), open_time=int(k[0]))
        for k in klines
    ]


def fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


candles = to_candles(fetch(TF, LIMIT))
buckets: dict[str, list] = {"long": [], "short": []}

for i in range(len(candles) - 3):
    r = detect_i_rdrb(candles[i], candles[i + 1], candles[i + 2], candles[i + 3])
    if r is None:
        continue
    buckets[r.direction].append((candles[i], r))

print(f"TF={TF}, candles scanned={len(candles)}")
for d in ("long", "short"):
    print(f"\n=== Latest {d.upper()} i-RDRB on {TF} ===")
    if not buckets[d]:
        print("  (none found in window)")
        continue
    c1, r = max(buckets[d], key=lambda x: x[0].open_time)
    print(f"  C1 start (MSK): {fmt(c1.open_time)}")
    print(f"  C1:  O={r.rdrb.c1.open:.2f}  H={r.rdrb.c1.high:.2f}  L={r.rdrb.c1.low:.2f}  C={r.rdrb.c1.close:.2f}")
    print(f"  C2:  O={r.rdrb.c2.open:.2f}  H={r.rdrb.c2.high:.2f}  L={r.rdrb.c2.low:.2f}  C={r.rdrb.c2.close:.2f}")
    print(f"  C3:  O={r.rdrb.c3.open:.2f}  H={r.rdrb.c3.high:.2f}  L={r.rdrb.c3.low:.2f}  C={r.rdrb.c3.close:.2f}")
    print(f"  C4:  O={r.c4.open:.2f}  H={r.c4.high:.2f}  L={r.c4.low:.2f}  C={r.c4.close:.2f}")
    print(f"  RDRB: dir={r.rdrb.direction}  variant={r.rdrb.variant}")
    print(f"        POI={r.rdrb.poi}  block={r.rdrb.block}  liq={r.rdrb.liq}")
    cond = f"C4.close ({r.c4.close:.2f}) > block.top ({r.rdrb.block[1]:.2f})" if r.direction == "long" \
        else f"C4.close ({r.c4.close:.2f}) < block.bottom ({r.rdrb.block[0]:.2f})"
    print(f"  i-RDRB confirm: {cond}")
    print(f"  Total {d} i-RDRB on {TF}: {len(buckets[d])}")
